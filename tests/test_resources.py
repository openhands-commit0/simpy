"""
Theses test cases demonstrate the API for shared resources.

"""
# Pytest gets the parameters "env" and "log" from the *conftest.py* file
import pytest

import simpy
from simpy.resources.resource import Preempted

#
# Tests for Resource
#


def test_resource(env, log):
    """A *resource* is something with a limited numer of slots that need
    to be requested before and released after the usage (e.g., gas pumps
    at a gas station).

    """

    def pem(env, name, resource, log):
        req = resource.request()
        yield req
        assert resource.count == 1

        yield env.timeout(1)
        resource.release(req)

        log.append((name, env.now))

    resource = simpy.Resource(env, capacity=1)
    assert resource.capacity == 1
    assert resource.count == 0
    env.process(pem(env, 'a', resource, log))
    env.process(pem(env, 'b', resource, log))
    env.run()

    assert log == [('a', 1), ('b', 2)]


def test_resource_capacity(env):
    with pytest.raises(ValueError, match=r'"capacity" must be > 0.'):
        simpy.Resource(env, 0)


def test_resource_context_manager(env, log):
    """The event that ``Resource.request()`` returns can be used as
    Context Manager."""

    def pem(env, name, resource, log):
        with resource.request() as request:
            yield request
            yield env.timeout(1)

        log.append((name, env.now))

    resource = simpy.Resource(env, capacity=1)
    env.process(pem(env, 'a', resource, log))
    env.process(pem(env, 'b', resource, log))
    env.run()

    assert log == [('a', 1), ('b', 2)]


def test_resource_slots(env, log):
    def pem(env, name, resource, log):
        with resource.request() as req:
            yield req
            log.append((name, env.now))
            yield env.timeout(1)

    resource = simpy.Resource(env, capacity=3)
    for i in range(9):
        env.process(pem(env, str(i), resource, log))
    env.run()

    assert log == [
        ('0', 0),
        ('1', 0),
        ('2', 0),
        ('3', 1),
        ('4', 1),
        ('5', 1),
        ('6', 2),
        ('7', 2),
        ('8', 2),
    ]


def test_resource_continue_after_interrupt(env):
    """A process may be interrupted while waiting for a resource but
    should be able to continue waiting afterwards."""

    def pem(env, res):
        with res.request() as req:
            yield req
            yield env.timeout(1)

    def victim(env, res):
        evt = res.request()
        try:
            yield evt
            pytest.fail('Should not have gotten the resource.')
        except simpy.Interrupt:
            yield evt
            res.release(evt)
            assert env.now == 1

    def interruptor(proc):
        proc.interrupt()
        return 0
        yield

    res = simpy.Resource(env, 1)
    env.process(pem(env, res))
    proc = env.process(victim(env, res))
    env.process(interruptor(proc))
    env.run()


def test_resource_release_after_interrupt(env):
    """A process needs to release a resource, even if it was interrupted
    and does not continue to wait for it."""

    def blocker(env, res):
        with res.request() as req:
            yield req
            yield env.timeout(1)

    def victim(env, res):
        evt = res.request()
        try:
            yield evt
            pytest.fail('Should not have gotten the resource.')
        except simpy.Interrupt:
            # Don't wait for the resource
            res.release(evt)
            assert env.now == 0

    def interruptor(proc):
        proc.interrupt()
        return 0
        yield

    res = simpy.Resource(env, 1)
    env.process(blocker(env, res))
    victim_proc = env.process(victim(env, res))
    env.process(interruptor(victim_proc))
    env.run()


def test_resource_immediate_requests(env):
    """A process must not acquire a resource if it releases it and immediately
    requests it again while there are already other requesting processes."""

    def child(env, res):
        result = []
        for _ in range(3):
            with res.request() as req:
                yield req
                result.append(env.now)
                yield env.timeout(1)
        return result

    def parent(env):
        res = simpy.Resource(env, 1)
        child_a = env.process(child(env, res))
        child_b = env.process(child(env, res))

        a_acquire_times = yield child_a
        b_acquire_times = yield child_b

        assert a_acquire_times == [0, 2, 4]
        assert b_acquire_times == [1, 3, 5]

    env.process(parent(env))
    env.run()


