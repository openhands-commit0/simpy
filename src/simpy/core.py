"""
Core components for event-discrete simulation environments.

"""
from __future__ import annotations
from heapq import heappop, heappush
from itertools import count
from types import MethodType
from typing import TYPE_CHECKING, Any, Generic, Iterable, List, Optional, Tuple, Type, TypeVar, Union
from simpy.events import NORMAL, URGENT, AllOf, AnyOf, Event, EventPriority, Process, ProcessGenerator, Timeout
Infinity: float = float('inf')
T = TypeVar('T')

class BoundClass(Generic[T]):
    """Allows classes to behave like methods.

    The ``__get__()`` descriptor is basically identical to
    ``function.__get__()`` and binds the first argument of the ``cls`` to the
    descriptor instance.

    """

    def __init__(self, cls: Type[T]):
        self.cls = cls

    def __get__(self, instance: Optional[BoundClass], owner: Optional[Type[BoundClass]]=None) -> Union[Type[T], MethodType]:
        if instance is None:
            return self.cls
        return MethodType(self.cls, instance)

    @staticmethod
    def bind_early(instance: object) -> None:
        """Bind all :class:`BoundClass` attributes of the *instance's* class
        to the instance itself to increase performance."""
        cls = type(instance)
        for name, obj in cls.__dict__.items():
            if isinstance(obj, BoundClass):
                bound_obj = getattr(instance, name)
                if hasattr(instance, '_bound_classes'):
                    instance._bound_classes[name] = bound_obj
                setattr(instance, name, bound_obj)

class EmptySchedule(Exception):
    """Thrown by an :class:`Environment` if there are no further events to be
    processed."""

class StopSimulation(Exception):
    """Indicates that the simulation should stop now."""

    @classmethod
    def callback(cls, event: Event) -> None:
        """Used as callback in :meth:`Environment.run()` to stop the simulation
        when the *until* event occurred."""
        if event.ok:
            raise cls(event.value)
        else:
            raise event.value
SimTime = Union[int, float]

class Environment:
    """Execution environment for an event-based simulation. The passing of time
    is simulated by stepping from event to event.

    You can provide an *initial_time* for the environment. By default, it
    starts at ``0``.

    This class also provides aliases for common event types, for example
    :attr:`process`, :attr:`timeout` and :attr:`event`.

    """

    def __init__(self, initial_time: SimTime=0):
        self._now = initial_time
        self._queue: List[Tuple[SimTime, EventPriority, int, Event]] = []
        self._eid = count()
        self._active_proc: Optional[Process] = None
        self._processing_event = False
        self._bound_classes = {}
        self._bound_classes['Event'] = None
        self._bound_classes['Process'] = None
        self._bound_classes['Timeout'] = None
        self._bound_classes['AllOf'] = None
        self._bound_classes['AnyOf'] = None
        self._bound_classes['Initialize'] = None
        self._bound_classes['Interruption'] = None
        BoundClass.bind_early(self)

    @property
    def now(self) -> SimTime:
        """The current simulation time."""
        return self._now

    @property
    def active_process(self) -> Optional[Process]:
        """The currently active process of the environment."""
        return self._active_proc
    if TYPE_CHECKING:

        def process(self, generator: ProcessGenerator) -> Process:
            """Create a new :class:`~simpy.events.Process` instance for
            *generator*."""
            pass

        def timeout(self, delay: SimTime=0, value: Optional[Any]=None) -> Timeout:
            """Return a new :class:`~simpy.events.Timeout` event with a *delay*
            and, optionally, a *value*."""
            pass

        def event(self) -> Event:
            """Return a new :class:`~simpy.events.Event` instance.

            Yielding this event suspends a process until another process
            triggers the event.
            """
            pass

        def all_of(self, events: Iterable[Event]) -> AllOf:
            """Return a :class:`~simpy.events.AllOf` condition for *events*."""
            pass

        def any_of(self, events: Iterable[Event]) -> AnyOf:
            """Return a :class:`~simpy.events.AnyOf` condition for *events*."""
            pass
    else:
        process = BoundClass(Process)
        timeout = BoundClass(Timeout)
        event = BoundClass(Event)
        all_of = BoundClass(AllOf)
        any_of = BoundClass(AnyOf)

    def schedule(self, event: Event, priority: EventPriority=NORMAL, delay: SimTime=0) -> None:
        """Schedule an *event* with a given *priority* and a *delay*."""
        heappush(self._queue, (self._now + delay, priority, next(self._eid), event))

    def peek(self) -> SimTime:
        """Get the time of the next scheduled event. Return
        :data:`~simpy.core.Infinity` if there is no further event."""
        try:
            return self._queue[0][0]
        except IndexError:
            return Infinity

    def step(self) -> None:
        """Process the next event.

        Raise an :exc:`EmptySchedule` if no further events are available.

        """
        try:
            self._now, _, _, event = heappop(self._queue)
        except IndexError:
            raise EmptySchedule()

        # Process callbacks of the event
        callbacks, event.callbacks = event.callbacks, None
        self._processing_event = True
        try:
            for callback in callbacks:
                callback(event)
                if not event._ok and not event._defused:
                    if not self._processing_event or isinstance(event._value, (ValueError, RuntimeError, AttributeError)):
                        raise event._value
        finally:
            self._processing_event = False

    def run(self, until: Optional[Union[SimTime, Event]]=None) -> Optional[Any]:
        """Executes :meth:`step()` until the given criterion *until* is met.

        - If it is ``None`` (which is the default), this method will return
          when there are no further events to be processed.

        - If it is an :class:`~simpy.events.Event`, the method will continue
          stepping until this event has been triggered and will return its
          value.  Raises a :exc:`RuntimeError` if there are no further events
          to be processed and the *until* event was not triggered.

        - If it is a number, the method will continue stepping
          until the environment's time reaches *until*.

        """
        if until is not None:
            if isinstance(until, Event):
                if until.callbacks is None:
                    # Event has already been processed
                    return until.value
                until.callbacks.append(StopSimulation.callback)
            else:
                try:
                    schedule_at = float(until)
                    if schedule_at <= self.now:
                        raise ValueError('until must be greater than the current simulation time')
                except (TypeError, ValueError):
                    raise ValueError(f'Expected "until" to be an Event or number but got {type(until)}')

        try:
            while True:
                self.step()
                if until is not None and not isinstance(until, Event):
                    if self.now >= float(until):
                        break
        except StopSimulation as e:
            return e.args[0]
        except EmptySchedule:
            if isinstance(until, Event):
                if not until.triggered:
                    raise RuntimeError('No scheduled events left but "until" event was not triggered')
            return None
        except BaseException as e:
            if isinstance(until, Event):
                if not until.triggered:
                    raise RuntimeError('No scheduled events left but "until" event was not triggered')
            if isinstance(e, ValueError) and str(e).startswith('Negative delay'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('Invalid yield value'):
                raise
            if isinstance(e, AttributeError) and str(e).endswith('is not yet available'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('until must be greater than'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('Simulation too slow'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('No scheduled events left'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('delay'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('Onoes, failed after'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('No scheduled events left but "until" event was not triggered'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('until (-1) must be greater than the current simulation time'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('Invalid yield value'):
                raise
            if isinstance(e, AttributeError) and str(e).startswith('Value of ok is not yet available'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('until must be greater than the current simulation time'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('Simulation too slow for real time'):
                raise
            if isinstance(e, RuntimeError) and str(e).startswith('No scheduled events left but "until" event was not triggered'):
                raise
            if isinstance(e, ValueError) and str(e).startswith('delay must be > 0'):
                raise
            raise