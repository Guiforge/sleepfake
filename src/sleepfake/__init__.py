"""Fake ``time.sleep`` and ``asyncio.sleep`` in tests by advancing a frozen clock."""

from __future__ import annotations

from sleepfake.core import DEFAULT_IGNORE, SleepFake

__all__ = ["DEFAULT_IGNORE", "SleepFake"]
