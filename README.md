<!-- Shield Badges -->
<p align="center">
  <img src="./logo.png" alt="SleepFake Logo" width="160"/>
</p>
<p align="center">
  <a href="https://github.com/Guiforge/sleepfake/actions/workflows/test.yml"><img src="https://github.com/Guiforge/sleepfake/actions/workflows/test.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/sleepfake/"><img src="https://img.shields.io/pypi/v/sleepfake.svg?color=blue" alt="PyPI version"></a>
  <a href="https://pypi.org/project/sleepfake/"><img src="https://img.shields.io/pypi/pyversions/sleepfake.svg" alt="Python versions"></a>
  <img src="https://img.shields.io/badge/coverage-100%25-brightgreen" alt="Coverage 100%"/>
  <img src="https://img.shields.io/badge/free--threading-ready-blueviolet" alt="Free-threading ready"/>
  <img src="https://img.shields.io/pypi/l/sleepfake.svg" alt="License: MIT"/>
</p>

# 💤 SleepFake: Time Travel for Your Tests

Ever wish your tests could skip the waiting but keep correct time behavior? **SleepFake** patches `time.sleep` and `asyncio.sleep` so tests return instantly while frozen time moves forward exactly as requested. Async timeouts (`asyncio.wait_for`, `asyncio.timeout`, `loop.call_later`) fire on the fake clock too.

## 📦 Install

```bash
pip install sleepfake
```

Python 3.10 to 3.15, including free-threaded builds (`3.13t`+). The pytest plugin registers itself.

## ⚡ Quick start: global autouse

Make SleepFake apply to **every test**. Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
sleepfake_autouse = true
```

Now regular tests skip sleeps:

```python
import time


def test_retry():
    start = time.time()
    time.sleep(30)  # returns instantly
    assert time.time() - start >= 30
```

Async works the same way, timeouts included:

```python
import asyncio

import pytest


async def test_polling():
    start = asyncio.get_running_loop().time()
    await asyncio.sleep(10)  # returns instantly
    assert asyncio.get_running_loop().time() - start >= 10


async def test_gives_up():
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.Event().wait(), timeout=60)  # ~20 ms, not 60 s
```

> **`pytest-asyncio` users:** add `asyncio_mode = "auto"` (or mark tests with `@pytest.mark.asyncio`) so pytest collects async tests.

## 🧭 Choose your usage style

| Use case                            | Best option                                                  |
| ----------------------------------- | ------------------------------------------------------------ |
| Apply everywhere (most teams)       | Global autouse (`sleepfake_autouse = true` or `--sleepfake`) |
| Per-test explicit control           | `sleepfake` fixture                                          |
| Decoration-style usage              | `@pytest.mark.sleepfake`                                     |
| Non-pytest scripts / direct control | `SleepFake` context manager                                  |

All pytest styles share one instance per test: combining them never patches twice.

## 📚 Usage

<details>
<summary><strong>Context manager</strong></summary>

```python
import asyncio
import time

from sleepfake import SleepFake

# Sync
with SleepFake():
    start = time.time()
    time.sleep(10)  # returns instantly
    assert time.time() - start >= 10


# Async: `async with` or plain `with` both work
async def main():
    async with SleepFake():
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(5)  # returns instantly
        assert asyncio.get_running_loop().time() - start >= 5
```

Keep some modules on real clocks with `ignore`:

```python
with SleepFake(ignore=["my_project.telemetry"]):
    ...
```

</details>

<details>
<summary><strong>Fixture (<code>sleepfake</code>)</strong></summary>

```python
import asyncio
import time


def test_retry_logic(sleepfake):
    start = time.time()
    time.sleep(30)  # instantly skipped
    assert time.time() - start >= 30


async def test_polling(sleepfake):
    start = asyncio.get_running_loop().time()
    await asyncio.gather(asyncio.sleep(1), asyncio.sleep(5), asyncio.sleep(3))
    # All three complete instantly; the clock sits at +5 s
    assert asyncio.get_running_loop().time() - start >= 5
```

The fixture yields the active `SleepFake`; `sleepfake.mock_sleep(60)` advances the clock by hand.

> **Deprecated:** `asleepfake` still works but warns. Use `sleepfake` for sync and async tests.

</details>

<details>
<summary><strong>Marker (<code>@pytest.mark.sleepfake</code>)</strong></summary>

```python
import time

import pytest


@pytest.mark.sleepfake
def test_marked():
    start = time.time()
    time.sleep(100)
    assert time.time() - start >= 100
```

Works on async tests, classes and modules (`pytestmark`) too.

</details>

<details>
<summary><strong>Global autouse, opt-out and ignores</strong></summary>

Enable it in config or on the command line:

```toml
# pyproject.toml
[tool.pytest.ini_options]
sleepfake_autouse = true
sleepfake_ignore = ["my_project.telemetry", "my_project.metrics"]
```

```bash
pytest --sleepfake --sleepfake-ignore my_project.telemetry
```

Opt a single test out with `@pytest.mark.no_sleepfake` (it has no effect if the test explicitly requests the `sleepfake` fixture).

Directory-scoped ignores go in a `conftest.py`; the nearest one wins:

```python
# conftest.py
pytest_sleepfake_ignore = ["my_project.telemetry"]
```

Function-scoped fixtures are set up and torn down with the fake active; session-, module- and class-scoped fixtures stay on real time.

</details>

<details>
<summary><strong>Async timeouts and the autojump threshold</strong></summary>

`asyncio.sleep` always wakes instantly. Loop **timers** (`asyncio.wait_for`, `asyncio.timeout`, `loop.call_later`) fire once the event loop has been idle for `autojump_threshold` **real** seconds (default `0.02`). That short grace period lets real I/O, such as a local test server, answer before a timeout is forced.

```python
async def test_timeout(sleepfake):
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(2):
            await asyncio.sleep(10)  # the clock stops at +2 s, like real asyncio
