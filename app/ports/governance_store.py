"""Tenant-explicit transactional storage for candidate governance."""

from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from app.auth.tenant_context import TenantContext
from app.domain.enums import GovernanceAction, IndexStatus, IndexType
from app.domain.models import (
    AuditLog,
    GovernanceCandidateState,
    LongTermCandidate,
    LongTermMemory,
    MemoryVersion,
)


class GovernanceTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def get_candidate_for_update(
        self,
        ctx: TenantContext,
        candidate_id: str,
    ) -> GovernanceCandidateState | None: ...

    async def existing_evidence_ids(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> frozenset[str]: ...

    async def find_exact_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> LongTermMemory | None: ...

    async def find_semantic_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> Sequence[LongTermMemory]: ...

    async def get_memory_for_update(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> LongTermMemory | None: ...

    async def create_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
    ) -> None: ...

    async def update_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        expected_version: int,
    ) -> None: ...

    async def link_superseded(
        self,
        ctx: TenantContext,
        memory_id: str,
        superseded_by_id: str,
        expected_version: int,
    ) -> None: ...

    async def add_version(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        version: MemoryVersion,
    ) -> None: ...

    async def set_candidate_result(
        self,
        ctx: TenantContext,
        candidate_id: str,
        status: str,
        action: GovernanceAction,
        reason: str,
        memory_id: str | None,
        memory_version: int | None,
    ) -> None: ...

    async def add_projection(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
        index_type: IndexType,
        status: IndexStatus,
    ) -> None: ...

    async def set_projection_status(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
        index_type: IndexType,
        status: IndexStatus,
        index_ref: str | None = None,
    ) -> None: ...

    async def list_projection_types(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
    ) -> tuple[IndexType, ...]: ...

    async def add_outbox_job(
        self,
        ctx: TenantContext,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
    ) -> None: ...

    async def append_audit(
        self,
        ctx: TenantContext,
        entry: AuditLog,
    ) -> None: ...

    async def commit(self) -> None: ...


class GovernanceUnitOfWorkFactory(Protocol):
    def open(self, ctx: TenantContext) -> GovernanceTransaction:
        """Open one transaction frozen to the trusted tenant."""
