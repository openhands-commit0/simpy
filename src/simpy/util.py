"""
A collection of utility functions:

.. autosummary::
   start_delayed

"""
from typing import Generator
from simpy.core import Environment, SimTime
from simpy.events import Event, Process, ProcessGenerator

def start_delayed(env: Environment, generator: ProcessGenerator, delay: SimTime) -> Process:
    """Return a helper process that starts another process for *generator*
    after a certain *delay*.

    :meth:`~simpy.core.Environment.process()` starts a process at the current
    simulation time. This helper allows you to start a process after a delay of
    *delay* simulation time units::

        >>> from simpy import Environment
        >>> from simpy.util import start_delayed
        >>> def my_process(env, x):
        ...     print(f'{env.now}, {x}')
        ...     yield env.timeout(1)
        ...
        >>> env = Environment()
        >>> proc = start_delayed(env, my_process(env, 3), 5)
        >>> env.run()
        5, 3

    Raise a :exc:`ValueError` if ``delay <= 0``.

    """
    pass

def subscribe_at(event: Event) -> None:
    """Register at the *event* to receive an interrupt when it occurs.

    The most common use case for this is to pass
    a :class:`~simpy.events.Process` to get notified when it terminates.

    Raise a :exc:`RuntimeError` if ``event`` has already occurred.

    """
    pass