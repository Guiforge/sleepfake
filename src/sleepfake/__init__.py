from __future__ import annotations

import asyncio
import contextlib
import datetime
import sys
from unittest.mock import patch

import freezegun

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class _NotInitializedError(Exception):
    def __init__(self) -> None:
        self.message = "sleep_queue is not initialized | should not happen"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


# Item stored in the priority queue: (wake_deadline_naive_utc, sequence_counter, future)
# The sequence counter breaks ties so that futures enqueued earlier are processed first.
_QueueItem = tuple[datetime.datetime, int, asyncio.Future[None]]


class SleepFake:
    """Fake the time.sleep/asyncio.sleep function during tests.

    Note:
        Uses ``unittest.mock.patch("time.sleep")`` / ``patch("asyncio.sleep")``.
        Code that binds the function locally (``from time import sleep``) before
        the context is entered will bypass the mock.
    """

    def __init__(self) -> None:
        self.freeze_time = freezegun.freeze_time(datetime.datetime.now(tz=datetime.timezone.utc))
        self._freeze_started = False
        self.frozen_factory: freezegun.api.FrozenDateTimeFactory | None = None
        self.time_patch = patch("time.sleep", side_effect=self.mock_sleep)
        self.asyncio_patch = patch("asyncio.sleep", side_effect=self.amock_sleep)
        self.sleep_queue: asyncio.PriorityQueue[_QueueItem] | None = None
        self.sleep_processor: asyncio.Task[None] | None = None
        self._seq: int = 0  # tie-breaker for equal deadlines

    def _start_freeze(self) -> None:
        if not self._freeze_started:
            # Capture _pytest.timing.perf_counter *before* starting the freeze.
            # Freezegun's to_patch mechanism scans sys.modules and replaces every
            # module attribute equal to the real perf_counter with its frozen stub,
            # including _pytest.timing.perf_counter which pytest uses to compute
            # --durations. Restoring it causes pytest to keep using the real
            # boot-relative clock, so reported durations stay near zero.
            _timing_module = None
            _real_pc = None
            try:
                import _pytest.timing  # noqa: PLC0415

                _timing_module = _pytest.timing
                _real_pc = _pytest.timing.perf_counter
            except ImportError:
                pass

            self.frozen_factory = self.freeze_time.start()
            self._freeze_started = True

            if _timing_module is not None:
                _timing_module.perf_counter = _real_pc  # type: ignore[assignment]

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
        self.sleep_queue = None

    def mock_sleep(self, seconds: float) -> None:
        """A mock sleep function that advances the frozen time instead of actually sleeping."""
        self.frozen_factory.tick(delta=datetime.timedelta(seconds=seconds))  # type: ignore[union-attr]

    async def amock_sleep(self, seconds: float) -> None:
        """A mock sleep function that advances the frozen time instead of actually sleeping.

        Raises:
            _NotInitializedError: If the sleep queue is not initialized.
        """
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
            except RuntimeError:  # noqa: PERF203
                return  # the queue is closed, when fixture pytest and pytest-asyncio
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
                tick: asyncio.Future[None] = loop.create_future()
                loop.call_soon(tick.set_result, None)
                await tick
                if not future.cancelled():
                    future.set_result(None)
