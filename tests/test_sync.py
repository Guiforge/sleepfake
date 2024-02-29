import asyncio
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


@pytest.mark.asyncio()
async def test_async_sleepfake():
    real_start_time = asyncio.get_event_loop().time()
    with SleepFake():
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_event_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.2
    real_end_time = asyncio.get_event_loop().time()
    assert real_end_time - real_start_time < 1
