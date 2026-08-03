"""Transactional in-memory candidate governance adapter."""

from collections.abc import Sequence
from copy import deepcopy
from types import TracebackType
from typing import Self

from app.auth.tenant_context import TenantContext
from app.core.errors import VersionConflictError
from app.domain.enums import GovernanceAction, IndexStatus, IndexType, MemoryStatus
from app.domain.models import (
    AuditLog,
    GovernanceCandidateState,
    LongTermCandidate,
    LongTermMemory,
    MemoryVersion,
)
from app.infrastructure.memory.in_memory import InMemoryWriteDatabase


class InMemoryGovernanceTransaction:
    def __init__(
        self,
        database: InMemoryWriteDatabase,
        ctx: TenantContext,
    ) -> None:
        self._database = database
        self._ctx = ctx
        self._state: InMemoryWriteDatabase | None = None

    async def __aenter__(self) -> Self:
        self._state = deepcopy(self._database)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self._state = None

    def _current(self, ctx: TenantContext) -> InMemoryWriteDatabase:
        if self._state is None or ctx != self._ctx:
            raise RuntimeError("Governance transaction context mismatch.")
        return self._state

    async def get_candidate_for_update(
        self,
        ctx: TenantContext,
        candidate_id: str,
    ) -> GovernanceCandidateState | None:
        state = self._current(ctx)
        key = (ctx.tenant_id, candidate_id)
        outcome = state.candidate_outcomes.get(key)
        if outcome is not None:
            return outcome
        candidate = state.candidates.get(key)
        if candidate is None:
            return None
        return GovernanceCandidateState(
            candidate=candidate,
            governance_status="pending",
        )

    async def existing_evidence_ids(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> frozenset[str]:
        state = self._current(ctx)
        return frozenset(
            evidence_id
            for evidence_id in evidence_ids
            if (ctx.tenant_id, evidence_id) in state.evidence
        )

    async def find_exact_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> LongTermMemory | None:
        state = self._current(ctx)
        return next(
            (
                memory
                for (tenant_id, _), memory in state.long_term_memories.items()
                if tenant_id == ctx.tenant_id
                and memory.status is MemoryStatus.ACTIVE
                and memory.scope == candidate.scope
                and memory.memory_type is candidate.memory_type
                and memory.normalized_key == candidate.normalized_key
            ),
            None,
        )

    async def find_semantic_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> Sequence[LongTermMemory]:
        state = self._current(ctx)
        if candidate.semantic_fingerprint is None:
            return ()
        return tuple(
            memory
            for (tenant_id, _), memory in state.long_term_memories.items()
            if tenant_id == ctx.tenant_id
            and memory.status is MemoryStatus.ACTIVE
            and memory.scope == candidate.scope
            and memory.memory_type is candidate.memory_type
            and memory.semantic_fingerprint == candidate.semantic_fingerprint
        )

    async def get_memory_for_update(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> LongTermMemory | None:
        return self._current(ctx).long_term_memories.get((ctx.tenant_id, memory_id))

    async def create_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
    ) -> None:
        state = self._current(ctx)
        key = (ctx.tenant_id, memory.memory_id)
        if key in state.long_term_memories:
            raise RuntimeError("Canonical memory already exists.")
        if any(
            tenant_id == ctx.tenant_id
            and existing.scope == memory.scope
            and existing.memory_type is memory.memory_type
            and existing.normalized_key == memory.normalized_key
            for (tenant_id, _), existing in state.long_term_memories.items()
        ):
            raise RuntimeError("Canonical normalized key already exists.")
        state.long_term_memories[key] = memory

    async def update_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        expected_version: int,
    ) -> None:
        state = self._current(ctx)
        key = (ctx.tenant_id, memory.memory_id)
        current = state.long_term_memories.get(key)
        if (
            state.force_version_conflict
            or current is None
            or current.version != expected_version
        ):
            raise VersionConflictError
        state.long_term_memories[key] = memory

    async def link_superseded(
        self,
        ctx: TenantContext,
        memory_id: str,
        superseded_by_id: str,
        expected_version: int,
    ) -> None:
        state = self._current(ctx)
        key = (ctx.tenant_id, memory_id)
        current = state.long_term_memories.get(key)
        if current is None or current.version != expected_version:
            raise VersionConflictError
        if (ctx.tenant_id, superseded_by_id) not in state.long_term_memories:
            raise VersionConflictError
        state.long_term_memories[key] = current.model_copy(
            update={"superseded_by_id": superseded_by_id}
        )

    async def add_version(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        version: MemoryVersion,
    ) -> None:
        state = self._current(ctx)
        state.versions.setdefault(
            (ctx.tenant_id, memory.memory_id, version.version),
            version,
        )

    async def set_candidate_result(
        self,
        ctx: TenantContext,
        candidate_id: str,
        status: str,
        action: GovernanceAction,
        reason: str,
        memory_id: str | None,
        memory_version: int | None,
    ) -> None:
        state = self._current(ctx)
        candidate = state.candidates.get((ctx.tenant_id, candidate_id))
        if candidate is None:
            raise RuntimeError("Candidate disappeared during governance.")
        state.candidate_outcomes[(ctx.tenant_id, candidate_id)] = (
            GovernanceCandidateState(
                candidate=candidate,
                governance_status=status,
                governance_action=action,
                governance_reason=reason,
                governed_memory_id=memory_id,
                governed_memory_version=memory_version,
            )
        )

    async def add_projection(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
        index_type: IndexType,
        status: IndexStatus,
    ) -> None:
        state = self._current(ctx)
        state.projections.setdefault(
            (ctx.tenant_id, memory_id, version, index_type),
            (status, None),
        )

    async def set_projection_status(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
        index_type: IndexType,
        status: IndexStatus,
        index_ref: str | None = None,
    ) -> None:
        state = self._current(ctx)
        key = (ctx.tenant_id, memory_id, version, index_type)
        if key not in state.projections:
            raise RuntimeError("Projection does not exist.")
        state.projections[key] = (status, index_ref)

    async def list_projection_types(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
    ) -> tuple[IndexType, ...]:
        state = self._current(ctx)
        return tuple(
            index_type
            for (
                tenant_id,
                projected_memory_id,
                projected_version,
                index_type,
            ) in state.projections
            if tenant_id == ctx.tenant_id
            and projected_memory_id == memory_id
            and projected_version == version
        )

    async def add_outbox_job(
        self,
        ctx: TenantContext,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
    ) -> None:
        state = self._current(ctx)
        state.outbox.setdefault(
            (ctx.tenant_id, job_id),
            {"job_type": job_type, "payload": payload},
        )

    async def append_audit(
        self,
        ctx: TenantContext,
        entry: AuditLog,
    ) -> None:
        self._current(ctx).audits.setdefault(
            (ctx.tenant_id, entry.audit_id),
            entry,
        )

    async def commit(self) -> None:
        if self._state is None:
            raise RuntimeError("Governance transaction is not open.")
        force_conflict = self._database.force_version_conflict
        committed = deepcopy(self._state)
        self._database.__dict__.update(committed.__dict__)
        self._database.force_version_conflict = force_conflict


class InMemoryGovernanceUnitOfWorkFactory:
    def __init__(self, database: InMemoryWriteDatabase) -> None:
        self.database = database

    def open(self, ctx: TenantContext) -> InMemoryGovernanceTransaction:
        return InMemoryGovernanceTransaction(self.database, ctx)
