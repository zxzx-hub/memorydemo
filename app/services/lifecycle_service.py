"""Deterministic lifecycle governance contract."""

from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.commands import GcMemoryRequest
from app.domain.results import GcMemoryResult


class LifecycleService(Protocol):
    async def apply(
        self,
        ctx: TenantContext,
        request: GcMemoryRequest,
    ) -> GcMemoryResult:
        """Apply tenant-scoped TTL, downrank, archive or deletion rules."""
