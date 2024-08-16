import asyncio
import sys

import pytest

from sleepfake import SleepFake

SLEEP_DURATION = 5


@pytest.mark.asyncio
async def test_async_sleepfake():
    real_start_time = asyncio.get_event_loop().time()
    with SleepFake():
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_event_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_event_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async__aenter_sleepfake():
    real_start_time = asyncio.get_event_loop().time()
    async with SleepFake():
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_event_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_event_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake_gather():
    real_start_time = asyncio.get_event_loop().time()
    with SleepFake():
        start_time = asyncio.get_event_loop().time()
        await asyncio.gather(
            asyncio.sleep(SLEEP_DURATION),
            asyncio.sleep(SLEEP_DURATION),
            asyncio.sleep(SLEEP_DURATION),
        )
        end_time = asyncio.get_event_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_event_loop().time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake_task():
    if sys.version_info < (3, 11):
        pytest.skip("This test requires Python 3.11 or later, TaskGroup")

    real_start_time = asyncio.get_event_loop().time()
    with SleepFake():
        start_time = asyncio.get_event_loop().time()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
            tg.create_task(asyncio.sleep(SLEEP_DURATION))
        end_time = asyncio.get_event_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.5
    real_end_time = asyncio.get_event_loop().time()
    assert real_end_time - real_start_time < 1
