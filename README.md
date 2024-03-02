# ⏰ SleepFake

[![Version](https://img.shields.io/pypi/v/sleepfake?style=for-the-badge)](<https://pypi.python.org/pypi/sleepfake>)
[![versions](https://img.shields.io/pypi/pyversions/sleepfake.svg?style=for-the-badge)](https://github.com/Guiforge/sleepfake)
[![license](https://img.shields.io/github/license/Guiforge/sleepfake.svg?style=for-the-badge)](https://github.com/Guiforge/sleepfake/blob/main/LICENSE)

`SleepFake` is a compact Python package (under 100 lines) that provides a context manager to simulate the `time.sleep` and `asyncio.sleep` functions during tests. This is useful for testing time-dependent code without the need to actually wait for time to pass. The real magic behind this package comes from [freezegun](https://github.com/spulec/freezegun). 🎩✨

## Installation

```bash
pip install sleepfake
```

## 🚀 Usage

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

## Local Development

### Prerequisites

Install [rye](https://rye-up.com/)

```bash
curl -sSf https://rye-up.com/get | bash
```

### Install dep

```bash
rye sync
```

### Run tests

```bash
rye run test
```

### Run linter

```bash
rye run lint
```

## Acknowledgments 🙏

- [freezegun](https://github.com/spulec/freezegun)
