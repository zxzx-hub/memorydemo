"""Tenant-scoped exact key access path."""

from typing import Protocol

from service.auth.tenant_context import TenantContext


class ExactKeyStore(Protocol):
    async def resolve(
        self,
        ctx: TenantContext,
        memory_key: str,
    ) -> str | None:
        """Resolve a key to a current-tenant memory ID."""

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        """Delete current-tenant exact key projections."""
