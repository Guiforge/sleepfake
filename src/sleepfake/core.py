"""The :class:`SleepFake` context manager."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import sys
import time as _time_module
import types
import warnings
from typing import Final, TypeVar, cast
from unittest.mock import patch

import freezegun

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: no cover
    from typing_extensions import Self

__all__ = ["DEFAULT_IGNORE", "SleepFake"]

_T = TypeVar("_T")


class _NotInitializedError(Exception):
    def __init__(self) -> None:
        self.message = "sleep_queue is not initialized | should not happen"
        super().__init__(self.message)


# Item stored in the priority queue: (wake_deadline_naive_utc, sequence_counter, future)
# The sequence counter breaks ties so that futures enqueued earlier are processed first.
_QueueItem = tuple[datetime.datetime, int, asyncio.Future[None]]

# Keep pytest's duration timer on real clocks while preserving frozen-time behavior.
# Keep pytest-timeout's session-expiry check on real clocks so advancing frozen time
# during a test does not trigger a false ``session-timeout`` failure.
DEFAULT_IGNORE: Final[list[str]] = ["_pytest.timing", "pytest_timeout"]

# Captured at import time, before any mock patch can replace them.
# Used by the broad-patch mechanism to locate module-level aliases.
_ORIG_TIME_SLEEP: Final = _time_module.sleep
_ORIG_ASYNCIO_SLEEP: Final = asyncio.sleep


# Upper bound on event-loop turns spent waiting for other tasks to settle, so a task
# that never stops scheduling callbacks cannot stall the fake clock forever.
_MAX_IDLE_YIELDS: Final = 1000


def _set_result_unless_done(fut: asyncio.Future[None]) -> None:
    if not fut.done():
        fut.set_result(None)


async def _yield_once(loop: asyncio.AbstractEventLoop) -> None:
    # Cannot use ``asyncio.sleep(0)``: it is patched and would re-enter amock_sleep.
    tick: asyncio.Future[None] = loop.create_future()
    loop.call_soon(_set_result_unless_done, tick)
    await tick


async def _run_until_idle(loop: asyncio.AbstractEventLoop) -> None:
    """Yield until no other callback is ready, so woken tasks reach their next ``await``."""
    # ponytail: reads BaseEventLoop._ready; loops without it (uvloop) get a single yield.
    ready = getattr(loop, "_ready", None)
    for _ in range(_MAX_IDLE_YIELDS):
        await _yield_once(loop)
        if not ready:
            return


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

    def __init__(self, *, ignore: list[str] | None = None) -> None:
        """Initialise a SleepFake instance.

        Args:
            ignore: Extra module prefixes that ``freezegun`` should leave on
                real clocks.  Merged after :data:`DEFAULT_IGNORE`, so the
                defaults are always active.

        Examples:
            Default — built-in ignores always apply:

            >>> sf = SleepFake()

            Keep an additional module on real clocks (e.g. a metrics library
            that uses ``time.time`` internally):

            >>> sf = SleepFake(ignore=["myapp.metrics"])
        """
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
        self.sleep_queue: asyncio.PriorityQueue[_QueueItem] | None = None
        self.sleep_processor: asyncio.Task[None] | None = None
        self._seq: int = 0  # tie-breaker for equal deadlines

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

    def _init_async_patch(self) -> None:
        self.sleep_queue = asyncio.PriorityQueue()
        self.sleep_processor = asyncio.create_task(self.process_sleeps())

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
        self._patch_module_aliases()
        self.sleep_processor = None
        self._seq = 0
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

    def _teardown(self) -> asyncio.Task[None] | None:
        """Undo every patch, cancel pending sleeps and return the processor to await, if any."""
        self._unpatch_module_aliases()
        self.time_patch.stop()
        self.asyncio_patch.stop()
        self._stop_freeze()
        processor, self.sleep_processor = self.sleep_processor, None
        queue, self.sleep_queue = self.sleep_queue, None
        # Cancel any futures still in the queue so coroutines awaiting them are not leaked.
        # A closed loop can no longer run callbacks, so there is nothing to cancel there.
        while queue is not None and not queue.empty():
            _, _, fut = queue.get_nowait()
            if not fut.get_loop().is_closed():
                fut.cancel()
        if processor is None or processor.done() or processor.get_loop().is_closed():
            return None
        processor.cancel()
        return processor

    async def aclose(self) -> None:
        """Cancel the background sleep processor and drain any pending futures.

        Safe to call multiple times; subsequent calls are no-ops once the
        processor has already been stopped.
        """
        processor = self._teardown()
        if processor is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await processor

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
        self.frozen_factory.tick(delta=datetime.timedelta(seconds=seconds))

    async def amock_sleep(self, seconds: float, result: _T | None = None) -> _T | None:
        """Enqueue a sleep request and yield until the frozen clock reaches the deadline.

        This is the replacement injected for ``asyncio.sleep``.  The background
        :meth:`process_sleeps` task advances the frozen clock and resolves
        futures in deadline order.

        Args:
            seconds: Number of seconds to wait (relative to the current frozen time).
                Negative values behave like ``0``, as with the real ``asyncio.sleep``.
            result: Value returned once the sleep completes.

        Returns:
            *result*, like the real ``asyncio.sleep``.

        Raises:
            _NotInitializedError: If the sleep queue has not been initialised.

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
        # Lazily start the processor, and restart it when a new event loop is used
        # (e.g. ``asyncio.run`` called twice inside one sync ``with SleepFake()``).
        processor = self.sleep_processor
        if processor is None or processor.done() or processor.get_loop() is not loop:
            self._init_async_patch()

        if self.sleep_queue is None:
            raise _NotInitializedError

        future: asyncio.Future[None] = loop.create_future()
        try:
            # Naive UTC, to match frozen_factory.time_to_freeze.
            deadline: datetime.datetime | None = datetime.datetime.now(
                tz=datetime.timezone.utc
            ).replace(tzinfo=None) + datetime.timedelta(seconds=seconds)
        except OverflowError:
            # inf, or beyond datetime's range: never enqueued, so it sleeps until cancelled.
            deadline = None
        if deadline is not None:
            self._seq += 1
            await self.sleep_queue.put((deadline, self._seq, future))
        await future
        return result

    async def process_sleeps(self) -> None:
        """Drain the priority queue and resolve futures in wake-deadline order.

        Runs as a background :class:`asyncio.Task` for the lifetime of the
        :class:`SleepFake` context.  For each item dequeued the frozen clock is
        moved to the item's deadline (if it has not already passed) and the
        associated future is resolved, unblocking the corresponding
        ``asyncio.sleep`` caller.

        Raises:
            _NotInitializedError: If the sleep queue has not been initialised.
        """
        if self.sleep_queue is None:
            raise _NotInitializedError

        queue = self.sleep_queue
        loop = asyncio.get_running_loop()
        while True:
            item = await queue.get()
            try:
                # Let every runnable task reach its next await first: a task just woken
                # may enqueue a sleep that is due before this one.
                await _run_until_idle(loop)
                queue.put_nowait(item)
                item = queue.get_nowait()
                deadline, _, future = item
                if future.cancelled():
                    continue
                if (
                    self.frozen_factory is not None
                    and self.frozen_factory.time_to_freeze < deadline
                ):
                    self.frozen_factory.move_to(deadline)
                # Let timers that are now due (e.g. asyncio.timeout) fire before waking.
                await _run_until_idle(loop)
            except asyncio.CancelledError:
                # The context is exiting: release the sleeper we already dequeued.
                item[2].cancel()
                raise
            if not future.cancelled():
                future.set_result(None)
