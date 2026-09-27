import asyncio
import datetime
import gc
import logging
import sys
import types

import pytest

from sleepfake import SleepFake

SLEEP_DURATION = 5


@pytest.mark.asyncio
async def test_async_sleepfake():
    real_start_time = asyncio.get_running_loop().time()
    with SleepFake():
        start_time = asyncio.get_running_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async__aenter_sleepfake():
    real_start_time = asyncio.get_running_loop().time()
    async with SleepFake():
        start_time = asyncio.get_running_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake_gather():
    real_start_time = asyncio.get_running_loop().time()
    with SleepFake():
        start_time = asyncio.get_running_loop().time()
        await asyncio.gather(
            asyncio.sleep(SLEEP_DURATION),
            asyncio.sleep(SLEEP_DURATION),
            asyncio.sleep(SLEEP_DURATION),
        )
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake_task():
    if sys.version_info < (3, 11):
        pytest.skip("This test requires Python 3.11 or later, TaskGroup")

    real_start_time = asyncio.get_running_loop().time()
    with SleepFake():
        start_time = asyncio.get_running_loop().time()
        async with asyncio.TaskGroup() as tg:  # type: ignore[attr-defined]
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


# ---------------------------------------------------------------------------
# Bug 2: PriorityQueue — mixed-duration gather wakes in deadline order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_gather_mixed_durations_wake_order():
    """Shorter sleeps should complete before longer sleeps."""
    order: list[int] = []

    async def tagged_sleep(duration: float, tag: int) -> None:
        await asyncio.sleep(duration)
        order.append(tag)

    with SleepFake():
        await asyncio.gather(
            tagged_sleep(10, 10),
            tagged_sleep(1, 1),
            tagged_sleep(5, 5),
            tagged_sleep(3, 3),
        )

    assert order == [1, 3, 5, 10]


@pytest.mark.asyncio
async def test_async_gather_mixed_durations_time_advances_correctly():
    """Frozen clock must advance to the longest deadline (max) when gathering mixed durations."""
    with SleepFake():
        start = asyncio.get_running_loop().time()
        await asyncio.gather(
            asyncio.sleep(1),
            asyncio.sleep(3),
            asyncio.sleep(2),
        )
        end = asyncio.get_running_loop().time()
    # longest is 3 seconds; real wall-clock must be < 1 s
    assert end - start >= 3


# ---------------------------------------------------------------------------
# asyncio.timeout integration (Python 3.11+)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_timeout_raises_when_sleep_exceeds_deadline():
    """asyncio.timeout should fire even when SleepFake is active."""
    if sys.version_info < (3, 11):
        pytest.skip("asyncio.timeout requires Python 3.11+")

    timed_out = False
    with SleepFake():
        try:
            async with asyncio.timeout(2):  # type: ignore[attr-defined]
                await asyncio.sleep(10)
        except TimeoutError:
            timed_out = True
    assert timed_out


@pytest.mark.asyncio
async def test_async_timeout_not_raised_when_sleep_within_deadline():
    """No TimeoutError when sleep finishes before the asyncio.timeout deadline."""
    if sys.version_info < (3, 11):
        pytest.skip("asyncio.timeout requires Python 3.11+")

    with SleepFake():
        async with asyncio.timeout(10):  # type: ignore[attr-defined]
            await asyncio.sleep(2)  # completes well within the 10 s deadline


# ---------------------------------------------------------------------------
# Bug 1: cancelled future must not crash process_sleeps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_cancelled_future_does_not_crash():
    """If a task is cancelled while waiting on amock_sleep, process_sleeps must survive."""
    results: list[str] = []

    async def short_sleep() -> None:
        await asyncio.sleep(1)
        results.append("short")

    async def long_sleep() -> None:
        try:
            await asyncio.sleep(100)
            results.append("long")
        except asyncio.CancelledError:
            results.append("cancelled")
            raise

    with SleepFake():
        long_task = asyncio.create_task(long_sleep())
        await asyncio.sleep(0)  # let tasks start
        long_task.cancel()
        await asyncio.gather(long_task, return_exceptions=True)
        # After cancellation, short_sleep must still work
        await short_sleep()

    assert "short" in results
    assert "cancelled" in results


