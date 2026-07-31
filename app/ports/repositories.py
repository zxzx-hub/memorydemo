"""Tenant-explicit repository contracts."""

from collections.abc import Sequence
from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.models import (
    AuditLog,
    Evidence,
    LongTermCandidate,
    LongTermMemory,
    MemoryDeletionRequest,
    MemoryLifecycleState,
    MemoryUsageStats,
    MemoryVersion,
    RawEvent,
    TaskCheckpoint,
)


class RawEventRepository(Protocol):
    async def add(self, ctx: TenantContext, event: RawEvent) -> None:
        """Persist an immutable raw event in the current tenant."""

    async def list_after(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor_event_id: str | None,
    ) -> Sequence[RawEvent]:
        """Return only current-tenant events after the cursor."""


class ConsolidationRepository(Protocol):
    async def save_siblings(
        self,
        ctx: TenantContext,
        batch_id: str,
        evidence: Evidence,
        checkpoint: TaskCheckpoint,
        candidates: Sequence[LongTermCandidate],
    ) -> None:
        """Atomically save the three Consolidate Once sibling results."""


class LongTermMemoryRepository(Protocol):
    async def get_active(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> LongTermMemory | None:
        """Load an active canonical record by tenant and memory ID."""

    async def save_with_version(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        version: MemoryVersion,
    ) -> None:
        """Persist canonical content and its append-only version."""


class LifecycleRepository(Protocol):
    async def get_state(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> tuple[MemoryUsageStats, MemoryLifecycleState] | None:
        """Load lifecycle data for one current-tenant memory."""

    async def create_deletion_request(
        self,
        ctx: TenantContext,
        request: MemoryDeletionRequest,
    ) -> None:
        """Create a tenant-scoped deletion workflow."""


class AuditRepository(Protocol):
    async def append(self, ctx: TenantContext, entry: AuditLog) -> None:
        """Append a minimal tenant-scoped audit entry."""