def test_resource_cm_exception(env, log):
    """Resource with context manager receives an exception."""

    def process(env, resource, log, raise_):
        with resource.request() as req:
            yield req
            yield env.timeout(1)
            log.append(env.now)
            if raise_:
                with pytest.raises(ValueError, match='Foo'):
                    raise ValueError('Foo')

    resource = simpy.Resource(env, 1)
    env.process(process(env, resource, log, True))
    # The second process is used to check if it was able to access the
    # resource:
    env.process(process(env, resource, log, False))
    env.run()

    assert log == [1, 2]


def test_resource_with_condition(env):
    def process(env, resource):
        with resource.request() as res_event:
            result = yield res_event | env.timeout(1)
            assert res_event in result

    resource = simpy.Resource(env, 1)
    env.process(process(env, resource))
    env.run()


def test_resource_with_priority_queue(env):
    def process(env, delay, resource, priority, res_time):
        yield env.timeout(delay)
        req = resource.request(priority=priority)
        yield req
        assert env.now == res_time
        yield env.timeout(5)
        resource.release(req)

    resource = simpy.PriorityResource(env, capacity=1)
    env.process(process(env, 0, resource, 2, 0))
    env.process(process(env, 2, resource, 3, 10))
    env.process(process(env, 2, resource, 3, 15))  # Test equal priority
    env.process(process(env, 4, resource, 1, 5))
    env.run()


def test_sorted_queue_maxlen(env):
    """Requests must fail if more than *maxlen* requests happen
    concurrently."""
    resource = simpy.PriorityResource(env, capacity=1)
    resource.put_queue.maxlen = 1  # pyright: ignore

    def process(env, resource):
        # The first request immediately triggered and does not enter the queue.
        resource.request(priority=1)
        # The second request is enqueued.
        resource.request(priority=1)
        with pytest.raises(RuntimeError, match='Cannot append event. Queue is full.'):
            # The third request will now fail.
            resource.request(priority=1)
        yield env.timeout(0)

    env.process(process(env, resource))
    env.run()


def test_get_users(env):
    def process(env, resource):
        with resource.request() as req:
            yield req
            yield env.timeout(1)

    resource = simpy.Resource(env, 1)
    procs = [env.process(process(env, resource)) for _ in range(3)]
    env.run(until=1)
    assert [evt.proc for evt in resource.users] == procs[0:1]
    assert [evt.proc for evt in resource.queue] == procs[1:]

    env.run(until=2)
    assert [evt.proc for evt in resource.users] == procs[1:2]
    assert [evt.proc for evt in resource.queue] == procs[2:]


#
# Tests for PreemptiveResource
#
def test_preemptive_resource(env):
    """Processes with a higher priority may preempt requests of lower priority
    processes. Note that higher priorities are indicated by a lower number
    value."""

    def proc_a(_, resource, prio):
        try:
            with resource.request(priority=prio) as req:
                yield req
                pytest.fail('Should have received an interrupt/preemption.')
        except simpy.Interrupt:
            pass

    def proc_b(_, resource, prio):
        with resource.request(priority=prio) as req:
            yield req

    resource = simpy.PreemptiveResource(env, 1)
    env.process(proc_a(env, resource, 1))
    env.process(proc_b(env, resource, 0))

    env.run()


def test_preemptive_resource_timeout_0(env):
    def proc_a(env, resource, prio):
        with resource.request(priority=prio) as req:
            try:
                yield req
                yield env.timeout(1)
                pytest.fail('Should have received an interrupt/preemption.')
            except simpy.Interrupt:
                pass
        yield env.event()

    def proc_b(_, resource, prio):
        with resource.request(priority=prio) as req:
            yield req

    resource = simpy.PreemptiveResource(env, 1)
    env.process(proc_a(env, resource, 1))
    env.process(proc_b(env, resource, 0))

    env.run()


