"""Tenant-partitioned graph projection contract."""

from collections.abc import Sequence
from typing import Protocol

from app.auth.tenant_context import TenantContext


class GraphStore(Protocol):
    async def traverse(
        self,
        ctx: TenantContext,
        entity_ids: Sequence[str],
        relations: Sequence[str],
        max_depth: int,
    ) -> Sequence[str]:
        """Return memory IDs reached within the current tenant only."""

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        """Delete current-tenant graph nodes and edges for a memory."""
