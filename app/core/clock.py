"""Injectable clock abstraction for deterministic lifecycle tests."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware instant."""


class SystemClock:
    def now(self) -> datetime:
        """Return the current UTC instant."""

        return datetime.now(UTC)
