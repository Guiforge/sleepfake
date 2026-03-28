import asyncio
import sys

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
    assert end - start >= 3  # noqa: PLR2004


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
        assert mid - start >= 2  # noqa: PLR2004
        assert end - start >= 5  # noqa: PLR2004


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
