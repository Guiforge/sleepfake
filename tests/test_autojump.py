"""Autojump: loop timers (wait_for, asyncio.timeout, call_later) advance the fake clock."""

import asyncio
import datetime
import math
import threading

import pytest

from sleepfake import SleepFake


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _elapsed(t0: datetime.datetime) -> float:
    return (_now() - t0).total_seconds()


async def test_wait_for_without_any_sleep_times_out() -> None:
    """A timeout on something that never completes fires instead of hanging."""
    async with SleepFake():
        t0 = _now()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.Event().wait(), timeout=3)
        assert _elapsed(t0) == pytest.approx(3, abs=1e-5)


async def test_fixture_wait_for_without_any_sleep_times_out(sleepfake: SleepFake) -> None:
    """Also through the fixture, entered before the test's event loop even exists."""
    t0 = _now()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.Event().wait(), timeout=30)
    assert _elapsed(t0) == pytest.approx(30, abs=1e-5)
    assert sleepfake.autojump_threshold > 0


async def test_wait_for_ends_at_the_timeout_not_the_sleep_deadline() -> None:
    """``wait_for(sleep(10), 5)`` leaves the clock at 5 s, as with real asyncio."""
    async with SleepFake():
        t0 = _now()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.sleep(10), timeout=5)
        assert _elapsed(t0) == pytest.approx(5, abs=1e-5)


async def test_call_later_fires() -> None:
    """``loop.call_later`` callbacks run once the loop is idle."""
    loop = asyncio.get_running_loop()
    async with SleepFake():
        t0 = _now()
        fired: asyncio.Future[float] = loop.create_future()
        loop.call_later(10, lambda: fired.set_result(_elapsed(t0)))
        assert await fired == pytest.approx(10, abs=1e-5)


async def test_zero_threshold_jumps_immediately() -> None:
    """With ``autojump_threshold=0`` the clock jumps as soon as the loop is idle."""
    async with SleepFake(autojump_threshold=0):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.Event().wait(), timeout=3600)


async def test_real_io_answering_within_threshold_beats_the_timeout() -> None:
    """Work finishing in real time before the threshold is not cut short by a timeout."""
    loop = asyncio.get_running_loop()
    async with SleepFake(autojump_threshold=5):
        done: asyncio.Future[str] = loop.create_future()
        # Stands in for real I/O: completes from another thread after ~10 ms real time.
        threading.Timer(0.01, loop.call_soon_threadsafe, (done.set_result, "answer")).start()
        assert await asyncio.wait_for(done, timeout=1) == "answer"


async def test_infinite_threshold_leaves_timers_to_sleeps() -> None:
    """With ``inf``, loop timers only fire when sleeps move the clock past them."""
    loop = asyncio.get_running_loop()
    async with SleepFake(autojump_threshold=math.inf):
        t0 = _now()
        fired: list[float] = []
        loop.call_later(1, lambda: fired.append(_elapsed(t0)))
        await asyncio.sleep(5)
        assert _elapsed(t0) == 5
    assert fired == [5]


async def test_earlier_timer_scheduled_while_armed_takes_over() -> None:
    """A timer added during the idle wait for another one is honoured first."""
    loop = asyncio.get_running_loop()
    async with SleepFake(autojump_threshold=0.05):
        t0 = _now()
        order: list[str] = []
        loop.call_later(10, order.append, "late")
        # Let the driver arm the 10 s timer, then add an earlier one.
        await asyncio.wait_for(loop.run_in_executor(None, threading.Event().wait, 0.01), 60)
        early: asyncio.Future[None] = loop.create_future()
        loop.call_later(2, lambda: (order.append("early"), early.set_result(None)))
        await early
        assert order == ["early"]
        assert _elapsed(t0) == pytest.approx(2, abs=1e-5)


async def test_nested_contexts_advance_the_clock_once() -> None:
    """Only the innermost context drives timers, so a timeout is not applied twice."""
    async with SleepFake(), SleepFake():
        t0 = _now()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.Event().wait(), timeout=3)
        assert _elapsed(t0) == pytest.approx(3, abs=1e-5)


@pytest.mark.parametrize("threshold", [-1, math.nan])
def test_invalid_threshold_is_rejected(threshold: float) -> None:
    with pytest.raises(ValueError, match="autojump_threshold"):
        SleepFake(autojump_threshold=threshold)


def test_ini_threshold_is_used_by_the_fixture(pytester: pytest.Pytester) -> None:
    """``sleepfake_autojump_threshold`` configures the fixture's instance."""
    pytester.makeini("""
        [pytest]
        asyncio_mode = auto
        sleepfake_autojump_threshold = 0.5
    """)
    pytester.makepyfile("""
        def test_it(sleepfake):
            assert sleepfake.autojump_threshold == 0.5
    """)
    pytester.runpytest_subprocess().assert_outcomes(passed=1)


@pytest.mark.parametrize("value", ["soon", "-1"])
def test_invalid_ini_threshold_is_a_usage_error(pytester: pytest.Pytester, value: str) -> None:
    pytester.makeini(f"""
        [pytest]
        sleepfake_autojump_threshold = {value}
    """)
    pytester.makepyfile("""
        def test_it(sleepfake):
            pass
    """)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*sleepfake_autojump_threshold*"
            if value == "soon"
            else "*autojump_threshold must be >= 0*"
        ]
    )
