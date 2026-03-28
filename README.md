<!-- Shield Badges -->
<p align="center">
  <img src="./logo.svg" alt="SleepFake Logo" width="120"/>
</p>
<p align="center">
  <a href="https://pypi.org/project/sleepfake/"><img src="https://img.shields.io/pypi/v/sleepfake.svg?color=blue" alt="PyPI version"></a>
  <a href="https://github.com/spulec/freezegun"><img src="https://img.shields.io/badge/dependency-freezegun-blue" alt="freezegun"></a>
  <img src="https://img.shields.io/badge/pytest%20plugin-stable-green" alt="pytest plugin stable"/>
</p>

# 💤 SleepFake: Time Travel for Your Tests

Ever wish your tests could skip the wait? **SleepFake** patches `time.sleep` and `asyncio.sleep` so your tests run instantly—the frozen clock advances by the requested duration, so all your time-based assertions still hold.

## 🚀 Features

- Instantly skip over `sleep` calls in both sync and async code
- Works with `time.sleep` and `asyncio.sleep`
- Concurrent async sleeps wake in deadline order (priority queue)
- `asyncio.timeout` / `asyncio.TaskGroup` work correctly with frozen time
- Three ways to use: **context manager**, **pytest fixture**, or **marker**
- Compatible with pytest, pytest-asyncio, and pytest-timeout

## 📦 Installation

```bash
pip install sleepfake
```

## ✨ Usage

### As a context manager

```python
import time
import asyncio
from sleepfake import SleepFake

# Sync
with SleepFake():
    start = time.time()
    time.sleep(10)           # returns instantly
    assert time.time() - start >= 10

# Async — use async with for proper cleanup of the background processor
async def test_async():
    async with SleepFake():
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(5)   # returns instantly
        assert asyncio.get_running_loop().time() - start >= 5
```

### As a pytest fixture

Install once; the `sleepfake` and `asleepfake` fixtures are available in every test session automatically.

**`sleepfake`** (sync fixture):

```python
import time

def test_retry_logic(sleepfake):
    start = time.time()
    time.sleep(30)           # instantly skipped
    assert time.time() - start >= 30
```

**`asleepfake`** (async fixture — recommended for async tests; properly awaits the background processor task on teardown):

```python
import asyncio

async def test_polling(asleepfake):
    start = asyncio.get_running_loop().time()
    await asyncio.gather(
        asyncio.sleep(1),
        asyncio.sleep(5),
        asyncio.sleep(3),
    )
    # All three complete instantly; frozen clock sits at +5 s
    assert asyncio.get_running_loop().time() - start >= 5
```

### As a marker

Decorate individual tests with `@pytest.mark.sleepfake` — no fixture argument needed.
SleepFake is entered before the test body and exited after, automatically.

```python
import time
import asyncio
import pytest

@pytest.mark.sleepfake
def test_marked_sync():
    start = time.time()
    time.sleep(100)
    assert time.time() - start >= 100

@pytest.mark.sleepfake
async def test_marked_async():
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(100)
    assert asyncio.get_running_loop().time() - start >= 100
```

> If a test requests the `sleepfake` or `asleepfake` fixture *and* carries the marker, the marker is a no-op — double-patching is prevented automatically.

### Global autouse (every test, zero boilerplate)

**Option A — config file** (`pyproject.toml` or `pytest.ini`):

```toml
# pyproject.toml
[tool.pytest.ini_options]
sleepfake_autouse = true
```

**Option B — CLI flag** (useful for one-off runs or CI overrides):

```bash
pytest --sleepfake
```

Both activate SleepFake automatically for every test in the session:

```python
import time
import asyncio

def test_no_decoration_needed():
    start = time.time()
    time.sleep(100)          # patched automatically
    assert time.time() - start >= 100

async def test_async_no_decoration():
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(100)
    assert asyncio.get_running_loop().time() - start >= 100
```

Double-patching is prevented: if a test also requests the `sleepfake`/`asleepfake` fixture or carries `@pytest.mark.sleepfake`, the autouse layer is skipped for that test.

**Option C — conftest.py autouse fixtures** (if you need finer control per directory):

```python
# conftest.py
import pytest

@pytest.fixture(autouse=True)
def _sleepfake_sync(sleepfake):
    """Auto-apply SleepFake for every test (sync and async)."""

@pytest.fixture(autouse=True)
async def _sleepfake_async(sleepfake):
    """Async counterpart — shares the same sleepfake instance; no double-patch."""
```

Both fixtures reference the same `sleepfake` instance: sync tests get `_sleepfake_sync` only, async tests get both but share one `SleepFake` (no double-patch).

### `asyncio.timeout` integration

The frozen clock is advanced before resolving each sleep future, so `asyncio.timeout` fires correctly even when time is faked:

```python
import asyncio
import pytest
from sleepfake import SleepFake

async def test_timeout_fires():
    with SleepFake():
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(2):
                await asyncio.sleep(10)   # clock jumps to +10 s → timeout at +2 s fires
```

## ⚠️ Scope limitation

SleepFake patches `time.sleep` and `asyncio.sleep` by name via `unittest.mock.patch`.
Code that binds the function locally **before** the context is entered — e.g.
`from time import sleep` at module level — will bypass the mock.

## 🧪 How it works

| Aspect | Detail |
|---|---|
| **Sync sleep** | `frozen_factory.tick(delta)` — advances the freeze-gun clock immediately |
| **Async sleep** | `(deadline, seq, future)` pushed onto an `asyncio.PriorityQueue`; background task resolves futures in deadline order |
| **Timeout safety** | After advancing the clock, the processor yields one event-loop iteration so `asyncio.timeout` call-at callbacks can fire before futures are resolved |
| **Cancellation** | Cancelled futures are skipped; `process_sleeps` keeps running |
| **pytest durations** | `_pytest.timing.perf_counter` is restored after `freeze_time.start()` to prevent epoch-scale `--durations` output |

## 🤝 Contributing

PRs and issues welcome!

---

Made with ❤️ and a dash of impatience.

---

> **Note:** SleepFake uses [freezegun](https://github.com/spulec/freezegun) under the hood for time manipulation magic.