def test_mixed_preemption(env, log):
    def p(id, env, res, delay, prio, preempt, log):
        yield env.timeout(delay)
        with res.request(priority=prio, preempt=preempt) as req:
            try:
                yield req
                yield env.timeout(2)
                log.append((env.now, id))
            except simpy.Interrupt as ir:
                assert ir is not None  # noqa: PT017
                assert isinstance(ir.cause, Preempted)  # noqa: PT017
                log.append((env.now, id, (ir.cause.by, ir.cause.usage_since)))

    res = simpy.PreemptiveResource(env, 1)
    # p0: First user:
    env.process(p(0, env, res, delay=0, prio=2, preempt=True, log=log))
    # p1: Waits (cannot preempt):
    env.process(p(1, env, res, delay=0, prio=2, preempt=True, log=log))
    # p2: Waits later, but has a higher prio:
    env.process(p(2, env, res, delay=1, prio=1, preempt=False, log=log))
    # p3: Preempt the above proc:
    p3 = env.process(p(3, env, res, delay=3, prio=0, preempt=True, log=log))
    # p4: Wait again:
    env.process(p(4, env, res, delay=4, prio=3, preempt=True, log=log))

    env.run()

    assert log == [
        (2, 0),  # p0 done
        (3, 2, (p3, 2)),  # p2 got it next, but got interrupted by p3
        (5, 3),  # p3 done
        (7, 1),  # p1 done (finally got the resource)
        (9, 4),  # p4 done
    ]


def test_nested_preemption(env, log):
    def process(id, env, res, delay, prio, preempt, log):
        yield env.timeout(delay)
        with res.request(priority=prio, preempt=preempt) as req:
            try:
                yield req
                yield env.timeout(5)
                log.append((env.now, id))
            except simpy.Interrupt as ir:
                assert isinstance(ir.cause, Preempted)  # noqa: PT017
                log.append((env.now, id, (ir.cause.by, ir.cause.usage_since)))

    def process2(id, env, res0, res1, delay, prio, preempt, log):
        yield env.timeout(delay)
        with res0.request(priority=prio, preempt=preempt) as req0:
            try:
                yield req0
                with res1.request(priority=prio, preempt=preempt) as req1:
                    try:
                        yield req1
                        yield env.timeout(5)
                        log.append((env.now, id))
                    except simpy.Interrupt as ir:
                        assert isinstance(ir.cause, Preempted)  # noqa: PT017
                        log.append(
                            (
                                env.now,
                                id,
                                (ir.cause.by, ir.cause.usage_since, ir.cause.resource),
                            )
                        )
            except simpy.Interrupt as ir:
                assert isinstance(ir.cause, Preempted)  # noqa: PT017
                log.append(
                    (
                        env.now,
                        id,
                        (ir.cause.by, ir.cause.usage_since, ir.cause.resource),
                    )
                )

    res0 = simpy.PreemptiveResource(env, 1)
    res1 = simpy.PreemptiveResource(env, 1)

    env.process(process2(0, env, res0, res1, 0, -1, True, log))
    p1 = env.process(process(1, env, res1, 1, -2, True, log))

    env.process(process2(2, env, res0, res1, 20, -1, True, log))
    p3 = env.process(process(3, env, res0, 21, -2, True, log))

    env.process(process2(4, env, res0, res1, 21, -1, True, log))

    env.run()

    assert log == [
        (1, 0, (p1, 0, res1)),
        (6, 1),
        (21, 2, (p3, 20, res0)),
        (26, 3),
        (31, 4),
    ]


#
# Tests for Container
#


def test_container(env, log):
    """A *container* is a resource (of optionally limited capacity) where
    you can put in our take-out a discrete or continuous amount of
    things (e.g., a box of lump sugar or a can of milk).  The *put* and
    *get* operations block if the buffer is to full or to empty. If they
    return, the process knows that the *put* or *get* operation was
    successful.

    """

    def putter(env, buf, log):
        yield env.timeout(1)
        while True:
            yield buf.put(2)
            log.append(('p', env.now))
            yield env.timeout(1)

    def getter(env, buf, log):
        yield buf.get(1)
        log.append(('g', env.now))

        yield env.timeout(1)
        yield buf.get(1)
        log.append(('g', env.now))

    buf = simpy.Container(env, init=0, capacity=2)
    env.process(putter(env, buf, log))
    env.process(getter(env, buf, log))
    env.run(until=5)

    assert log == [('p', 1), ('g', 1), ('g', 2), ('p', 2)]


