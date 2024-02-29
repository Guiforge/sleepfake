# SleepFake

`SleepFake` is a Python class that provides a context manager to fake the `time.sleep` and `asyncio.sleep` functions during tests. This is useful for testing time-dependent code without having to actually wait for time to pass.
Simple package, the most import magic comes from [freezegun](https://github.com/spulec/freezegun).

## Usage

```python
import asyncio
import time

from sleepfake import SleepFake


def test_example():
    real_start = time.time()
    with SleepFake():
        start = time.time()
        time.sleep(10)
        end = time.time()
        assert end - start == 10
    real_end = time.time()
    assert real_end - real_start < 1


async def test_async_example():
    real_start = asyncio.get_event_loop().time()
    with SleepFake():
        start = asyncio.get_event_loop().time()
        await asyncio.gather(asyncio.sleep(5), asyncio.sleep(5), asyncio.sleep(5))
        end = asyncio.get_event_loop().time()
        assert end - start <= 5.5  # almost 5 seconds  # noqa: PLR2004
        assert end - start >= 5  # almost 5 seconds  # noqa: PLR2004
    real_end = asyncio.get_event_loop().time()
    assert real_end - real_start < 1  # almost 0 seconds
```
