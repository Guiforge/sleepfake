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
# sleepfake_autouse ini option  /  --sleepfake CLI flag
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``sleepfake_autouse`` ini option and ``--sleepfake`` CLI flag."""
    parser.addini(
        "sleepfake_autouse",
        help="Apply SleepFake automatically to every test in the session.",
        type="bool",
        default=False,
    )
    parser.addoption(
        "--sleepfake",
        action="store_true",
        default=False,
        help="Apply SleepFake automatically to every test (same as sleepfake_autouse = true).",
    )


def _autouse_enabled(config: pytest.Config) -> bool:
    if config.getini("sleepfake_autouse"):
        return True
    try:
        return bool(config.getoption("sleepfake"))
    except (ValueError, AttributeError):
        return False


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``sleepfake`` marker and optionally enable autouse mode."""
    config.addinivalue_line(
        "markers",
        "sleepfake: automatically patch time.sleep/asyncio.sleep with SleepFake",
    )
    if _autouse_enabled(config):
        config.pluginmanager.register(_AutouseSleepFakePlugin(), "sleepfake-autouse")


class _AutouseSleepFakePlugin:
    """Registered when ``sleepfake_autouse = true`` or ``--sleepfake`` is passed.

    Uses setup/teardown hooks (not autouse fixtures) so exactly one SleepFake
    context is entered per test, regardless of sync vs async, without touching
    the fixture discovery machinery.  Tests that already use the
    ``sleepfake``/``asleepfake`` fixture or ``@pytest.mark.sleepfake`` are
    skipped to avoid double-patching.
    """

    _ATTR = "_sleepfake_autouse_sf"

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        fixturenames: list[str] = getattr(item, "fixturenames", [])
        if "sleepfake" in fixturenames or "asleepfake" in fixturenames:
            return
        if list(item.iter_markers(name="sleepfake")):
            return
        sf = SleepFake()
        sf.__enter__()
        setattr(item, _AutouseSleepFakePlugin._ATTR, sf)

    def pytest_runtest_teardown(self, item: pytest.Item) -> None:
        sf: SleepFake | None = getattr(item, _AutouseSleepFakePlugin._ATTR, None)
        if sf is not None:
            sf.__exit__(None, None, None)
            delattr(item, _AutouseSleepFakePlugin._ATTR)


# ---------------------------------------------------------------------------
# @pytest.mark.sleepfake — auto-apply SleepFake to marked tests
# ---------------------------------------------------------------------------

_MARKER_ATTR = "_sleepfake_marker_sf"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Enter a SleepFake context for tests decorated with ``@pytest.mark.sleepfake``.

    Skipped when the test already requests the ``sleepfake`` or ``asleepfake``
    fixture to avoid double-patching.
    """
    if not list(item.iter_markers(name="sleepfake")):
        return
    fixturenames: list[str] = getattr(item, "fixturenames", [])
    if "sleepfake" in fixturenames or "asleepfake" in fixturenames:
        return
    sf = SleepFake()
    sf.__enter__()
    setattr(item, _MARKER_ATTR, sf)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    """Exit the SleepFake context opened by the marker hook."""
    sf: SleepFake | None = getattr(item, _MARKER_ATTR, None)
    if sf is not None:
        sf.__exit__(None, None, None)
        delattr(item, _MARKER_ATTR)
