"""
This module contains the basic event types used in SimPy.

The base class for all events is :class:`Event`. Though it can be directly
used, there are several specialized subclasses of it.

.. autosummary::

    ~simpy.events.Event
    ~simpy.events.Timeout
    ~simpy.events.Process
    ~simpy.events.AnyOf
    ~simpy.events.AllOf

"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable, Dict, Generator, Iterable, Iterator, List, NewType, Optional, Tuple, TypeVar
from simpy.exceptions import Interrupt
if TYPE_CHECKING:
    from types import FrameType
    from simpy.core import Environment, SimTime
PENDING: object = object()
'Unique object to identify pending values of events.'
EventPriority = NewType('EventPriority', int)
URGENT: EventPriority = EventPriority(0)
'Priority of interrupts and process initialization events.'
NORMAL: EventPriority = EventPriority(1)
'Default priority used by events.'

class Event:
    """An event that may happen at some point in time.

    An event

    - may happen (:attr:`triggered` is ``False``),
    - is going to happen (:attr:`triggered` is ``True``) or
    - has happened (:attr:`processed` is ``True``).

    Every event is bound to an environment *env* and is initially not
    triggered. Events are scheduled for processing by the environment after
    they are triggered by either :meth:`succeed`, :meth:`fail` or
    :meth:`trigger`. These methods also set the *ok* flag and the *value* of
    the event.

    An event has a list of :attr:`callbacks`. A callback can be any callable.
    Once an event gets processed, all callbacks will be invoked with the event
    as the single argument. Callbacks can check if the event was successful by
    examining *ok* and do further processing with the *value* it has produced.

    Failed events are never silently ignored and will raise an exception upon
    being processed. If a callback handles an exception, it must set
    :attr:`defused` to ``True`` to prevent this.

    This class also implements ``__and__()`` (``&``) and ``__or__()`` (``|``).
    If you concatenate two events using one of these operators,
    a :class:`Condition` event is generated that lets you wait for both or one
    of them.

    """
    _ok: bool
    _defused: bool
    _value: Any = PENDING

    def __init__(self, env: Environment):
        self.env = env
        'The :class:`~simpy.core.Environment` the event lives in.'
        self.callbacks: EventCallbacks = []
        'List of functions that are called when the event is processed.'

    def __repr__(self) -> str:
        """Return the description of the event (see :meth:`_desc`) with the id
        of the event."""
        return f'<{self._desc()} object at {id(self):#x}>'

    def _desc(self) -> str:
        """Return a string *Event()*."""
        pass

    @property
    def triggered(self) -> bool:
        """Becomes ``True`` if the event has been triggered and its callbacks
        are about to be invoked."""
        pass

    @property
    def processed(self) -> bool:
        """Becomes ``True`` if the event has been processed (e.g., its
        callbacks have been invoked)."""
        pass

    @property
    def ok(self) -> bool:
        """Becomes ``True`` when the event has been triggered successfully.

        A "successful" event is one triggered with :meth:`succeed()`.

        :raises AttributeError: if accessed before the event is triggered.

        """
        pass

    @property
    def defused(self) -> bool:
        """Becomes ``True`` when the failed event's exception is "defused".

        When an event fails (i.e. with :meth:`fail()`), the failed event's
        `value` is an exception that will be re-raised when the
        :class:`~simpy.core.Environment` processes the event (i.e. in
        :meth:`~simpy.core.Environment.step()`).

        It is also possible for the failed event's exception to be defused by
        setting :attr:`defused` to ``True`` from an event callback. Doing so
        prevents the event's exception from being re-raised when the event is
        processed by the :class:`~simpy.core.Environment`.

        """
        pass

    @property
    def value(self) -> Optional[Any]:
        """The value of the event if it is available.

        The value is available when the event has been triggered.

        Raises :exc:`AttributeError` if the value is not yet available.

        """
        pass

    def trigger(self, event: Event) -> None:
        """Trigger the event with the state and value of the provided *event*.
        Return *self* (this event instance).

        This method can be used directly as a callback function to trigger
        chain reactions.

        """
        pass

    def succeed(self, value: Optional[Any]=None) -> Event:
        """Set the event's value, mark it as successful and schedule it for
        processing by the environment. Returns the event instance.

        Raises :exc:`RuntimeError` if this event has already been triggerd.

        """
        pass

    def fail(self, exception: Exception) -> Event:
        """Set *exception* as the events value, mark it as failed and schedule
        it for processing by the environment. Returns the event instance.

        Raises :exc:`TypeError` if *exception* is not an :exc:`Exception`.

        Raises :exc:`RuntimeError` if this event has already been triggered.

        """
        pass

    def __and__(self, other: Event) -> Condition:
        """Return a :class:`~simpy.events.Condition` that will be triggered if
        both, this event and *other*, have been processed."""
        return Condition(self.env, Condition.all_events, [self, other])

    def __or__(self, other: Event) -> Condition:
        """Return a :class:`~simpy.events.Condition` that will be triggered if
        either this event or *other* have been processed (or even both, if they
        happened concurrently)."""
        return Condition(self.env, Condition.any_events, [self, other])
EventType = TypeVar('EventType', bound=Event)
EventCallback = Callable[[EventType], None]
EventCallbacks = List[EventCallback]

class Timeout(Event):
    """A :class:`~simpy.events.Event` that gets processed after a *delay* has
    passed.

    This event is automatically triggered when it is created.


    """

    def __init__(self, env: Environment, delay: SimTime, value: Optional[Any]=None):
        if delay < 0:
            raise ValueError(f'Negative delay {delay}')
        self.env = env
        self.callbacks: EventCallbacks = []
        self._value = value
        self._delay = delay
        self._ok = True
        env.schedule(self, NORMAL, delay)

    def _desc(self) -> str:
        """Return a string *Timeout(delay[, value=value])*."""
        pass

class Initialize(Event):
    """Initializes a process. Only used internally by :class:`Process`.

    This event is automatically triggered when it is created.

    """

    def __init__(self, env: Environment, process: Process):
        self.env = env
        self.callbacks: EventCallbacks = [process._resume]
        self._value: Any = None
        self._ok = True
        env.schedule(self, URGENT)

class Interruption(Event):
    """Immediately schedules an :class:`~simpy.exceptions.Interrupt` exception
    with the given *cause* to be thrown into *process*.

    This event is automatically triggered when it is created.

    """

    def __init__(self, process: Process, cause: Optional[Any]):
        self.env = process.env
        self.callbacks: EventCallbacks = [self._interrupt]
        self._value = Interrupt(cause)
        self._ok = False
        self._defused = True
        if process._value is not PENDING:
            raise RuntimeError(f'{process} has terminated and cannot be interrupted.')
        if process is self.env.active_process:
            raise RuntimeError('A process is not allowed to interrupt itself.')
        self.process = process
        self.env.schedule(self, URGENT)
ProcessGenerator = Generator[Event, Any, Any]

class Process(Event):
    """Process an event yielding generator.

    A generator (also known as a coroutine) can suspend its execution by
    yielding an event. ``Process`` will take care of resuming the generator
    with the value of that event once it has happened. The exception of failed
    events is thrown into the generator.

    ``Process`` itself is an event, too. It is triggered, once the generator
    returns or raises an exception. The value of the process is the return
    value of the generator or the exception, respectively.

    Processes can be interrupted during their execution by :meth:`interrupt`.

    """

    def __init__(self, env: Environment, generator: ProcessGenerator):
        if not hasattr(generator, 'throw'):
            raise ValueError(f'{generator} is not a generator.')
        self.env = env
        self.callbacks: EventCallbacks = []
        self._generator = generator
        self._target: Event = Initialize(env, self)

    def _desc(self) -> str:
        """Return a string *Process(process_func_name)*."""
        pass

    @property
    def target(self) -> Event:
        """The event that the process is currently waiting for.

        Returns ``None`` if the process is dead, or it is currently being
        interrupted.

        """
        pass

    @property
    def name(self) -> str:
        """Name of the function used to start the process."""
        pass

    @property
    def is_alive(self) -> bool:
        """``True`` until the process generator exits."""
        pass

    def interrupt(self, cause: Optional[Any]=None) -> None:
        """Interrupt this process optionally providing a *cause*.

        A process cannot be interrupted if it already terminated. A process can
        also not interrupt itself. Raise a :exc:`RuntimeError` in these
        cases.

        """
        pass

    def _resume(self, event: Event) -> None:
        """Resumes the execution of the process with the value of *event*. If
        the process generator exits, the process itself will get triggered with
        the return value or the exception of the generator."""
        pass

class ConditionValue:
    """Result of a :class:`~simpy.events.Condition`. It supports convenient
    dict-like access to the triggered events and their values. The events are
    ordered by their occurrences in the condition."""

    def __init__(self) -> None:
        self.events: List[Event] = []

    def __getitem__(self, key: Event) -> Any:
        if key not in self.events:
            raise KeyError(str(key))
        return key._value

    def __contains__(self, key: Event) -> bool:
        return key in self.events

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConditionValue):
            return self.events == other.events
        elif isinstance(other, dict):
            return self.todict() == other
        else:
            return NotImplemented

    def __repr__(self) -> str:
        return f'<ConditionValue {self.todict()}>'

    def __iter__(self) -> Iterator[Event]:
        return self.keys()

class Condition(Event):
    """An event that gets triggered once the condition function *evaluate*
    returns ``True`` on the given list of *events*.

    The value of the condition event is an instance of :class:`ConditionValue`
    which allows convenient access to the input events and their values. The
    :class:`ConditionValue` will only contain entries for those events that
    occurred before the condition is processed.

    If one of the events fails, the condition also fails and forwards the
    exception of the failing event.

    The *evaluate* function receives the list of target events and the number
    of processed events in this list: ``evaluate(events, processed_count)``. If
    it returns ``True``, the condition is triggered. The
    :func:`Condition.all_events()` and :func:`Condition.any_events()` functions
    are used to implement *and* (``&``) and *or* (``|``) for events.

    Condition events can be nested.

    """

    def __init__(self, env: Environment, evaluate: Callable[[Tuple[Event, ...], int], bool], events: Iterable[Event]):
        super().__init__(env)
        self._evaluate = evaluate
        self._events = tuple(events)
        self._count = 0
        if not self._events:
            self.succeed(ConditionValue())
            return
        for event in self._events:
            if self.env != event.env:
                raise ValueError('It is not allowed to mix events from different environments')
        for event in self._events:
            if event.callbacks is None:
                self._check(event)
            else:
                event.callbacks.append(self._check)
        assert isinstance(self.callbacks, list)
        self.callbacks.append(self._build_value)

    def _desc(self) -> str:
        """Return a string *Condition(evaluate, [events])*."""
        pass

    def _populate_value(self, value: ConditionValue) -> None:
        """Populate the *value* by recursively visiting all nested
        conditions."""
        pass

    def _build_value(self, event: Event) -> None:
        """Build the value of this condition."""
        pass

    def _remove_check_callbacks(self) -> None:
        """Remove _check() callbacks from events recursively.

        Once the condition has triggered, the condition's events no longer need
        to have _check() callbacks. Removing the _check() callbacks is
        important to break circular references between the condition and
        untriggered events.

        """
        pass

    def _check(self, event: Event) -> None:
        """Check if the condition was already met and schedule the *event* if
        so."""
        pass

    @staticmethod
    def all_events(events: Tuple[Event, ...], count: int) -> bool:
        """An evaluation function that returns ``True`` if all *events* have
        been triggered."""
        pass

    @staticmethod
    def any_events(events: Tuple[Event, ...], count: int) -> bool:
        """An evaluation function that returns ``True`` if at least one of
        *events* has been triggered."""
        pass

class AllOf(Condition):
    """A :class:`~simpy.events.Condition` event that is triggered if all of
    a list of *events* have been successfully triggered. Fails immediately if
    any of *events* failed.

    """

    def __init__(self, env: Environment, events: Iterable[Event]):
        super().__init__(env, Condition.all_events, events)

class AnyOf(Condition):
    """A :class:`~simpy.events.Condition` event that is triggered if any of
    a list of *events* has been successfully triggered. Fails immediately if
    any of *events* failed.

    """

    def __init__(self, env: Environment, events: Iterable[Event]):
        super().__init__(env, Condition.any_events, events)

def _describe_frame(frame: FrameType) -> str:
    """Print filename, line number and function name of a stack frame."""
    pass