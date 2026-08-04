"""Tenant-scoped canonical reads, checkpoints, evidence and usage updates."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from service.auth.tenant_context import TenantContext
from domain.enums import MemoryType
from domain.models import (
    EvidenceExcerpt,
    RetrievalRecord,
    ScopeFilter,
    TaskCheckpointView,
)


class RetrievalStore(Protocol):
    async def latest_checkpoint(
        self,
        ctx: TenantContext,
        task_id: str,
        now: datetime,
    ) -> TaskCheckpointView | None:
        """Load the latest valid checkpoint by tenant + task."""

    async def resolve_normalized_key(
        self,
        ctx: TenantContext,
        memory_type: MemoryType,
        normalized_key: str,
        scopes: Sequence[ScopeFilter],
    ) -> str | None:
        """Resolve a stable key only within allowed current-tenant scopes."""

    async def get_for_recall(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> RetrievalRecord | None:
        """Re-read a canonical record by tenant + memory ID, regardless of state."""

    async def get_evidence(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> tuple[EvidenceExcerpt, ...]:
        """Return safe excerpts from current-tenant evidence only."""

    async def mark_recalled(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        recalled_at: datetime,
    ) -> None:
        """Increment recall counters for current-tenant canonical records."""

    async def mark_used(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        used_at: datetime,
    ) -> None:
        """Increment use counters only for records entering Context Package."""