def test_container_get_queued(env):
    def proc(env, wait, container, what):
        yield env.timeout(wait)
        with getattr(container, what)(1) as req:
            yield req

    container = simpy.Container(env, 1)
    p0 = env.process(proc(env, 0, container, 'get'))
    env.process(proc(env, 1, container, 'put'))
    env.process(proc(env, 1, container, 'put'))
    p3 = env.process(proc(env, 1, container, 'put'))

    env.run(until=1)
    assert [ev.proc for ev in container.put_queue] == []
    assert [ev.proc for ev in container.get_queue] == [p0]

    env.run(until=2)
    assert [ev.proc for ev in container.put_queue] == [p3]
    assert [ev.proc for ev in container.get_queue] == []


def test_initial_container_capacity(env):
    container = simpy.Container(env)
    assert container.capacity == float('inf')


def test_container_get_put_bounds(env):
    container = simpy.Container(env)
    with pytest.raises(ValueError, match='amount.*must be > 0'):
        container.get(-13)
    with pytest.raises(ValueError, match='amount.*must be > 0'):
        container.put(-13)


@pytest.mark.parametrize(
    ('error', 'args'),
    [
        (None, [2, 1]),  # normal case
        (None, [1, 1]),  # init == capacity should be valid
        (None, [1, 0]),  # init == 0 should be valid
        (ValueError, [1, 2]),  # init > capacity
        (ValueError, [0]),  # capacity == 0
        (ValueError, [-1]),  # capacity < 0
        (ValueError, [1, -1]),  # init < 0
    ],
)
def test_container_init_capacity(env, error, args):
    args.insert(0, env)
    if error:
        pytest.raises(error, simpy.Container, *args)
    else:
        simpy.Container(*args)


#
# Tests fore Store
#


def test_store(env):
    """A store models the production and consumption of concrete python
    objects (in contrast to containers, where you only now if the *put*
    or *get* operations were successful but don't get concrete
    objects).

    """

    def putter(_, store, item):
        yield store.put(item)

    def getter(_, store, orig_item):
        item = yield store.get()
        assert item is orig_item

    store = simpy.Store(env, capacity=2)
    item = object()

    # NOTE: Does the start order matter? Need to test this.
    env.process(putter(env, store, item))
    env.process(getter(env, store, item))
    env.run()


@pytest.mark.parametrize(
    'store_type',
    [
        simpy.Store,
        simpy.FilterStore,
    ],
)
def test_initial_store_capacity(env, store_type):
    store = store_type(env)
    assert store.capacity == float('inf')


def test_store_capacity(env):
    with pytest.raises(ValueError, match='"capacity" must be > 0'):
        simpy.Store(env, 0)
    with pytest.raises(ValueError, match='"capacity" must be > 0'):
        simpy.Store(env, -1)

    capacity = 2
    store = simpy.Store(env, capacity)
    env.process(store.put(i) for i in range(capacity + 1))
    env.run()

    # Ensure store is filled to capacity
    assert len(store.items) == capacity


def test_store_cancel(env):
    store = simpy.Store(env, capacity=1)

    def acquire_implicit_cancel():
        with store.get():
            yield env.timeout(1)
            # implicit cancel() when exiting with-block

    env.process(acquire_implicit_cancel())
    env.run()


def test_priority_store_item_priority(env):
    pstore = simpy.PriorityStore(env, 3)
    log = []

    def getter(wait):
        yield env.timeout(wait)
        item = yield pstore.get()
        log.append(item)

    # Do not specify priority; the items themselves will be compared to
    # determine priority.
    env.process(pstore.put(s) for s in 'bcadefg')
    env.process(getter(1))
    env.process(getter(2))
    env.process(getter(3))
    env.run()
    assert log == ['a', 'b', 'c']


