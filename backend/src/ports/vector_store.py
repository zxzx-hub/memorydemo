"""Tenant-filtered semantic index contract."""

from collections.abc import Sequence
from typing import Protocol

from service.auth.tenant_context import TenantContext


class VectorStore(Protocol):
    async def search(
        self,
        ctx: TenantContext,
        query: str,
        limit: int,
    ) -> Sequence[str]:
        """Return current-tenant memory IDs only."""

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        """Delete one current-tenant vector projection."""
