"""Deterministic lifecycle governance contract."""

from typing import Protocol

from domain.commands import GcMemoryRequest
from domain.results import GcMemoryResult
from service.auth.tenant_context import TenantContext


class LifecycleService(Protocol):
    async def apply(
        self,
        ctx: TenantContext,
        request: GcMemoryRequest,
    ) -> GcMemoryResult:
        """Apply tenant-scoped TTL, downrank, archive or deletion rules."""
