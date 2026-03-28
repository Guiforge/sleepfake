from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sleepfake import SleepFake

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


@pytest.fixture
def sleepfake() -> Generator[SleepFake, None, None]:
    """Sync fixture — enters SleepFake via ``__enter__``/``__exit__``."""
    with SleepFake() as sf:
        yield sf


@pytest.fixture
async def asleepfake() -> AsyncGenerator[SleepFake, None]:
    """Async fixture — enters SleepFake via ``__aenter__``/``__aexit__``.

    Properly awaits the background sleep-processor task on teardown.
    """
    async with SleepFake() as sf:
        yield sf


# ---------------------------------------------------------------------------
# @pytest.mark.sleepfake — auto-apply SleepFake to marked tests
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``sleepfake`` marker."""
    config.addinivalue_line(
        "markers",
        "sleepfake: automatically patch time.sleep/asyncio.sleep with SleepFake",
    )


_SLEEPFAKE_ATTR = "_sleepfake_instance"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Enter a SleepFake context for tests decorated with ``@pytest.mark.sleepfake``.

    Skipped when the test already requests the ``sleepfake`` or ``asleepfake``
    fixture to avoid double-patching.
    """
    if not list(item.iter_markers(name="sleepfake")):
        return

    # Avoid double-patching when the fixture is also requested.
    fixturenames: list[str] = getattr(item, "fixturenames", [])
    if "sleepfake" in fixturenames or "asleepfake" in fixturenames:
        return

    sf = SleepFake()
    sf.__enter__()
    setattr(item, _SLEEPFAKE_ATTR, sf)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    """Exit the SleepFake context opened by the marker hook."""
    sf: SleepFake | None = getattr(item, _SLEEPFAKE_ATTR, None)
    if sf is not None:
        sf.__exit__(None, None, None)
        delattr(item, _SLEEPFAKE_ATTR)
