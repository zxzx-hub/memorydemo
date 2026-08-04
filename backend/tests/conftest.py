"""Shared deterministic health probe fixtures."""

from dataclasses import dataclass

import pytest

from service.auth.tenant_context import TenantContext
from service.core.health import ReadinessProbe
from tests.fixtures.tenants import TestTenantResolver


@dataclass(slots=True)
class StubDependency:
    name: str
    available: bool = True
    calls: int = 0

    async def ping(self) -> None:
        self.calls += 1
        if not self.available:
            raise ConnectionError(f"{self.name} unavailable")


@pytest.fixture
def ready_probe() -> ReadinessProbe:
    return ReadinessProbe(
        dependencies=(
            StubDependency("postgresql"),
            StubDependency("redis"),
        ),
        timeout_seconds=0.1,
    )


@pytest.fixture
def tenant_a() -> TenantContext:
    return TestTenantResolver().context(tenant_id="tenant_a")


@pytest.fixture
def tenant_b() -> TenantContext:
    return TestTenantResolver().context(tenant_id="tenant_b")
