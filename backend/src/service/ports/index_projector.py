"""Derived-index execution boundary."""

from typing import Protocol

from service.auth.tenant_context import TenantContext
from service.domain.enums import IndexType
from service.domain.models import LongTermMemory


class IndexProjector(Protocol):
    async def project(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        index_type: IndexType,
    ) -> str | None:
        """Build one tenant-scoped derived projection and return its reference."""
