"""Deterministic lifecycle governance contract."""

from typing import Protocol

from service.auth.tenant_context import TenantContext
from service.domain.commands import GcMemoryRequest
from service.domain.results import GcMemoryResult


class LifecycleService(Protocol):
    async def apply(
        self,
        ctx: TenantContext,
        request: GcMemoryRequest,
    ) -> GcMemoryResult:
        """Apply tenant-scoped TTL, downrank, archive or deletion rules."""
