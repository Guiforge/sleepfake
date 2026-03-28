from __future__ import annotations

import pathlib
import warnings
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from sleepfake import SleepFake

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


@pytest.fixture
def sleepfake(request: pytest.FixtureRequest) -> Generator[SleepFake, None, None]:
    """Pytest fixture that patches ``time.sleep`` and ``asyncio.sleep`` for a test.

    Works transparently for both sync and async tests.  The priority-queue and
    background processor are initialised lazily on the first ``asyncio.sleep``
    call, so no separate async fixture is required.

    Args:
        request: The pytest fixture request object (injected by pytest).

    Yields:
        SleepFake: The active :class:`~sleepfake.SleepFake` instance.

    Examples:
        Sync test — ``time.sleep`` returns immediately, clock advances:

        >>> def test_no_real_wait(sleepfake):
        ...     import time, datetime
        ...     t0 = datetime.datetime.now()
        ...     time.sleep(60)
        ...     assert (datetime.datetime.now() - t0).total_seconds() == 60.0

        Async test — same fixture, no ``asleepfake`` needed:

        >>> async def test_no_real_wait_async(sleepfake):
        ...     import asyncio, datetime
        ...     t0 = datetime.datetime.now()
        ...     await asyncio.sleep(60)
        ...     assert (datetime.datetime.now() - t0).total_seconds() == 60.0

        Inspect or manually advance the clock via the yielded instance:

        >>> def test_manual_tick(sleepfake):
        ...     import datetime
        ...     t0 = datetime.datetime.now()
        ...     sleepfake.mock_sleep(120)
        ...     assert (datetime.datetime.now() - t0).total_seconds() == 120.0
    """
    with SleepFake(ignore=_resolve_ignore(request.config, request.path)) as sf:
        yield sf


@pytest.fixture
async def asleepfake(request: pytest.FixtureRequest) -> AsyncGenerator[SleepFake, None]:
    """*Deprecated* async fixture — use :func:`sleepfake` instead.

    ``sleepfake`` now works transparently in both sync and async tests.
    ``asleepfake`` emits a :class:`DeprecationWarning` and will be removed in a
    future release.

    Args:
        request: The pytest fixture request object (injected by pytest).

    Yields:
        SleepFake: The active :class:`~sleepfake.SleepFake` instance.
    """
    warnings.warn(
        "The 'asleepfake' fixture is deprecated and will be removed in a future release. "
        "Use the 'sleepfake' fixture instead — it works for both sync and async tests.",
        DeprecationWarning,
        stacklevel=2,
    )
    async with SleepFake(ignore=_resolve_ignore(request.config, request.path)) as sf:
        yield sf


