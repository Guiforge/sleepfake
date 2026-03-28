import asyncio
import sys
import time

import pytest

from sleepfake import SleepFake

SLEEP_DURATION = 4


def test_sync_sleepfake():
    real_start_time = time.time()
    with SleepFake():
        start_time = time.time()
        time.sleep(SLEEP_DURATION)
        end_time = time.time()
        assert end_time - start_time >= SLEEP_DURATION
    real_end_time = time.time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake():
    real_start_time = asyncio.get_running_loop().time()
    with SleepFake():
        start_time = asyncio.get_running_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.2
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


def test_sync_multiple_sleeps_accumulate():
    """Multiple sequential time.sleep calls should each advance frozen time."""
    with SleepFake():
        t0 = time.time()
        time.sleep(2)
        t1 = time.time()
        time.sleep(3)
        t2 = time.time()
        assert t1 - t0 >= 2  # noqa: PLR2004
        assert t2 - t0 >= 5  # noqa: PLR2004


def test_sync_freeze_not_started_before_enter():
    """Bug 5: freeze_time must NOT start before __enter__ is called."""
    sf = SleepFake()
    # Before entering the context, frozen_factory should not be active.
    assert not sf._freeze_started  # noqa: SLF001
    with sf:
        assert sf._freeze_started  # noqa: SLF001
    assert not sf._freeze_started  # noqa: SLF001


def test_sync_context_restores_time_sleep():
    """time.sleep should be restored to the real function after exiting."""
    original = time.sleep
    with SleepFake():
        assert time.sleep is not original
    assert time.sleep is original


def test_sync_zero_sleep():
    """time.sleep(0) should be a no-op and not raise."""
    with SleepFake():
        start = time.time()
        time.sleep(0)
        end = time.time()
    assert end - start < 1


def test_sync_reentrant_context():
    """SleepFake can be used multiple times sequentially without state leakage."""
    for _ in range(3):
        real_start = time.time()
        with SleepFake():
            time.sleep(SLEEP_DURATION)
        assert time.time() - real_start < 1


# ---------------------------------------------------------------------------
# asyncio.timeout integration inside a sync context manager (Python 3.11+)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_timeout_raises_when_sleep_exceeds_deadline():
    """asyncio.timeout should fire when SleepFake is entered via sync __enter__."""
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
async def test_sync_timeout_not_raised_when_sleep_within_deadline():
    """No TimeoutError when asyncio.sleep finishes before the asyncio.timeout deadline."""
    if sys.version_info < (3, 11):
        pytest.skip("asyncio.timeout requires Python 3.11+")

    with SleepFake():
        async with asyncio.timeout(10):  # type: ignore[attr-defined]
            await asyncio.sleep(2)  # completes well within the 10 s deadline
