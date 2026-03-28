from __future__ import annotations

import asyncio
import contextlib
import datetime
import sys
import time as _time_module
import types
import warnings
from typing import Final
from unittest.mock import patch

import freezegun

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: no cover
    from typing_extensions import Self

__all__ = ["DEFAULT_IGNORE", "SleepFake"]


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
        self.time_patch = patch("time.sleep", side_effect=self.mock_sleep)
        self.asyncio_patch = patch("asyncio.sleep", side_effect=self.amock_sleep)
        self.sleep_queue: asyncio.PriorityQueue[_QueueItem] | None = None
        self.sleep_processor: asyncio.Task[None] | None = None
        self._seq: int = 0  # tie-breaker for equal deadlines
        self._alias_patches: list[tuple[types.ModuleType, str, object]] = []

    def _patch_module_aliases(self) -> None:
        """Scan ``sys.modules`` and patch any module-level aliases of the real sleep functions.

        This covers code that ran ``from time import sleep`` (or
        ``from asyncio import sleep``) before the :class:`SleepFake` context was
        entered.  All such attributes in loaded modules are replaced with the
        corresponding mock, and the originals are recorded for restoration in
        :meth:`_unpatch_module_aliases`.
        """
        self._alias_patches = []
        # Skip the modules that either already received the main patch or hold our
        # own internal sentinel variables (_ORIG_TIME_SLEEP / _ORIG_ASYNCIO_SLEEP).
        _self = sys.modules.get(__name__)
        ignore = tuple(self._ignore)

        for mod_name, mod in list(sys.modules.items()):
            if not isinstance(mod, types.ModuleType):
                continue
            if mod is _time_module or mod is asyncio or mod is _self:
                continue
            # Mirror freezegun: honour the ignore list so that ignored modules
            # also keep their real sleep references (e.g. _pytest.timing).
            if mod_name.startswith(ignore):
                continue
            try:
                mod_dict = mod.__dict__
            except AttributeError:  # pragma: no cover
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for name, val in list(mod_dict.items()):
                    if val is _ORIG_TIME_SLEEP:
                        replacement: object = self.mock_sleep
                    elif val is _ORIG_ASYNCIO_SLEEP:
                        replacement = self.amock_sleep
                    else:
                        continue
                    with contextlib.suppress(AttributeError, TypeError):
                        setattr(mod, name, replacement)
                        self._alias_patches.append((mod, name, val))

    def _unpatch_module_aliases(self) -> None:
        """Restore every module-level alias that was patched by :meth:`_patch_module_aliases`."""
        for mod, name, original in reversed(self._alias_patches):
            with contextlib.suppress(AttributeError, TypeError):
                setattr(mod, name, original)
        self._alias_patches = []

    def _start_freeze(self) -> None:
        if not self._freeze_started:
            self.frozen_factory = self.freeze_time.start()
            self._freeze_started = True

    def _stop_freeze(self) -> None:
        if self._freeze_started:
            self.freeze_time.stop()
            self._freeze_started = False
            self.frozen_factory = None

    async def _init_async_patch(self) -> None:
        loop = asyncio.get_running_loop()
        if not self.sleep_processor and loop.is_running():
            self.sleep_queue = asyncio.PriorityQueue()
            self.sleep_processor = asyncio.create_task(self.process_sleeps())

    def __enter__(self) -> Self:
        """Replace the time.sleep/asyncio.sleep function with the mock function when entering the context.

        Returns:
            Self: The context-managed instance.
        """
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

    async def aclose(self) -> None:
        """Cancel the background sleep processor and drain any pending futures.

        Safe to call multiple times; subsequent calls are no-ops once the
        processor has already been stopped.
        """
        self._unpatch_module_aliases()
        self.time_patch.stop()
        self.asyncio_patch.stop()
        self._stop_freeze()
        if self.sleep_processor:
            if not self.sleep_processor.done():
                self.sleep_processor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.sleep_processor
            self.sleep_processor = None
        # Cancel any futures still in the queue so coroutines awaiting them are not leaked.
        if self.sleep_queue is not None:
            while not self.sleep_queue.empty():
                try:
                    _, _, fut = self.sleep_queue.get_nowait()
                    if not fut.done():
                        fut.cancel()
                except asyncio.QueueEmpty:  # noqa: PERF203  # pragma: no cover
                    break
        self.sleep_queue = None

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Restore ``time.sleep`` / ``asyncio.sleep`` and stop the frozen clock.

        Args:
            exc_type: The exception class, or ``None`` if no exception was raised.
            exc_val: The exception instance, or ``None``.
            exc_tb: The traceback, or ``None``.
        """
        self._unpatch_module_aliases()
        self.time_patch.stop()
        self.asyncio_patch.stop()
        self._stop_freeze()
        if self.sleep_processor:
            if not self.sleep_processor.done():
                self.sleep_processor.cancel()
            self.sleep_processor = None
        # Cancel any futures still in the queue so coroutines awaiting them are not leaked.
        if self.sleep_queue is not None:
            while not self.sleep_queue.empty():
                try:
                    _, _, fut = self.sleep_queue.get_nowait()
                    if not fut.done():
                        fut.cancel()
                except asyncio.QueueEmpty:  # noqa: PERF203  # pragma: no cover
                    break
        self.sleep_queue = None

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
            raise ValueError("sleep length must be non-negative")
        if self.frozen_factory is None:
            raise RuntimeError("mock_sleep called outside SleepFake context")
        self.frozen_factory.tick(delta=datetime.timedelta(seconds=seconds))

    async def amock_sleep(self, seconds: float) -> None:
        """Enqueue a sleep request and yield until the frozen clock reaches the deadline.

        This is the replacement injected for ``asyncio.sleep``.  The background
        :meth:`process_sleeps` task advances the frozen clock and resolves
        futures in deadline order.

        Args:
            seconds: Number of seconds to wait (relative to the current frozen time).

        Raises:
            ValueError: If *seconds* is negative.
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
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        # lazy initialize the sleep queue and processor (useful for async tests fixture)
        if self.sleep_processor is None:
            await self._init_async_patch()

        if self.sleep_queue is None:
            raise _NotInitializedError

        # Compute deadline as naive UTC to match frozen_factory.time_to_freeze (also naive UTC).
        deadline = datetime.datetime.now(tz=datetime.timezone.utc).replace(
            tzinfo=None
        ) + datetime.timedelta(seconds=seconds)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._seq += 1
        await self.sleep_queue.put((deadline, self._seq, future))
        await future

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

        loop = asyncio.get_running_loop()
        while True:
            try:
                sleep_time, _seq, future = await self.sleep_queue.get()
            except RuntimeError as exc:  # noqa: PERF203
                if "event loop is closed" in str(exc).lower():  # pragma: no cover
                    return  # the queue is closed when pytest-asyncio tears down the loop
                raise  # pragma: no cover
            else:
                if future.cancelled():
                    continue
                # Advance frozen clock to the wake deadline if not already there.
                if (
                    self.frozen_factory is not None
                    and hasattr(self.frozen_factory, "time_to_freeze")
                    and self.frozen_factory.time_to_freeze < sleep_time
                ):
                    self.frozen_factory.move_to(sleep_time)
                # Yield exactly one event-loop iteration so that any call_at
                # callbacks whose deadlines have now passed (e.g. asyncio.timeout)
                # can fire and cancel pending futures before we resolve them.
                # NOTE: cannot use ``await asyncio.sleep(0)`` here — asyncio.sleep is
                # patched and calling it would re-enter amock_sleep causing recursion.
                tick: asyncio.Future[None] = loop.create_future()
                loop.call_soon(tick.set_result, None)
                await tick
                if not future.cancelled():
                    future.set_result(None)