# ---------------------------------------------------------------------------
# sleepfake_autouse ini option  /  --sleepfake CLI flag
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register SleepFake ini options and CLI flags with pytest.

    Adds the ``sleepfake_autouse`` / ``sleepfake_ignore`` ini options and the
    ``--sleepfake`` / ``--sleepfake-ignore`` command-line flags.

    Args:
        parser: The pytest argument parser provided by the hook.
    """
    parser.addini(
        "sleepfake_autouse",
        help="Apply SleepFake automatically to every test in the session.",
        type="bool",
        default=False,
    )
    parser.addini(
        "sleepfake_ignore",
        help="Module prefixes to ignore when freezing time.",
        type="linelist",
        default=[],
    )
    parser.addoption(
        "--sleepfake",
        action="store_true",
        default=False,
        help="Apply SleepFake automatically to every test (same as sleepfake_autouse = true).",
    )
    parser.addoption(
        "--sleepfake-ignore",
        action="append",
        default=[],
        metavar="MODULE",
        help="Add a module prefix to ignore when freezing time (repeatable; merged with sleepfake_ignore ini).",
    )


def _configured_ignore(config: pytest.Config) -> list[str]:
    ini = config.getini("sleepfake_ignore")
    entries = [str(e) for e in ini] if ini else []
    try:
        cli: list[Any] = config.getoption("--sleepfake-ignore") or []
        entries.extend(str(e) for e in cli)
    except ValueError:
        pass
    return list(dict.fromkeys(entries))


def _conftest_ignore(config: pytest.Config, path: pathlib.Path) -> list[str]:
    configured: object | None = None
    nearest_depth = -1
    for plugin in config.pluginmanager.get_plugins():
        # Use getattr with default only for dunder (not a constant-name anti-pattern)
        plugin_file = getattr(plugin, "__file__", None)
        if not isinstance(plugin_file, str):
            continue
        plugin_path = pathlib.Path(plugin_file)
        if plugin_path.name != "conftest.py":
            continue
        if not path.is_relative_to(plugin_path.parent):
            continue
        depth = len(plugin_path.parent.parts)
        # plugin is a confirmed conftest module — vars() is safe
        plugin_ns: dict[str, Any] = vars(plugin)  # type: ignore[arg-type]
        value: Any = plugin_ns.get("pytest_sleepfake_ignore")
        if value is None or depth < nearest_depth:
            continue
        nearest_depth = depth
        configured = value

    if configured is None:
        return []
    if isinstance(configured, str):
        return [configured]
    if isinstance(configured, (list, tuple)):
        return [str(e) for e in configured]
    return [str(configured)]


def _resolve_ignore(config: pytest.Config, path: pathlib.Path) -> list[str]:
    configured = [*_configured_ignore(config), *_conftest_ignore(config, path)]
    return list(dict.fromkeys(configured))


def _has_marker(item: pytest.Item, name: str) -> bool:
    """Return True if *item* has the named marker."""
    return any(item.iter_markers(name=name))


def _autouse_enabled(config: pytest.Config) -> bool:
    if config.getini("sleepfake_autouse"):
        return True
    try:
        return bool(config.getoption("sleepfake"))
    except (ValueError, AttributeError):
        return False


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``sleepfake`` / ``no_sleepfake`` markers and autouse plugin.

    Called by pytest during startup.  When ``sleepfake_autouse = true`` or the
    ``--sleepfake`` flag is present, registers
    :class:`_AutouseSleepFakePlugin` so every test is patched automatically.

    Args:
        config: The active :class:`pytest.Config` instance.
    """
    config.addinivalue_line(
        "markers",
        "sleepfake: automatically patch time.sleep/asyncio.sleep with SleepFake",
    )
    config.addinivalue_line(
        "markers",
        "no_sleepfake: opt this test out of global autouse SleepFake patching",
    )
    if _autouse_enabled(config):
        config.pluginmanager.register(_AutouseSleepFakePlugin(), "sleepfake-autouse")


class _AutouseSleepFakePlugin:
    """Registered when ``sleepfake_autouse = true`` or ``--sleepfake`` is passed.

    Uses setup/teardown hooks (not autouse fixtures) so exactly one SleepFake
    context is entered per test, regardless of sync vs async, without touching
    the fixture discovery machinery.  Tests that already use the ``sleepfake``
    fixture (or the deprecated ``asleepfake``) or ``@pytest.mark.sleepfake``
    are skipped to avoid double-patching.
    """

    _ATTR: ClassVar[str] = "_sleepfake_autouse_sf"

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        if _has_marker(item, "no_sleepfake"):
            return
        fixturenames: list[str] = getattr(item, "fixturenames", [])
        if "sleepfake" in fixturenames or "asleepfake" in fixturenames:
            return
        if _has_marker(item, "sleepfake"):
            return
        sf = SleepFake(ignore=_resolve_ignore(item.config, item.path))
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
    """Enter a :class:`~sleepfake.SleepFake` context for ``@pytest.mark.sleepfake`` tests.

    No-op when the test already requests the ``sleepfake`` or ``asleepfake``
    fixture to avoid double-patching.

    Args:
        item: The pytest test item being set up.
    """
    if not _has_marker(item, "sleepfake"):
        return
    fixturenames: list[str] = getattr(item, "fixturenames", [])
    if "sleepfake" in fixturenames or "asleepfake" in fixturenames:
        return
    sf = SleepFake(ignore=_resolve_ignore(item.config, item.path))
    sf.__enter__()
    setattr(item, _MARKER_ATTR, sf)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    """Exit the :class:`~sleepfake.SleepFake` context opened by :func:`pytest_runtest_setup`.

    Args:
        item: The pytest test item being torn down.
    """
    sf: SleepFake | None = getattr(item, _MARKER_ATTR, None)
    if sf is not None:
        sf.__exit__(None, None, None)
        delattr(item, _MARKER_ATTR)
