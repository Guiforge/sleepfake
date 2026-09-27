# sleepfake — Project Guidelines

## Architecture

`SleepFake` is a pytest plugin and context manager that fakes `time.sleep` / `asyncio.sleep` by:
- Patching both via `unittest.mock.patch`
- Advancing a `freezegun` frozen clock by the requested duration instead of actually sleeping
- Driving each event loop with a `_LoopDriver` (`call_soon` callbacks, no background task): when the loop is idle it jumps the clock to the earliest `asyncio.sleep` deadline, or, after `autojump_threshold` real seconds, to the earliest loop timer (`wait_for`, `asyncio.timeout`, `call_later`). `BaseEventLoop.call_at` is patched to wake the driver when a timer is scheduled

Key files:
- `src/sleepfake/__init__.py` — `SleepFake` class (sync + async context manager)
- `src/sleepfake/plugin.py` — pytest fixture and marker registration
- `tests/` — sync tests (`test_sync.py`), async tests (`test_async.py`), loop-timer autojump (`test_autojump.py`)

## Build and Test

```sh
# Install deps + run tests
uv run pytest

# Lint (ruff + ty) then test
make test-all

# Run against all supported Python versions (3.10–3.15)
make test-all-python
```

## Code Style

- **Formatter/linter**: ruff with `select = ["ALL"]` (`target-version = "py310"`, line length 100). Run `make lint`
- **Type checker**: ty with every rule set to `error` (`[tool.ty.rules] all = "error"`)
- **Git hooks**: prek (`prek.toml`), installed by `make dev-install`; run all with `make hooks`
- **pytest**: `--strict-markers --strict-config`, `filterwarnings = ["error"]`, `xfail_strict = true`
- **Docstrings**: Google style (`pydocstyle.convention = "google"`); public methods only
- Python 3.10 minimum — use `from __future__ import annotations` and `typing_extensions` for backcompat

## Conventions

- All public surface must have type annotations; avoid `Any`
- `Self` import: `from typing import Self` on 3.11+, `from typing_extensions import Self` on 3.10
- Tests use `pytester` for plugin integration (`pytest_plugins = ["pytester"]` in `conftest.py`)
- Do not add new runtime dependencies lightly — current runtime deps are `freezegun`, `pytest`, and `typing-extensions` (Python 3.10 only)
