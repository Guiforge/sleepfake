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

You can customize freezegun module ignores via `ignore`:

```python
from sleepfake import SleepFake

# `_pytest.timing` is always ignored by default to keep pytest durations sane.
# Add your own modules as needed.
with SleepFake(ignore=["my_project.telemetry"]):
    ...
```

### As a pytest fixture

Install once; the `sleepfake` fixture is available in every test session automatically.

**`sleepfake`** — works for both sync *and* async tests:

```python
import time

def test_retry_logic(sleepfake):
    start = time.time()
    time.sleep(30)           # instantly skipped
    assert time.time() - start >= 30
```

```python
import asyncio

async def test_polling(sleepfake):
    start = asyncio.get_running_loop().time()
    await asyncio.gather(
        asyncio.sleep(1),
        asyncio.sleep(5),
        asyncio.sleep(3),
    )
    # All three complete instantly; frozen clock sits at +5 s
    assert asyncio.get_running_loop().time() - start >= 5
```

> **Deprecated:** The `asleepfake` async fixture is deprecated. Use `sleepfake` instead — it initialises the async sleep-processor lazily on the first `asyncio.sleep` call and works identically in async tests.

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

> If a test requests the `sleepfake` fixture *and* carries the marker, the marker is a no-op — double-patching is prevented automatically.

### Global autouse (every test, zero boilerplate)

**Option A — config file** (`pyproject.toml` or `pytest.ini`):

```toml
# pyproject.toml
[tool.pytest.ini_options]
sleepfake_autouse = true
sleepfake_ignore = ["my_project.telemetry", "my_project.metrics"]
```

```ini
# pytest.ini
[pytest]
sleepfake_autouse = true
sleepfake_ignore =
    my_project.telemetry
    my_project.metrics
```

**Option B — CLI flag** (useful for one-off runs or CI overrides):

```bash
pytest --sleepfake
pytest --sleepfake --sleepfake-ignore my_project.telemetry --sleepfake-ignore my_project.metrics
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

Double-patching is prevented: if a test also requests the `sleepfake` fixture or carries `@pytest.mark.sleepfake`, the autouse layer is skipped for that test.

### Disabling autouse for specific tests

When autouse is on globally, mark individual tests with `@pytest.mark.no_sleepfake` to opt them out:

```python
import time
import pytest

# This test runs with SleepFake (autouse applies).
def test_patched():
    start = time.time()
    time.sleep(100)
    assert time.time() - start >= 100

# This test uses real time — SleepFake is NOT applied.
@pytest.mark.no_sleepfake
def test_needs_real_time():
    start = time.time()
    time.sleep(0.01)          # real sleep, returns fast
    assert time.time() - start < 5
```

`@pytest.mark.no_sleepfake` only affects the autouse layer. Tests that explicitly request the `sleepfake` fixture are unaffected (the fixture always patches).

### Configure ignores in `conftest.py`

If you want project- or directory-specific ignore rules without putting them in
`pyproject.toml`, define `pytest_sleepfake_ignore` in `conftest.py`:

```python
# conftest.py
pytest_sleepfake_ignore = ["my_project.telemetry", "my_project.metrics"]
```

This conftest setting is used by:

- the `sleepfake` fixture
- `@pytest.mark.sleepfake`
- global autouse mode (`sleepfake_autouse = true` or `--sleepfake`)

### Options reference (API, CLI, and config)

| Where | Option | Example | Purpose |
|---|---|---|---|
| Python API (`SleepFake`) | `ignore: list[str] \| None` | `SleepFake(ignore=["my.module"])` | Add module prefixes freezegun should ignore while freezing time. |
| Pytest CLI | `--sleepfake` | `pytest --sleepfake` | Enable SleepFake for every test in the session. |
| Pytest CLI | `--sleepfake-ignore MODULE` | `pytest --sleepfake-ignore my.module` | Add a module prefix to ignore (repeatable; merged with `sleepfake_ignore`). |
| Pytest config (`pytest.ini` / `pyproject.toml`) | `sleepfake_autouse = true` | `[tool.pytest.ini_options]\nsleepfake_autouse = true` | Same as `--sleepfake`, but persisted in config. |
| Pytest config (`pytest.ini` / `pyproject.toml`) | `sleepfake_ignore` | `sleepfake_ignore = ["my.module"]` | Add module prefixes to ignore for all pytest-managed SleepFake usage. |
| `conftest.py` | `pytest_sleepfake_ignore` | `pytest_sleepfake_ignore = ["my.module"]` | Override ignore prefixes for a test subtree (directory-scoped). |

Notes:

- Every ignore list is **merged** with `DEFAULT_IGNORE = ["_pytest.timing"]` — the built-in constant defined in `sleepfake.__init__`.
  **Why it exists:** `freezegun` patches every reachable module that calls `time.*` helpers, including `_pytest.timing.perf_counter`, which pytest uses to measure wall-clock test durations. Without this exclusion, `pytest --durations` reports absurd epoch-scale values (e.g. `1,704,067,200.00s`). By always ignoring `_pytest.timing`, real clocks stay intact for pytest's own instrumentation while all other `time.*` / `asyncio.sleep` calls are still frozen.
- User-provided/configured ignore values are appended after `DEFAULT_IGNORE` and deduplicated.

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
| **pytest durations** | `freeze_time(..., ignore=["_pytest.timing", ...])` keeps pytest timing internals on real clocks to prevent epoch-scale `--durations` output |

## 🤝 Contributing

PRs and issues welcome!

---

Made with ❤️ and a dash of impatience.

---

> **Note:** SleepFake uses [freezegun](https://github.com/spulec/freezegun) under the hood for time manipulation magic.
