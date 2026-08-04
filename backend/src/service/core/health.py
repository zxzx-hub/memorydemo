"""Dependency readiness orchestration."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class HealthDependency(Protocol):
    @property
    def name(self) -> str:
        """Return a safe dependency name."""

    async def ping(self) -> None:
        """Raise when the dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    dependencies: tuple[DependencyStatus, ...]


class ReadinessProbe:
    """Check all required dependencies without exposing connection details."""

    def __init__(
        self,
        dependencies: Sequence[HealthDependency],
        timeout_seconds: float,
    ) -> None:
        self._dependencies = tuple(dependencies)
        self._timeout_seconds = timeout_seconds

    async def check(self) -> ReadinessReport:
        async def inspect(dependency: HealthDependency) -> DependencyStatus:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    await dependency.ping()
            except Exception:
                return DependencyStatus(name=dependency.name, status="unavailable")
            return DependencyStatus(name=dependency.name, status="ok")

        statuses = tuple(
            await asyncio.gather(
                *(inspect(dependency) for dependency in self._dependencies)
            )
        )
        return ReadinessReport(
            ready=all(item.status == "ok" for item in statuses),
            dependencies=statuses,
        )
