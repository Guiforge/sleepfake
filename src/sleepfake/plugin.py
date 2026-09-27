"""Pytest plugin: ``sleepfake`` fixture, markers and autouse options."""

from __future__ import annotations

import pathlib
import warnings
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import pytest

from sleepfake import DEFAULT_AUTOJUMP_THRESHOLD, SleepFake

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
    with _new_sleepfake(request) as sf:
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
    async with _new_sleepfake(request) as sf:
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
        "sleepfake_autojump_threshold",
        help=(
            "Real seconds an idle event loop waits before the fake clock jumps to its next "
            f"timer (wait_for, asyncio.timeout, call_later). Default {DEFAULT_AUTOJUMP_THRESHOLD}; "
            "0 jumps at once; inf never jumps."
        ),
        type="string",
        default=str(DEFAULT_AUTOJUMP_THRESHOLD),
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
    cli: list[Any] = config.getoption("--sleepfake-ignore") or []
    entries.extend(str(e) for e in cli)
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
    if isinstance(configured, Iterable):
        return [str(e) for e in configured]
    msg = (
        "pytest_sleepfake_ignore must be a str or an iterable of str, "
        f"got {type(configured).__name__}"
    )
    raise pytest.UsageError(msg)


def _resolve_ignore(config: pytest.Config, path: pathlib.Path) -> list[str]:
    configured = [*_configured_ignore(config), *_conftest_ignore(config, path)]
    return list(dict.fromkeys(configured))


def _new_sleepfake(request: pytest.FixtureRequest) -> SleepFake:
    raw = request.config.getini("sleepfake_autojump_threshold")
    try:
        threshold = float(raw)
    except ValueError:
        msg = f"sleepfake_autojump_threshold must be a number, got {raw!r}"
        raise pytest.UsageError(msg) from None
    try:
        return SleepFake(
            ignore=_resolve_ignore(request.config, request.path), autojump_threshold=threshold
        )
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None


def _autouse_enabled(config: pytest.Config) -> bool:
    return bool(config.getini("sleepfake_autouse") or config.getoption("sleepfake"))


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``sleepfake`` / ``no_sleepfake`` markers.

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


@pytest.fixture(autouse=True)
def _sleepfake_auto(request: pytest.FixtureRequest) -> None:
    """Apply ``sleepfake`` to ``@pytest.mark.sleepfake`` tests, or to every test in autouse mode.

    Going through the fixture (rather than setup/teardown hooks) lets pytest order it:
    broader-scope fixtures are set up outside the frozen clock, and function fixtures
    are torn down while it is still active. A test that also requests ``sleepfake``
    shares the same instance, so nothing is patched twice.
    """
    # The deprecated fixture opens its own context.
    if "asleepfake" in request.fixturenames:
        return
    node = request.node
    if node.get_closest_marker("sleepfake") or (
        _autouse_enabled(request.config) and not node.get_closest_marker("no_sleepfake")
    ):
        request.getfixturevalue("sleepfake")
