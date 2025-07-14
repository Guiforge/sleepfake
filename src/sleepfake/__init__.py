from __future__ import annotations

import asyncio
import contextlib
import datetime
import time
from unittest.mock import patch

import freezegun

try:
    from typing import Self  # Python 3.11+
except ImportError:
    from typing_extensions import Self


class _NotInitializedError(Exception):
    def __init__(self) -> None:
        self.message = "sleep_queue is not initialized | should not happen"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class SleepFake:
    """Fake the time.sleep/asyncio.sleep function during tests."""

    def __init__(self) -> None:
        self.sleep = time.sleep
        self.freeze_time = freezegun.freeze_time(datetime.datetime.now(tz=datetime.UTC))
        self.frozen_factory = self.freeze_time.start()
        self.time_patch = patch("time.sleep", side_effect=self.mock_sleep)
        self.asyncio_patch = patch("asyncio.sleep", side_effect=self.amock_sleep)
        self.sleep_queue: asyncio.Queue[tuple[datetime.datetime, asyncio.Future[None]]] | None = (
            None
        )
        self.sleep_processor: asyncio.Task[None] | None = None

    async def _init_async_patch(self) -> None:
        if not self.sleep_processor and asyncio.get_event_loop().is_running():
            self.sleep_queue = asyncio.Queue()
            self.sleep_processor = asyncio.create_task(self.process_sleeps())

    def __enter__(self) -> Self:
        """Replace the time.sleep/asyncio.sleep function with the mock function when entering the context.

        Returns:
            Self: The context-managed instance.
        """
        self.time_patch.start()
        self.asyncio_patch.start()
        self.sleep_processor = None
        return self

    async def __aenter__(self) -> Self:
        return self.__enter__()

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Async cleanup for the sleep processor and queue."""
        self.time_patch.stop()
        self.asyncio_patch.stop()
        self.freeze_time.stop()
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
        self.freeze_time.stop()
        if self.sleep_processor:
            if not self.sleep_processor.done():
                self.sleep_processor.cancel()
                with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        pass
                    else:
                        loop.run_until_complete(self.sleep_processor)
            self.sleep_processor = None
        self.sleep_queue = None

    def mock_sleep(self, seconds: float) -> None:
        """A mock sleep function that advances the frozen time instead of actually sleeping."""
        self.frozen_factory.move_to(datetime.timedelta(seconds=seconds))

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

        future = asyncio.get_event_loop().create_future()
        await self.sleep_queue.put(
            (datetime.datetime.now() + datetime.timedelta(seconds=seconds), future)  # noqa: DTZ005
        )
        await future

    async def process_sleeps(self) -> None:
        """Process the sleep queue, advancing the time when necessary.

        Raises:
            _NotInitializedError: If the sleep queue is not initialized.
        """
        if self.sleep_queue is None:
            raise _NotInitializedError

        while True:
            try:
                sleep_time, future = await self.sleep_queue.get()
            except RuntimeError:  # noqa: PERF203
                return  # the queue is closed, when fixture pytest and pytest-asyncio
            else:
                # Ensure sleep_time is a datetime
                if (
                    hasattr(self.frozen_factory, "time_to_freeze")
                    and self.frozen_factory.time_to_freeze < sleep_time
                ):
                    self.frozen_factory.move_to(sleep_time)
                future.set_result(None)
