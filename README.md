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

Ever wish your tests could skip the waiting but keep correct time behavior? **SleepFake** patches `time.sleep` and `asyncio.sleep` so tests return instantly while frozen time moves forward exactly as requested.

## 🚀 Why teams adopt SleepFake fast

- **Zero waiting** in sync and async tests
- **Minimal setup** (one install + one config toggle)
- **Realistic behavior** for timeouts, task groups, and ordering

## 📦 Install (30 seconds)

```bash
pip install sleepfake
```

## ⚡ Quick start (recommended): global autouse

If you want instant wins with almost no boilerplate, make SleepFake apply to **every test**.

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
sleepfake_autouse = true
```

Now regular tests automatically skip sleeps:

```python
import time

def test_retry():
    start = time.time()
    time.sleep(30)  # returns instantly
    assert time.time() - start >= 30
```

Async works the same way:

```python
import asyncio

async def test_polling():
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(10)  # returns instantly
    assert asyncio.get_running_loop().time() - start >= 10
```

✅ **Result:** your suite keeps time-based correctness, minus the wall-clock pain.

## 🧭 Choose your usage style

| Use case | Best option | Boilerplate |
|---|---|---|
| Apply everywhere (most teams) | Global autouse (`sleepfake_autouse = true` or `--sleepfake`) | Lowest |
| Per-test explicit control | `sleepfake` fixture | Low |
| Decoration-style usage | `@pytest.mark.sleepfake` | Low |
| Non-pytest scripts / direct control | `SleepFake` context manager | Medium |

## 📚 Full details (expand as needed)

<details>
<summary><strong>Context manager usage</strong></summary>

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

Customize freezegun ignores via `ignore`:

```python
from sleepfake import SleepFake

# `_pytest.timing` is always ignored by default to keep pytest durations sane.
# Add your own modules as needed.
with SleepFake(ignore=["my_project.telemetry"]):
    ...
```

</details>

<details>
<summary><strong>Fixture usage (`sleepfake`)</strong></summary>

Install once; the `sleepfake` fixture is available automatically in tests.

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

> **Deprecated:** `asleepfake` is deprecated. Use `sleepfake` for both sync and async tests.

</details>

<details>
<summary><strong>Marker usage (`@pytest.mark.sleepfake`)</strong></summary>

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

If a test already requests the `sleepfake` fixture, this marker becomes a no-op (no double patching).

</details>

<details>
<summary><strong>Global autouse: all options and opt-out</strong></summary>

### Option A — config file (`pyproject.toml` / `pytest.ini`)

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

### Option B — CLI flag

```bash
pytest --sleepfake
pytest --sleepfake --sleepfake-ignore my_project.telemetry --sleepfake-ignore my_project.metrics
```

### Disable autouse per-test

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
    time.sleep(0.01)
    assert time.time() - start < 5
```

`@pytest.mark.no_sleepfake` only disables the autouse layer.
If your test explicitly requests `sleepfake`, it still patches.

### Option C — per-directory autouse in `conftest.py`

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

Both fixtures share one `sleepfake` instance.

</details>

<details>
<summary><strong>Configure ignores in <code>conftest.py</code></strong></summary>

If you need project- or directory-specific ignore rules without touching `pyproject.toml`:

```python
# conftest.py
pytest_sleepfake_ignore = ["my_project.telemetry", "my_project.metrics"]
```

This is used by:

- the `sleepfake` fixture
- `@pytest.mark.sleepfake`
- global autouse mode (`sleepfake_autouse = true` or `--sleepfake`)

</details>

<details>
<summary><strong><code>asyncio.timeout</code> integration</strong></summary>

The frozen clock advances before each sleep future resolves, so `asyncio.timeout` still fires correctly:

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

</details>

<details>
<summary><strong>Options reference (API, CLI, config)</strong></summary>

| Where | Option | Example | Purpose |
|---|---|---|---|
| Python API (`SleepFake`) | `ignore: list[str] \| None` | `SleepFake(ignore=["my.module"])` | Add module prefixes freezegun should ignore while freezing time. |
| Pytest CLI | `--sleepfake` | `pytest --sleepfake` | Enable SleepFake for every test in the session. |
| Pytest CLI | `--sleepfake-ignore MODULE` | `pytest --sleepfake-ignore my.module` | Add a module prefix to ignore (repeatable; merged with `sleepfake_ignore`). |
| Pytest config (`pytest.ini` / `pyproject.toml`) | `sleepfake_autouse = true` | `[tool.pytest.ini_options]\nsleepfake_autouse = true` | Same as `--sleepfake`, but persisted in config. |
| Pytest config (`pytest.ini` / `pyproject.toml`) | `sleepfake_ignore` | `sleepfake_ignore = ["my.module"]` | Add module prefixes to ignore for all pytest-managed SleepFake usage. |
| `conftest.py` | `pytest_sleepfake_ignore` | `pytest_sleepfake_ignore = ["my.module"]` | Override ignore prefixes for a test subtree (directory-scoped). |

Notes:

- Every ignore list is merged with `DEFAULT_IGNORE = ["_pytest.timing"]`.
  This keeps pytest duration measurement on real clocks and prevents epoch-scale `--durations` output.
- User-provided ignore values are appended after `DEFAULT_IGNORE` and deduplicated.

</details>

## ⚠️ Scope limitation

SleepFake patches `time.sleep` and `asyncio.sleep` by name via `unittest.mock.patch`.
Code that binds the function locally **before** the context is entered (for example `from time import sleep` at module import time) bypasses the patch.

## 🧪 How it works

| Aspect | Detail |
|---|---|
| **Sync sleep** | `frozen_factory.tick(delta)` advances frozen time immediately |
| **Async sleep** | `(deadline, seq, future)` goes into an `asyncio.PriorityQueue`; a background task resolves futures in deadline order |
| **Timeout safety** | After advancing time, the processor yields one event-loop turn so timeout callbacks can fire before futures resolve |
| **Cancellation** | Cancelled futures are skipped; the processor keeps running |
| **pytest durations** | `freeze_time(..., ignore=["_pytest.timing", ...])` avoids breaking pytest internal wall-clock timing |

## 🤝 Contributing

PRs and issues welcome!


> **Note:** SleepFake uses [freezegun](https://github.com/spulec/freezegun) under the hood.
