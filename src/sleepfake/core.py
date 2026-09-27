"""The :class:`SleepFake` context manager."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import heapq
import math
import sys
import threading
import time as _time_module
import types
import warnings
from typing import TYPE_CHECKING, Final, TypeVar, cast
from unittest.mock import patch

import freezegun

if TYPE_CHECKING:
    import contextvars
    from collections.abc import Callable

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

__all__ = ["DEFAULT_AUTOJUMP_THRESHOLD", "DEFAULT_IGNORE", "SleepFake"]

_T = TypeVar("_T")


# A pending asyncio.sleep: (wake_deadline_naive_utc, sequence_counter, future).
# The sequence counter breaks ties so that earlier sleeps wake first.
_Sleeper = tuple[datetime.datetime, int, asyncio.Future[None]]

# Keep pytest's duration timer on real clocks while preserving frozen-time behavior.
# Keep pytest-timeout's session-expiry check on real clocks so advancing frozen time
# during a test does not trigger a false ``session-timeout`` failure.
DEFAULT_IGNORE: Final[list[str]] = ["_pytest.timing", "pytest_timeout"]

# Real seconds the event loop must stay idle before the clock jumps to its next timer
# (``asyncio.wait_for``, ``asyncio.timeout``, ``loop.call_later``). Gives real I/O, such
# as a local test server, a chance to answer before a timeout is forced.
DEFAULT_AUTOJUMP_THRESHOLD: Final = 0.02

# Captured at import time, before any mock patch can replace them.
# Used by the broad-patch mechanism to locate module-level aliases.
_ORIG_TIME_SLEEP: Final = _time_module.sleep
_ORIG_ASYNCIO_SLEEP: Final = asyncio.sleep
_ORIG_CALL_AT: Final = asyncio.BaseEventLoop.call_at

# Upper bound on event-loop turns spent waiting for other tasks to settle, so a task
# that never stops scheduling callbacks cannot stall the fake clock forever.
_MAX_IDLE_YIELDS: Final = 1000


def _others_ready(loop: asyncio.AbstractEventLoop, turns: int) -> bool:
    """Whether other callbacks are runnable, i.e. the loop is not idle yet."""
    # ponytail: reads BaseEventLoop._ready; loops without it (uvloop) count as idle.
    return bool(getattr(loop, "_ready", None)) and turns < _MAX_IDLE_YIELDS


def _next_timer(loop: asyncio.AbstractEventLoop) -> asyncio.TimerHandle | None:
    """The earliest live timer of *loop*."""
    # ponytail: reads BaseEventLoop._scheduled; other loops get no timer autojump.
    scheduled: list[asyncio.TimerHandle] = getattr(loop, "_scheduled", [])
    live = [handle for handle in scheduled if not handle.cancelled()]
    return min(live, key=asyncio.TimerHandle.when) if live else None


class _LoopDriver:
    """Moves the frozen clock for one event loop, from ``call_soon`` callbacks.

    Whenever the loop goes idle it advances the clock to whichever comes first: the
    earliest ``asyncio.sleep`` deadline (immediately) or the earliest loop timer (after
    ``autojump_threshold`` real seconds of idleness). Callbacks rather than a task: a
    loop closed while callbacks are pending drops them silently.
    """

    def __init__(self, sleepfake: SleepFake, loop: asyncio.AbstractEventLoop) -> None:
        self.sleepfake = sleepfake
        self.loop = loop
        self.sleepers: list[_Sleeper] = []
        self._seq = 0
        self._busy = False  # a _check or _resolve callback is scheduled
        self._waking: asyncio.Future[None] | None = None  # popped, not resolved yet
        self._armed: asyncio.TimerHandle | None = None
        self._real_timer: threading.Timer | None = None
        self._stopped = False

    def add(self, deadline: datetime.datetime, future: asyncio.Future[None]) -> None:
        self._seq += 1
        heapq.heappush(self.sleepers, (deadline, self._seq, future))
        self.kick()

    def kick(self) -> None:
        """Schedule a check of what to wake next (loop thread only)."""
        if not self._busy and not self._stopped:
            self._busy = True
            self.loop.call_soon(self._check, 0)

    def _kick_threadsafe(self) -> None:
        with contextlib.suppress(RuntimeError):  # the loop was closed meanwhile
            self.loop.call_soon_threadsafe(self.kick)

    def _check(self, turns: int) -> None:
        self._busy = False
        factory = self.sleepfake.frozen_factory
        if self._stopped or factory is None:
            return
        # Let every runnable task reach its next await first: a task just woken may
        # schedule a sleep or a timer that is due before anything we know about.
        if _others_ready(self.loop, turns):
            self._busy = True
            self.loop.call_soon(self._check, turns + 1)
            return
        while self.sleepers and self.sleepers[0][2].cancelled():
            heapq.heappop(self.sleepers)
        # With an infinite threshold, loop timers only fire once sleeps move the clock.
        timer = _next_timer(self.loop) if self.sleepfake.autojump_threshold != math.inf else None
        if timer is not None and (
            not self.sleepers
            or timer.when() - self.loop.time()
            <= (self.sleepers[0][0] - factory.time_to_freeze).total_seconds()
        ):
            self._jump_to_timer(timer, factory)
        elif self.sleepers:
            deadline, _, self._waking = heapq.heappop(self.sleepers)
            if factory.time_to_freeze < deadline:
                with self.sleepfake._tick_lock:  # noqa: SLF001
                    factory.move_to(deadline)
            self._busy = True
            self.loop.call_soon(self._resolve, 0)

    def _jump_to_timer(
        self, timer: asyncio.TimerHandle, factory: freezegun.api.FrozenDateTimeFactory
    ) -> None:
        threshold = self.sleepfake.autojump_threshold
        if threshold > 0 and timer is not self._armed:
            # Wait for real idleness first; the real timer kicks us to re-check.
            self._armed = timer
            if self._real_timer is not None:
                self._real_timer.cancel()
            self._real_timer = threading.Timer(threshold, self._kick_threadsafe)
            self._real_timer.daemon = True
            self._real_timer.start()
            return
        self._armed = None
        # Land 1 µs (freezegun's resolution) past the deadline: asyncio only runs a timer
        # once ``when < time() + clock_resolution``, and at epoch-sized floats the 1 ns
        # resolution is lost, so landing exactly on ``when`` never makes it due.
        seconds = timer.when() - self.loop.time() + 1e-6
        # Round up: landing a microsecond short of the timer would never make it due.
        delta = datetime.timedelta(microseconds=math.ceil(seconds * 1_000_000))
        with self.sleepfake._tick_lock:  # noqa: SLF001
            factory.tick(delta=delta)
        self.kick()  # the timer is due now; look again once it has run

    def _resolve(self, turns: int) -> None:
        # Let timers that are now due (e.g. asyncio.timeout) fire before waking.
        if _others_ready(self.loop, turns) and not self._stopped:
            self.loop.call_soon(self._resolve, turns + 1)
            return
        self._busy = False
        future, self._waking = self._waking, None
        if future is not None and not future.done():
            future.set_result(None)
        self.kick()

    def stop(self) -> None:
        self._stopped = True
        if self._real_timer is not None:
            self._real_timer.cancel()
        # A closed loop can no longer run callbacks, so there is nothing to cancel there.
        if not self.loop.is_closed():
            for _, _, future in self.sleepers:
                future.cancel()
            if self._waking is not None:
                self._waking.cancel()
        self.sleepers.clear()
        self._waking = None


class SleepFake:
    """Fake the time.sleep/asyncio.sleep function during tests.

    Note:
        In addition to ``unittest.mock.patch("time.sleep")`` / ``patch("asyncio.sleep")``,
        :class:`SleepFake` scans ``sys.modules`` on context entry and replaces any
        module-level aliases of the real functions (e.g. ``from time import sleep``).
        The one case that cannot be covered is a **local variable** binding created
        inside a function body before the context is entered — those are invisible to
        ``sys.modules`` and will still call the real ``time.sleep``.

    Examples:
        Synchronous — clock jumps instantly, no real wall-clock delay:

        >>> import time, datetime
        >>> with SleepFake() as sf:
        ...     t0 = datetime.datetime.now()
        ...     time.sleep(30)
        ...     elapsed = (datetime.datetime.now() - t0).total_seconds()
        >>> elapsed
        30.0

        Async — works with ``async with`` or the ``sleepfake`` pytest fixture:

        >>> import asyncio, datetime
        >>> async def main():
        ...     async with SleepFake() as sf:
        ...         t0 = datetime.datetime.now()
        ...         await asyncio.sleep(10)
        ...         return (datetime.datetime.now() - t0).total_seconds()
        >>> asyncio.run(main())
        10.0
    """

    def __init__(
        self,
        *,
        ignore: list[str] | None = None,
        autojump_threshold: float = DEFAULT_AUTOJUMP_THRESHOLD,
    ) -> None:
        """Initialise a SleepFake instance.

        Args:
            ignore: Extra module prefixes that ``freezegun`` should leave on
                real clocks.  Merged after :data:`DEFAULT_IGNORE`, so the
                defaults are always active.
            autojump_threshold: Real seconds an idle event loop waits before the
                clock jumps to its next timer (``asyncio.wait_for``,
                ``asyncio.timeout``, ``loop.call_later``). ``0`` jumps at once;
                ``math.inf`` never jumps, so those timers need real time.
                ``asyncio.sleep`` is not affected: it always wakes at once.

        Raises:
            ValueError: If *autojump_threshold* is negative or NaN.

        Examples:
            Default — built-in ignores always apply:

            >>> sf = SleepFake()

            Keep an additional module on real clocks (e.g. a metrics library
            that uses ``time.time`` internally):

            >>> sf = SleepFake(ignore=["myapp.metrics"])
        """
        if not autojump_threshold >= 0:
            msg = f"autojump_threshold must be >= 0, got {autojump_threshold!r}"
            raise ValueError(msg)
        self.autojump_threshold = autojump_threshold
        resolved_ignore = [*DEFAULT_IGNORE, *(ignore or [])]
        self._ignore = resolved_ignore
        self.freeze_time = freezegun.freeze_time(
            datetime.datetime.now(tz=datetime.timezone.utc),
            ignore=resolved_ignore,
        )
        self._freeze_started = False
        self.frozen_factory: freezegun.api.FrozenDateTimeFactory | None = None
        # Bound once so module aliases can be matched by identity on exit.
        self._sleep = self.mock_sleep
        self._asleep = self.amock_sleep
        self._prev_sleep: object = _ORIG_TIME_SLEEP
        self._prev_asleep: object = _ORIG_ASYNCIO_SLEEP
        self.time_patch = patch("time.sleep", new=self._sleep)
        self.asyncio_patch = patch("asyncio.sleep", new=self._asleep)
        self.call_at_patch = patch.object(asyncio.BaseEventLoop, "call_at", new=self._call_at())
        self._drivers: dict[asyncio.AbstractEventLoop, _LoopDriver] = {}
        # tick() is a read-modify-write: without a lock, concurrent time.sleep calls
        # lose time on free-threaded builds.
        self._tick_lock = threading.Lock()

    def _swap_module_attrs(self, swaps: list[tuple[object, object]], *, honor_ignore: bool) -> None:
        """Replace, in every loaded module, each attribute that *is* ``old`` with ``new``.

        This covers ``from time import sleep`` / ``from asyncio import sleep`` aliases,
        which ``unittest.mock.patch`` alone cannot reach.
        """
        this_module = sys.modules.get(__name__)  # holds _ORIG_* on purpose
        # Mirror freezegun: ignored modules keep their real sleep on entry.
        ignore = tuple(self._ignore) if honor_ignore else ()
        for mod_name, mod in list(sys.modules.items()):
            # sys.modules is typed as ModuleType-only, but may hold other objects at runtime.
            if not isinstance(mod, types.ModuleType):  # ty: ignore[redundant-condition-strict]
                continue
            if mod is this_module or mod_name.startswith(ignore):
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for name, val in list(vars(mod).items()):
                    for old, new in swaps:
                        if val is old:
                            with contextlib.suppress(AttributeError, TypeError):
                                setattr(mod, name, new)
                            break

    def _patch_module_aliases(self) -> None:
        # The previous values matter when nested: aliases then hold the outer fake.
        self._swap_module_attrs(
            [
                (_ORIG_TIME_SLEEP, self._sleep),
                (self._prev_sleep, self._sleep),
                (_ORIG_ASYNCIO_SLEEP, self._asleep),
                (self._prev_asleep, self._asleep),
            ],
            honor_ignore=True,
        )

    def _unpatch_module_aliases(self) -> None:
        # Rescan instead of replaying a record: this also restores aliases created by
        # imports inside the context, and leaves alone anything the user reassigned.
        self._swap_module_attrs(
            [(self._sleep, self._prev_sleep), (self._asleep, self._prev_asleep)],
            honor_ignore=False,
        )

    def _start_freeze(self) -> None:
        # Re-create on every entry so a reused instance freezes at the current time.
        self.freeze_time = freezegun.freeze_time(
            datetime.datetime.now(tz=datetime.timezone.utc), ignore=self._ignore
        )
        # Without tick/auto_tick_seconds, freeze_time always yields a FrozenDateTimeFactory.
        self.frozen_factory = cast("freezegun.api.FrozenDateTimeFactory", self.freeze_time.start())
        self._freeze_started = True

    def _stop_freeze(self) -> None:
        if self._freeze_started:
            self.freeze_time.stop()
            self._freeze_started = False
            self.frozen_factory = None

    def _driver(self, loop: asyncio.AbstractEventLoop) -> _LoopDriver:
        driver = self._drivers.get(loop)
        if driver is None:
            driver = self._drivers[loop] = _LoopDriver(self, loop)
        return driver

    def _call_at(self) -> Callable[..., asyncio.TimerHandle]:
        """Build the ``BaseEventLoop.call_at`` replacement that wakes the loop's driver."""

        def call_at(
            loop: asyncio.BaseEventLoop,
            when: float,
            callback: Callable[..., object],
            *args: object,
            context: contextvars.Context | None = None,
        ) -> asyncio.TimerHandle:
            # The original, not the previous value: when nested, only the innermost
            # SleepFake drives the clock.
            handle = _ORIG_CALL_AT(loop, when, callback, *args, context=context)
            self._driver(loop).kick()
            return handle

        return call_at

    def __enter__(self) -> Self:
        """Replace the time.sleep/asyncio.sleep function with the mock function when entering the context.

        Returns:
            Self: The context-managed instance.
        """
        self._prev_sleep = _time_module.sleep
        self._prev_asleep = asyncio.sleep
        self._start_freeze()
        self.time_patch.start()
        self.asyncio_patch.start()
        self.call_at_patch.start()
        self._patch_module_aliases()
        return self

    async def __aenter__(self) -> Self:
        """Async context manager entry — delegates to :meth:`__enter__`.

        Returns:
            Self: The context-managed instance.
        """
        return self.__enter__()

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit — delegates to :meth:`aclose`.

        Args:
            exc_type: The exception class, or ``None`` if no exception was raised.
            exc_val: The exception instance, or ``None``.
            exc_tb: The traceback, or ``None``.
        """
        await self.aclose()

    def _teardown(self) -> None:
        """Undo every patch and cancel pending sleeps."""
        self._unpatch_module_aliases()
        self.time_patch.stop()
        self.asyncio_patch.stop()
        self.call_at_patch.stop()
        self._stop_freeze()
        for driver in self._drivers.values():
            driver.stop()
        self._drivers.clear()

    async def aclose(self) -> None:
        """Undo every patch and cancel pending sleeps (async counterpart of ``__exit__``).

        Safe to call multiple times.
        """
        self._teardown()

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Restore ``time.sleep`` / ``asyncio.sleep`` and stop the frozen clock.

        Args:
            exc_type: The exception class, or ``None`` if no exception was raised.
            exc_val: The exception instance, or ``None``.
            exc_tb: The traceback, or ``None``.
        """
        self._teardown()

    def mock_sleep(self, seconds: float) -> None:
        """Advance the frozen clock by *seconds* instead of blocking.

        This is the replacement injected for ``time.sleep``.

        Args:
            seconds: Number of seconds to advance the frozen clock.

        Raises:
            ValueError: If *seconds* is negative.
            RuntimeError: If called outside a :class:`SleepFake` context.

        Examples:
            Called indirectly via the patched ``time.sleep``:

            >>> import time, datetime
            >>> with SleepFake() as sf:
            ...     t0 = datetime.datetime.now()
            ...     time.sleep(5)
            ...     elapsed = (datetime.datetime.now() - t0).total_seconds()
            >>> elapsed
            5.0

            Or called directly to advance the clock without touching
            ``time.sleep``:

            >>> with SleepFake() as sf:
            ...     t0 = datetime.datetime.now()
            ...     sf.mock_sleep(60)
            ...     elapsed = (datetime.datetime.now() - t0).total_seconds()
            >>> elapsed
            60.0
        """
        if seconds < 0:
            msg = "sleep length must be non-negative"
            raise ValueError(msg)
        if self.frozen_factory is None:
            msg = "mock_sleep called outside SleepFake context"
            raise RuntimeError(msg)
        with self._tick_lock:
            self.frozen_factory.tick(delta=datetime.timedelta(seconds=seconds))

    async def amock_sleep(self, seconds: float, result: _T | None = None) -> _T | None:
        """Enqueue a sleep request and yield until the frozen clock reaches the deadline.

        This is the replacement injected for ``asyncio.sleep``.  Once the event loop
        is idle, the frozen clock jumps to the earliest deadline and that sleep wakes,
        so concurrent sleeps resolve in deadline order.

        Args:
            seconds: Number of seconds to wait (relative to the current frozen time).
                Negative values behave like ``0``, as with the real ``asyncio.sleep``.
            result: Value returned once the sleep completes.

        Returns:
            *result*, like the real ``asyncio.sleep``.

        Examples:
            Called indirectly via the patched ``asyncio.sleep`` (most common):

            >>> import asyncio, datetime
            >>> async def main():
            ...     async with SleepFake() as sf:
            ...         t0 = datetime.datetime.now()
            ...         await asyncio.sleep(7)
            ...         return (datetime.datetime.now() - t0).total_seconds()
            >>> asyncio.run(main())
            7.0

            Multiple concurrent sleeps resolve in deadline order:

            >>> async def race():
            ...     results = []
            ...     async with SleepFake():
            ...         async def task(n):
            ...             await asyncio.sleep(n)
            ...             results.append(n)
            ...         await asyncio.gather(task(3), task(1), task(2))
            ...     return results
            >>> asyncio.run(race())
            [1, 2, 3]
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        try:
            # Naive UTC, to match frozen_factory.time_to_freeze.
            deadline = datetime.datetime.now(tz=datetime.timezone.utc).replace(
                tzinfo=None
            ) + datetime.timedelta(seconds=seconds)
        except OverflowError:
            # inf, or beyond datetime's range: never scheduled, so it sleeps until cancelled.
            pass
        else:
            self._driver(loop).add(deadline, future)
        await future
        return result