def test_priority_store_stable_order(env):
    pstore = simpy.PriorityStore(env, 3)
    log = []

    def getter(wait):
        yield env.timeout(wait)
        _, item = yield pstore.get()
        log.append(item)

    items = [object() for _ in range(3)]

    # Unorderable items are inserted with same priority.
    env.process(pstore.put(simpy.PriorityItem(0, item)) for item in items)
    env.process(getter(1))
    env.process(getter(2))
    env.process(getter(3))
    env.run()

    # Since the priorities were the same for all items, ensure that items are
    # retrieved in insertion order.
    assert log == items


def test_filter_store(env):
    def pem(env):
        store = simpy.FilterStore(env, capacity=2)

        get_event = store.get(lambda item: item == 'b')
        yield store.put('a')
        assert not get_event.triggered
        yield store.put('b')
        assert get_event.triggered

    env.process(pem(env))
    env.run()


def test_filter_store_get_after_mismatch(env):
    """Regression test for issue #49.

    Triggering get-events after a put in FilterStore wrongly breaks after the
    first mismatch.

    """

    def putter(env, store):
        # The order of putting 'spam' before 'eggs' is important here.
        yield store.put('spam')
        yield env.timeout(1)
        yield store.put('eggs')

    def getter(store):
        # The order of requesting 'eggs' before 'spam' is important here.
        eggs = store.get(lambda i: i == 'eggs')
        spam = store.get(lambda i: i == 'spam')

        ret = yield spam | eggs
        assert spam in ret
        assert eggs not in ret
        assert env.now == 0

        yield eggs
        assert env.now == 1

    store = simpy.FilterStore(env, capacity=2)
    env.process(getter(store))
    env.process(putter(env, store))
    env.run()


def test_filter_calls_best_case(env):
    """The filter function is called every item in the store until a match is
    found. In the best case the first item already matches."""
    log = []

    def log_filter(item):
        log.append(f'check {item}')
        return True

    store = simpy.FilterStore(env)
    store.items = [1, 2, 3]

    def getter(store):
        log.append(f'get {yield store.get(log_filter)}')
        log.append(f'get {yield store.get(log_filter)}')
        log.append(f'get {yield store.get(log_filter)}')

    env.process(getter(store))
    env.run()

    assert log == ['check 1', 'get 1', 'check 2', 'get 2', 'check 3', 'get 3']


def test_filter_calls_worst_case(env):
    """In the worst case the filter function is being called for items multiple
    times."""

    log = []
    store = simpy.FilterStore(env)

    def putter(store):
        for i in range(4):
            log.append(f'put {i}')
            yield store.put(i)

    def log_filter(item):
        log.append(f'check {item}')
        return item >= 3

    def getter(store):
        log.append(f'get {yield store.get(log_filter)}')

    env.process(getter(store))
    env.process(putter(store))
    env.run()

    # The filter function is repeatedly called for every item in the store
    # until a match is found.
    # fmt: off
    assert log == [
        'put 0', 'check 0',
        'put 1', 'check 0', 'check 1',
        'put 2', 'check 0', 'check 1', 'check 2',
        'put 3', 'check 0', 'check 1', 'check 2', 'check 3', 'get 3',
    ]
    # fmt: on


def test_immediate_put_request(env):
    """Put requests that can be fulfilled immediately do not enter the put
    queue."""
    resource = simpy.Resource(env, capacity=1)
    assert len(resource.users) == 0
    assert len(resource.queue) == 0

    # The resource is empty, the first request will succeed immediately without
    # entering the queue.
    request = resource.request()
    assert request.triggered
    assert len(resource.users) == 1
    assert len(resource.queue) == 0

    # A second request will get enqueued however.
    request = resource.request()
    assert not request.triggered
    assert len(resource.users) == 1
    assert len(resource.queue) == 1


def test_immediate_get_request(env):
    """Get requests that can be fulfilled immediately do not enter the get
    queue."""
    container = simpy.Container(env)
    # Put something in the container, this request is triggered immediately
    # without entering the queue.
    request = container.put(1)
    assert request.triggered
    assert container.level == 1
    assert len(container.put_queue) == 0

    # The first get request will succeed immediately without entering the
    # queue.
    request = container.get(1)
    assert request.triggered
    assert container.level == 0
    assert len(container.get_queue) == 0

    # A second get request will get enqueued.
    request = container.get(1)
    assert not request.triggered
    assert len(container.get_queue) == 1
