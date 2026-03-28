from __future__ import annotations

import asyncio
import contextlib
import datetime
import sys
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


class SleepFake:
    """Fake the time.sleep/asyncio.sleep function during tests.

    Note:
        Uses ``unittest.mock.patch("time.sleep")`` / ``patch("asyncio.sleep")``.
        Code that binds the function locally (``from time import sleep``) before
        the context is entered will bypass the mock.
    """

    def __init__(self, *, ignore: list[str] | None = None) -> None:
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
        self.sleep_processor = None
        self._seq = 0
        return self

    async def __aenter__(self) -> Self:
        return self.__enter__()

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Async cleanup for the sleep processor and queue."""
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
        """Restore the original time.sleep/asyncio.sleep function when exiting the context."""
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
        """A mock sleep function that advances the frozen time instead of actually sleeping."""
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        if self.frozen_factory is None:
            raise RuntimeError("mock_sleep called outside SleepFake context")
        self.frozen_factory.tick(delta=datetime.timedelta(seconds=seconds))

    async def amock_sleep(self, seconds: float) -> None:
        """A mock sleep function that advances the frozen time instead of actually sleeping.

        Raises:
            ValueError: If seconds is negative.
            _NotInitializedError: If the sleep queue is not initialized.
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
        """Process the priority sleep queue, advancing the time when necessary.

        Raises:
            _NotInitializedError: If the sleep queue is not initialized.
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
