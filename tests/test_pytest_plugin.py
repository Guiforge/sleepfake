import time

import pytest


def test_pytest_plugin(pytester: pytest.Pytester) -> None:
    """Make sure that our plugin works."""
    # create a temporary pytest test file
    pytester.makepyfile(
        """
        import pytest
        import time
        import asyncio

        from sleepfake import SleepFake

        SLEEP_DURATION = 12

        def test_sync_sleepfake(sleepfake):
            start_time = time.time()
            time.sleep(SLEEP_DURATION)
            end_time = time.time()
            assert end_time - start_time >= SLEEP_DURATION

        @pytest.mark.asyncio
        async def test_async_sleepfake(sleepfake):
            start_time = asyncio.get_event_loop().time()
            await asyncio.sleep(SLEEP_DURATION)
            end_time = asyncio.get_event_loop().time()
            assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5

        @pytest.mark.asyncio
        async def test_async_sleepfake_gather(sleepfake):
            start_time = asyncio.get_event_loop().time()
            await asyncio.gather(
                asyncio.sleep(SLEEP_DURATION),
                asyncio.sleep(SLEEP_DURATION),
                asyncio.sleep(SLEEP_DURATION)
                )
            end_time = asyncio.get_event_loop().time()
            assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    """
    )

    real_start_time = time.time()

    result = pytester.runpytest()

    real_end_time = time.time()
    assert real_end_time - real_start_time < 1

    result.assert_outcomes(passed=3)
