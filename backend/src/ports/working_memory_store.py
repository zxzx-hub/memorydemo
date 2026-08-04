"""Working Memory persistence contract."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from service.auth.tenant_context import TenantContext
from domain.models import WorkingMemory


class WorkingMemoryStore(Protocol):
    async def get(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> WorkingMemory | None:
        """Load one tenant-scoped workspace."""

    async def save(
        self,
        ctx: TenantContext,
        working_memory: WorkingMemory,
    ) -> None:
        """Save one tenant-scoped workspace."""

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        expected_cursor: str | None,
        new_cursor: str,
    ) -> bool:
        """Compare-and-set the consolidation cursor."""

    def lock(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> AbstractAsyncContextManager[None]:
        """Acquire a tenant + workspace scoped consolidation lock."""