# ---------------------------------------------------------------------------
# Bug 3: timezone safety — naive UTC deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_sleep_deadline_is_naive_utc():
    """amock_sleep must compute deadlines in naive UTC, not local time."""
    with SleepFake() as sf:
        # Directly call amock_sleep and capture what was enqueued
        await asyncio.sleep(10)
        # frozen time should have advanced by exactly 10 s from the start
        assert sf.frozen_factory is not None
        frozen_now = sf.frozen_factory.time_to_freeze  # type: ignore[attr-defined]
        # frozen_now is naive UTC; it should be a datetime without tzinfo
        assert frozen_now.tzinfo is None


# ---------------------------------------------------------------------------
# Bug 5: freeze_time lifecycle — starts at __enter__, stops at __exit__
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_freeze_not_started_before_aenter():
    """freeze_time must NOT be active before the context is entered."""
    sf = SleepFake()
    assert not sf._freeze_started  # noqa: SLF001
    async with sf:
        assert sf._freeze_started  # noqa: SLF001
    assert not sf._freeze_started  # noqa: SLF001


# ---------------------------------------------------------------------------
# aclose: processor task cleaned up after async with
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_cleanup_after_aenter():
    """After async with, sleep_processor and sleep_queue should be None."""
    async with SleepFake() as sf:
        await asyncio.sleep(1)
    assert sf.sleep_processor is None
    assert sf.sleep_queue is None
    assert not sf._freeze_started  # noqa: SLF001


# ---------------------------------------------------------------------------
# Zero-duration async sleep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_zero_sleep():
    """asyncio.sleep(0) should complete without error."""
    with SleepFake():
        await asyncio.sleep(0)
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Sequential async sleeps accumulate correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_sequential_sleeps_accumulate():
    """Sequential asyncio.sleep calls should each advance the frozen clock."""
    with SleepFake():
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(2)
        mid = asyncio.get_running_loop().time()
        await asyncio.sleep(3)
        end = asyncio.get_running_loop().time()
        assert mid - start >= 2
        assert end - start >= 5


# ---------------------------------------------------------------------------
# Reentrant: multiple sequential uses of SleepFake do not interfere
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_reentrant_context():
    for _ in range(3):
        real_start = asyncio.get_running_loop().time()
        with SleepFake():
            await asyncio.sleep(SLEEP_DURATION)
        assert asyncio.get_running_loop().time() - real_start < 1


