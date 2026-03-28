# sleepfake — Project Guidelines

## Architecture

`SleepFake` is a pytest plugin and context manager that fakes `time.sleep` / `asyncio.sleep` by:
- Patching both via `unittest.mock.patch`
- Advancing a `freezegun` frozen clock by the requested duration instead of actually sleeping
- Managing an `asyncio.PriorityQueue` (keyed by deadline + sequence counter) + background `Task` for correct async sleep ordering

Key files:
- `src/sleepfake/__init__.py` — `SleepFake` class (sync + async context manager)
- `src/sleepfake/plugin.py` — pytest fixture and marker registration
- `tests/` — sync tests (`test_sync.py`), async tests (`test_async.py`)

## Build and Test

```sh
# Install deps + run tests
uv run pytest --force-sugar -vvv

# Lint (ruff + mypy) then test
make test-all

# Run against all supported Python versions (3.10–3.15)
make test-all-python
```

## Code Style

- **Formatter/linter**: ruff (`target-version = "py310"`, line length 100). Run `uv run ruff check --fix . && uv run ruff format .`
- **Type checker**: mypy in strict mode (`disallow_untyped_calls`, `disallow_any_generics`, etc.)
- **Docstrings**: Google style (`pydocstyle.convention = "google"`); public methods only
- Python 3.10 minimum — use `from __future__ import annotations` and `typing_extensions` for backcompat

## Conventions

- All public surface must have type annotations; avoid `Any`
- `Self` import: `from typing import Self` on 3.11+, `from typing_extensions import Self` on 3.10
- Tests use `pytester` for plugin integration (`pytest_plugins = ["pytester"]` in `conftest.py`)
- Do not add new runtime dependencies lightly — current runtime deps are `freezegun`, `pytest`, and `typing-extensions` (Python 3.10 only)