```

Tune it per instance or per project:

```python
SleepFake(autojump_threshold=0)  # jump as soon as the loop is idle
SleepFake(autojump_threshold=math.inf)  # never jump: timers only fire when sleeps move the clock
```

```toml
[tool.pytest.ini_options]
sleepfake_autojump_threshold = "0.5"
```

</details>

## 🛠️ Options reference

| Where                         | Option                                | Purpose                                                                       |
| ----------------------------- | ------------------------------------- | ----------------------------------------------------------------------------- |
| `SleepFake(...)`              | `ignore: list[str]`                   | Module prefixes that stay on real clocks.                                     |
| `SleepFake(...)`              | `autojump_threshold: float`           | Real idle seconds before loop timers fire (default `0.02`, `0`, `math.inf`). |
| pytest config                 | `sleepfake_autouse = true`            | Apply SleepFake to every test.                                                |
| pytest config                 | `sleepfake_ignore`                    | Module prefixes that stay on real clocks, for every test.                    |
| pytest config                 | `sleepfake_autojump_threshold`        | Same as the constructor argument, for every test.                            |
| pytest CLI                    | `--sleepfake`                         | Same as `sleepfake_autouse = true`.                                           |
| pytest CLI                    | `--sleepfake-ignore MODULE`           | Add an ignored prefix (repeatable).                                           |
| `conftest.py`                 | `pytest_sleepfake_ignore`             | Ignored prefixes for that directory subtree (a string or an iterable).       |
| marker                        | `@pytest.mark.sleepfake`              | Apply SleepFake to one test, class or module.                                 |
| marker                        | `@pytest.mark.no_sleepfake`           | Opt one test out of global autouse.                                           |

Every ignore list is merged with `DEFAULT_IGNORE = ["_pytest.timing", "pytest_timeout"]`, which keeps pytest's `--durations` and pytest-timeout on real clocks. Disable the plugin with `-p no:sleepfake`.

## 🧪 How it works

| Aspect               | Detail                                                                                                                                         |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Clock**            | [freezegun](https://github.com/spulec/freezegun) freezes `time.time`, `time.monotonic`, `datetime.now`... and so the event loop's clock        |
| **Sync sleep**       | `time.sleep(n)` ticks the frozen clock by `n` (thread-safe)                                                                                    |
| **Async sleep**      | Once the event loop is idle, the clock jumps to the earliest pending deadline and that sleep wakes, so concurrent sleeps resolve in order     |
| **Loop timers**      | `BaseEventLoop.call_at` is patched; after `autojump_threshold` real idle seconds the clock jumps to the next timer                             |
| **Module aliases**   | `from time import sleep` / `from asyncio import sleep` bindings in `sys.modules` are swapped on entry and restored on exit                      |
| **Nesting**          | Contexts nest; the innermost one drives the clock                                                                                              |

## ⚠️ Limitations

- **Local bindings.** A `sleep` captured in a local variable before the context starts (`_sleep = time.sleep`) keeps calling the real function.
- **Real I/O under a timeout.** If real I/O takes longer than `autojump_threshold` inside a `wait_for`/`timeout`, the timeout fires on the fake clock. Raise the threshold, or set it to `math.inf`.
- **Other event loops.** Timer autojump reads asyncio's pure-Python loop internals. On other loops (e.g. uvloop) `asyncio.sleep` is still faked, but loop timers need real time.
- **Timer precision.** A timer jump lands 1 µs after the deadline: asyncio only runs a timer once the clock is strictly past it.
- **Shared clock.** The frozen clock is global: every thread and every event loop sees the same time.

## 🆚 Alternatives

| Tool                                                            | Fakes `time.sleep` | Fakes `asyncio.sleep` / loop timers | Freezes `datetime` / `time.time` |
| --------------------------------------------------------------- | ------------------ | ----------------------------------- | -------------------------------- |
| **SleepFake**                                                   | ✅                 | ✅                                  | ✅ (via freezegun)               |
| [freezegun](https://github.com/spulec/freezegun)                | ❌ (really sleeps) | ❌                                  | ✅                               |
| [time-machine](https://github.com/adamchainz/time-machine)      | ❌                 | ❌                                  | ✅                               |
| [looptime](https://github.com/nolar/looptime)                   | ❌                 | ✅ (asyncio loop time)              | ❌                               |

## 🤝 Contributing

```bash
make dev-install   # uv sync + prek git hooks
make test-all      # ruff + ty, then tests
make cov           # tests under coverage (100% required)
make test-all-python  # 3.10 to 3.15 and 3.14t
```

PRs and issues welcome. See [CHANGELOG.md](CHANGELOG.md) for release notes.