# ---------------------------------------------------------------------------
# Equal-duration concurrent sleeps (FIFO tie-breaking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_gather_equal_durations():
    """Equal-duration sleeps must all complete (tie-breaking by seq number)."""
    results: list[int] = []

    async def tagged(tag: int) -> None:
        await asyncio.sleep(SLEEP_DURATION)
        results.append(tag)

    with SleepFake():
        await asyncio.gather(tagged(1), tagged(2), tagged(3))

    assert sorted(results) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Fixture-based async tests (sync fixture in async test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_async_sleep(sleepfake: SleepFake) -> None:  # noqa: ARG001
    """The sync ``sleepfake`` fixture works inside an async test."""
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(SLEEP_DURATION)
    end = asyncio.get_running_loop().time()
    assert end - start >= SLEEP_DURATION


@pytest.mark.asyncio
async def test_fixture_async_gather(sleepfake: SleepFake) -> None:  # noqa: ARG001
    """Concurrent gathers work through the sync fixture."""
    start = asyncio.get_running_loop().time()
    await asyncio.gather(
        asyncio.sleep(SLEEP_DURATION),
        asyncio.sleep(SLEEP_DURATION),
    )
    end = asyncio.get_running_loop().time()
    assert SLEEP_DURATION <= end - start <= SLEEP_DURATION + 0.5


# ---------------------------------------------------------------------------
# sleepfake fixture in async tests (covers deprecated asleepfake use-cases)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_fixture_sleep(sleepfake: SleepFake) -> None:  # noqa: ARG001
    """The ``sleepfake`` fixture works for basic async sleep."""
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(SLEEP_DURATION)
    end = asyncio.get_running_loop().time()
    assert end - start >= SLEEP_DURATION


@pytest.mark.asyncio
async def test_async_fixture_gather(sleepfake: SleepFake) -> None:  # noqa: ARG001
    """Concurrent gathers work through the ``sleepfake`` fixture in an async test."""
    start = asyncio.get_running_loop().time()
    await asyncio.gather(
        asyncio.sleep(SLEEP_DURATION),
        asyncio.sleep(SLEEP_DURATION),
        asyncio.sleep(SLEEP_DURATION),
    )
    end = asyncio.get_running_loop().time()
    assert SLEEP_DURATION <= end - start <= SLEEP_DURATION + 0.5


@pytest.mark.asyncio
async def test_async_fixture_cleanup(sleepfake: SleepFake) -> None:
    """While the fixture is active the processor and queue are initialised."""
    await asyncio.sleep(1)
    # Lazy init on first amock_sleep — processor must be running now.
    assert sleepfake.sleep_processor is not None
    assert sleepfake.sleep_queue is not None


# ---------------------------------------------------------------------------
# Error-path coverage for core.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_amock_sleep_negative_behaves_like_zero() -> None:
    """Like the real asyncio.sleep, a negative delay returns immediately without raising."""
    async with SleepFake():
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.sleep(-1)
        assert loop.time() == start


@pytest.mark.asyncio
async def test_exit_drains_pending_queue_futures() -> None:
    """Sync __exit__ cancels futures still pending in the sleep queue."""
    import datetime as dt  # noqa: PLC0415

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[None] = loop.create_future()
    deadline = dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(seconds=100)

    with SleepFake() as sf:
        sf.sleep_queue = asyncio.PriorityQueue()
        sf.sleep_queue.put_nowait((deadline, 1, fut))

    assert fut.cancelled()


@pytest.mark.asyncio
async def test_process_sleeps_skips_cancelled_future() -> None:
    """process_sleeps gracefully skips futures that were cancelled after queuing."""
    import datetime as dt  # noqa: PLC0415

    async with SleepFake() as sf:
        await asyncio.sleep(0)  # trigger lazy init of queue + processor
        assert sf.sleep_queue is not None

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        deadline = dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None)
        sf._seq += 1  # noqa: SLF001
        sf.sleep_queue.put_nowait((deadline, sf._seq, fut))  # noqa: SLF001
        fut.cancel()

        # Yield so process_sleeps can dequeue and skip the cancelled future.
        tick: asyncio.Future[None] = loop.create_future()
        loop.call_soon(tick.set_result, None)
        await tick


@pytest.mark.asyncio
async def test_amock_sleep_not_initialized_raises() -> None:
    """amock_sleep raises _NotInitializedError when processor is set but queue is None."""
    from sleepfake.core import _NotInitializedError  # noqa: PLC0415

    async with SleepFake() as sf:
        await asyncio.sleep(0)  # init processor
        real_queue = sf.sleep_queue
        sf.sleep_queue = None  # corrupt state
        with pytest.raises(_NotInitializedError):
            await sf.amock_sleep(1)
        sf.sleep_queue = real_queue  # restore for clean aclose


@pytest.mark.asyncio
async def test_process_sleeps_raises_when_queue_is_none() -> None:
    """process_sleeps raises _NotInitializedError when sleep_queue is None."""
    from sleepfake.core import _NotInitializedError  # noqa: PLC0415

    sf = SleepFake()
    with pytest.raises(_NotInitializedError):
        await sf.process_sleeps()


