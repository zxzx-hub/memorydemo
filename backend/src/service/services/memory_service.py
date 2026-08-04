"""The only business service interface exposed to API orchestration."""

from typing import Protocol

from service.auth.tenant_context import TenantContext
from service.domain.commands import (
    GcMemoryRequest,
    ReadMemoryRequest,
    WriteRequest,
)
from service.domain.results import GcMemoryResult, ReadMemoryResult, WriteResult


class MemoryService(Protocol):
    async def write(
        self,
        ctx: TenantContext,
        request: WriteRequest,
    ) -> WriteResult:
        """Orchestrate actions 01, 02 and 05."""

    async def read(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
    ) -> ReadMemoryResult:
        """Orchestrate actions 03 and 04."""

    async def gc(
        self,
        ctx: TenantContext,
        request: GcMemoryRequest,
    ) -> GcMemoryResult:
        """Orchestrate action 06."""
