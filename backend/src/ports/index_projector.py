"""Derived-index execution boundary."""

from typing import Protocol

from domain.enums import IndexType
from domain.models import LongTermMemory
from service.auth.tenant_context import TenantContext


class IndexProjector(Protocol):
    async def project(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        index_type: IndexType,
    ) -> str | None:
        """Build one tenant-scoped derived projection and return its reference."""