# ---------------------------------------------------------------------------
# Broad patching — asyncio.sleep module-level aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broad_patch_asyncio_sleep_module_alias() -> None:
    """SleepFake patches module-level ``from asyncio import sleep`` aliases in sys.modules."""
    original_sleep = asyncio.sleep  # capture before any context is active
    fake_mod = types.ModuleType("_sleepfake_test_broad_async")
    fake_mod.__dict__["sleep"] = original_sleep  # simulates ``from asyncio import sleep``
    sys.modules["_sleepfake_test_broad_async"] = fake_mod
    try:
        with SleepFake():
            # The alias must have been replaced with a mock (not the original coroutine).
            assert fake_mod.sleep is not original_sleep  # type: ignore[attr-defined]
            start = asyncio.get_running_loop().time()
            await fake_mod.sleep(5)  # type: ignore[attr-defined]
            assert asyncio.get_running_loop().time() - start >= 5
        # After exit the alias is restored.
        assert fake_mod.sleep is original_sleep  # type: ignore[attr-defined]
    finally:
        sys.modules.pop("_sleepfake_test_broad_async", None)


@pytest.mark.asyncio
async def test_amock_sleep_returns_result() -> None:
    """``asyncio.sleep(delay, result)`` returns *result*, like the real function."""
    async with SleepFake():
        assert await asyncio.sleep(1, "done") == "done"
        assert await asyncio.sleep(1, result=42) == 42
        assert await asyncio.sleep(1) is None


@pytest.mark.asyncio
async def test_exit_cancels_in_flight_future() -> None:
    """A sleep already dequeued by the processor is cancelled on exit, not leaked forever."""
    loop = asyncio.get_running_loop()

    async def real_yield() -> None:
        fut: asyncio.Future[None] = loop.create_future()
        loop.call_soon(fut.set_result, None)
        await fut

    sf = SleepFake()
    sf.__enter__()
    task = asyncio.create_task(asyncio.sleep(5))
    for _ in range(10):
        await real_yield()
        if sf.sleep_queue is not None and sf.sleep_queue.empty():
            break
    # The processor has dequeued the sleep and is mid-tick; exit now.
    assert not task.done()
    sf.__exit__(None, None, None)
    for _ in range(5):
        await real_yield()
    assert task.done()
    assert task.cancelled() or task.exception() is None


