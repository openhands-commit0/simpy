"""Execution environment for events that synchronizes passing of time
with the real-time (aka *wall-clock time*).

"""
from time import monotonic, sleep
from simpy.core import EmptySchedule, Environment, Infinity, SimTime

class RealtimeEnvironment(Environment):
    """Execution environment for an event-based simulation which is
    synchronized with the real-time (also known as wall-clock time). A time
    step will take *factor* seconds of real time (one second by default).
    A step from ``0`` to ``3`` with a ``factor=0.5`` will, for example, take at
    least
    1.5 seconds.

    The :meth:`step()` method will raise a :exc:`RuntimeError` if a time step
    took too long to compute. This behaviour can be disabled by setting
    *strict* to ``False``.

    """

    def __init__(self, initial_time: SimTime=0, factor: float=1.0, strict: bool=True):
        Environment.__init__(self, initial_time)
        self.env_start = initial_time
        self.real_start = monotonic()
        self._factor = factor
        self._strict = strict

    @property
    def factor(self) -> float:
        """Scaling factor of the real-time."""
        return self._factor

    @property
    def strict(self) -> bool:
        """Running mode of the environment. :meth:`step()` will raise a
        :exc:`RuntimeError` if this is set to ``True`` and the processing of
        events takes too long."""
        return self._strict

    def sync(self) -> None:
        """Synchronize the internal time with the current wall-clock time.

        This can be useful to prevent :meth:`step()` from raising an error if
        a lot of time passes between creating the RealtimeEnvironment and
        calling :meth:`run()` or :meth:`step()`.

        """
        self.real_start = monotonic()

    def step(self) -> None:
        """Process the next event after enough real-time has passed for the
        event to happen.

        The delay is scaled according to the real-time :attr:`factor`. With
        :attr:`strict` mode enabled, a :exc:`RuntimeError` will be raised, if
        the event is processed too slowly.

        """
        evt_time = self.peek()
        if evt_time is Infinity:
            raise EmptySchedule()

        real_time = monotonic() - self.real_start
        sim_time = (evt_time - self.env_start) * self.factor

        if sim_time > real_time:
            sleep(sim_time - real_time)
        elif self.strict and sim_time < real_time:
            # Events scheduled for time *t* may be triggered at real-time
            # *t + ε*. For example, if an event is scheduled for t=0, it
            # may be triggered at real-time ε, which is not a problem.
            if real_time - sim_time > self.factor:
                # Events scheduled for time *t* may not be triggered at
                # real-time *t + factor + ε*, as this most likely indicates
                # a problem with the simulation.
                raise RuntimeError('Simulation too slow for real time (%.3fs).' % (real_time - sim_time))

        return Environment.step(self)