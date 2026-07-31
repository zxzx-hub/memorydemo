"""Derived-index execution boundary."""

from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.enums import IndexType
from app.domain.models import LongTermMemory


class IndexProjector(Protocol):
    async def project(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        index_type: IndexType,
    ) -> str | None:
        """Build one tenant-scoped derived projection and return its reference."""