@pytest.mark.filterwarnings("ignore:The 'asleepfake' fixture is deprecated:DeprecationWarning")
async def test_deprecated_asleepfake_fixture_still_works(asleepfake: SleepFake) -> None:
    """The deprecated ``asleepfake`` fixture keeps working until it is removed."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.sleep(10)
    assert loop.time() - start == 10
    assert asleepfake.sleep_processor is not None


def test_asleepfake_fixture_emits_deprecation_warning(pytester: pytest.Pytester) -> None:
    """Requesting ``asleepfake`` emits a DeprecationWarning pointing to ``sleepfake``."""
    pytester.makepyfile("""
        import pytest

        @pytest.mark.asyncio
        async def test_uses_deprecated(asleepfake):
            pass
    """)
    result = pytester.runpytest_subprocess("-W", "error::DeprecationWarning")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*asleepfake*deprecated*"])


def _elapsed(t0: datetime.datetime) -> float:
    return (datetime.datetime.now(tz=datetime.timezone.utc) - t0).total_seconds()


async def test_woken_task_sleeps_again_before_clock_advances() -> None:
    """A task woken by the processor re-sleeps before the clock jumps to the next deadline."""
    seen: list[float] = []
    async with SleepFake():
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)

        async def heartbeat() -> None:
            for _ in range(3):
                await asyncio.sleep(1)
                seen.append(_elapsed(t0))

        await asyncio.gather(heartbeat(), asyncio.sleep(100))
    assert seen == [1, 2, 3]


async def test_periodic_task_is_not_starved() -> None:
    """A 1 s ticker runs 4 times during a 5 s sleep, as with real asyncio."""
    ticks: list[int] = []
    async with SleepFake():

        async def ticker() -> None:
            for _ in range(10):
                await asyncio.sleep(1)
                ticks.append(1)

        task = asyncio.create_task(ticker())
        await asyncio.sleep(5)
        task.cancel()
    assert len(ticks) == 4


async def test_sleep_zero_does_not_advance_to_pending_deadline() -> None:
    """``sleep(0)`` with a longer sleep pending must not jump the clock."""
    async with SleepFake():
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)
        background = asyncio.create_task(asyncio.sleep(60))
        await asyncio.sleep(0)
        assert _elapsed(t0) == 0
        background.cancel()


async def test_sleep_infinity_waits_until_cancelled() -> None:
    """``asyncio.sleep(inf)`` pends until cancelled instead of raising OverflowError."""
    async with SleepFake():
        task = asyncio.create_task(asyncio.sleep(float("inf")))
        await asyncio.sleep(1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_asyncio_run_twice_in_one_sync_context() -> None:
    """A sync context survives several event loops (e.g. ``asyncio.run`` twice)."""

    async def main() -> float:
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)
        await asyncio.sleep(1)
        return _elapsed(t0)

    with SleepFake():
        assert asyncio.run(main()) == 1
        assert asyncio.run(main()) == 1


# Closing a loop with a pending task makes asyncio report it when it is garbage-collected.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_exit_after_event_loop_closed(caplog: pytest.LogCaptureFixture) -> None:
    """Exiting after the loop that ran async sleeps was closed does not raise."""
    loop = asyncio.new_event_loop()
    with SleepFake():
        # One of these is held by the processor, the other is still queued at exit.
        pending = [loop.create_task(asyncio.sleep(10)), loop.create_task(asyncio.sleep(20))]
        loop.run_until_complete(asyncio.sleep(1))
        loop.close()
    assert not any(task.done() for task in pending)
    del pending, loop
    with caplog.at_level(logging.CRITICAL, logger="asyncio"):
        gc.collect()  # collect the orphaned processor here, not during a later test


async def test_cancelled_sleeper_left_in_queue_is_skipped() -> None:
    """A cancelled sleep still queued is skipped and does not stop the clock at its deadline."""
    async with SleepFake():
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)
        task = asyncio.create_task(asyncio.sleep(10))
        await asyncio.sleep(1)
        task.cancel()
        await asyncio.sleep(20)
        assert _elapsed(t0) == 21


async def test_deadline_already_passed_does_not_move_clock_back() -> None:
    """A sync ``time.sleep`` that overshoots a queued deadline never rewinds the clock."""
    async with SleepFake() as sf:
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)
        task = asyncio.create_task(asyncio.sleep(5))
        await asyncio.sleep(0)
        sf.mock_sleep(10)  # what a sync ``time.sleep`` does
        await task
        assert _elapsed(t0) == 10


async def test_sleep_after_timeout_keeps_working() -> None:
    """After a timeout cancels a sleep, later sleeps are still processed."""
    async with SleepFake():
        t0 = datetime.datetime.now(tz=datetime.timezone.utc)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.sleep(10), timeout=2)
        await asyncio.sleep(1)
        assert _elapsed(t0) == 11


async def test_busy_task_does_not_stall_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task that never stops scheduling callbacks cannot block sleeps forever."""
    monkeypatch.setattr("sleepfake.core._MAX_IDLE_YIELDS", 5)
    loop = asyncio.get_running_loop()
    stop = False

    def spin() -> None:
        if not stop:
            loop.call_soon(spin)

    async with SleepFake():
        loop.call_soon(spin)
        await asyncio.sleep(1)
        stop = True


async def test_aclose_twice_is_a_no_op() -> None:
    """``aclose`` can be called again after the context already exited."""
    sf = SleepFake()
    async with sf:
        await asyncio.sleep(1)
    await sf.aclose()
    assert sf.sleep_processor is None
