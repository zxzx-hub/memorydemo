"""PostgreSQL transaction adapter for deterministic candidate governance."""

from collections.abc import Sequence
from types import TracebackType
from typing import Any, Self

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.auth.tenant_context import TenantContext
from service.core.errors import VersionConflictError
from service.domain.enums import (
    GovernanceAction,
    IndexStatus,
    IndexType,
    MemoryStatus,
    MemoryType,
)
from service.domain.models import (
    AuditLog,
    GovernanceCandidateState,
    LongTermCandidate,
    LongTermMemory,
    MemoryVersion,
    Scope,
)
from service.infrastructure.db.models.memory import (
    LongTermMemoryModel,
    LongTermMemoryVersionModel,
    MemoryAuditLogModel,
    MemoryCandidateModel,
    MemoryEvidenceModel,
    MemoryIndexProjectionModel,
    OutboxJobModel,
)
from service.infrastructure.db.repositories.base import require_repository_context


class SqlAlchemyGovernanceTransaction:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._committed = False

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    def _tenant(self, ctx: TenantContext) -> TenantContext:
        tenant = require_repository_context(ctx)
        if tenant != self._ctx:
            raise RuntimeError("Governance transaction TenantContext mismatch.")
        return tenant

    async def get_candidate_for_update(
        self,
        ctx: TenantContext,
        candidate_id: str,
    ) -> GovernanceCandidateState | None:
        tenant = self._tenant(ctx)
        model = await self._session.scalar(
            select(MemoryCandidateModel)
            .where(
                MemoryCandidateModel.tenant_id == tenant.tenant_id,
                MemoryCandidateModel.candidate_id == candidate_id,
            )
            .with_for_update()
        )
        if model is None:
            return None
        action = (
            GovernanceAction(model.governance_action)
            if model.governance_action is not None
            else None
        )
        return GovernanceCandidateState(
            candidate=self._to_candidate(model),
            governance_status=model.governance_status,
            governance_action=action,
            governance_reason=model.governance_reason,
            governed_memory_id=model.governed_memory_id,
            governed_memory_version=model.governed_memory_version,
        )

    async def existing_evidence_ids(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> frozenset[str]:
        tenant = self._tenant(ctx)
        if not evidence_ids:
            return frozenset()
        rows = await self._session.scalars(
            select(MemoryEvidenceModel.evidence_id).where(
                MemoryEvidenceModel.tenant_id == tenant.tenant_id,
                MemoryEvidenceModel.evidence_id.in_(evidence_ids),
            )
        )
        return frozenset(rows.all())

    async def find_exact_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> LongTermMemory | None:
        tenant = self._tenant(ctx)
        model = await self._session.scalar(
            select(LongTermMemoryModel).where(
                LongTermMemoryModel.tenant_id == tenant.tenant_id,
                LongTermMemoryModel.scope_type == candidate.scope.type,
                LongTermMemoryModel.scope_id == candidate.scope.id,
                LongTermMemoryModel.memory_type == candidate.memory_type.value,
                LongTermMemoryModel.normalized_key == candidate.normalized_key,
                LongTermMemoryModel.status == MemoryStatus.ACTIVE.value,
            )
        )
        return self._to_memory(model) if model is not None else None

    async def find_semantic_active(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> Sequence[LongTermMemory]:
        tenant = self._tenant(ctx)
        if candidate.semantic_fingerprint is None:
            return ()
        models = (
            await self._session.scalars(
                select(LongTermMemoryModel).where(
                    LongTermMemoryModel.tenant_id == tenant.tenant_id,
                    LongTermMemoryModel.scope_type == candidate.scope.type,
                    LongTermMemoryModel.scope_id == candidate.scope.id,
                    LongTermMemoryModel.memory_type == candidate.memory_type.value,
                    LongTermMemoryModel.semantic_fingerprint
                    == candidate.semantic_fingerprint,
                    LongTermMemoryModel.status == MemoryStatus.ACTIVE.value,
                )
            )
        ).all()
        return tuple(self._to_memory(model) for model in models)

    async def get_memory_for_update(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> LongTermMemory | None:
        tenant = self._tenant(ctx)
        model = await self._session.scalar(
            select(LongTermMemoryModel)
            .where(
                LongTermMemoryModel.tenant_id == tenant.tenant_id,
                LongTermMemoryModel.memory_id == memory_id,
            )
            .with_for_update()
        )
        return self._to_memory(model) if model is not None else None

    async def create_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
    ) -> None:
        tenant = self._tenant(ctx)
        self._session.add(
            LongTermMemoryModel(
                tenant_id=tenant.tenant_id,
                **self._memory_values(memory),
            )
        )

    async def update_memory(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        expected_version: int,
    ) -> None:
        tenant = self._tenant(ctx)
        result = await self._session.execute(
            update(LongTermMemoryModel)
            .where(
                LongTermMemoryModel.tenant_id == tenant.tenant_id,
                LongTermMemoryModel.memory_id == memory.memory_id,
                LongTermMemoryModel.version == expected_version,
            )
            .values(**self._memory_values(memory))
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise VersionConflictError

    async def link_superseded(
        self,
        ctx: TenantContext,
        memory_id: str,
        superseded_by_id: str,
        expected_version: int,
    ) -> None:
        tenant = self._tenant(ctx)
        result = await self._session.execute(
            update(LongTermMemoryModel)
            .where(
                LongTermMemoryModel.tenant_id == tenant.tenant_id,
                LongTermMemoryModel.memory_id == memory_id,
                LongTermMemoryModel.version == expected_version,
            )
            .values(superseded_by_id=superseded_by_id)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise VersionConflictError

    async def add_version(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        version: MemoryVersion,
    ) -> None:
        tenant = self._tenant(ctx)
        await self._session.execute(
            insert(LongTermMemoryVersionModel)
            .values(
                tenant_id=tenant.tenant_id,
                memory_id=memory.memory_id,
                version=version.version,
                operation=version.operation,
                content=memory.content,
                content_hash=version.content_hash,
                type_payload=memory.type_payload,
                evidence_ids=list(memory.evidence_ids),
                snapshot=version.snapshot,
                created_at=version.created_at,
            )
            .on_conflict_do_nothing()
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
        tenant = self._tenant(ctx)
        result = await self._session.execute(
            update(MemoryCandidateModel)
            .where(
                MemoryCandidateModel.tenant_id == tenant.tenant_id,
                MemoryCandidateModel.candidate_id == candidate_id,
            )
            .values(
                governance_status=status,
                governance_action=action.value,
                governance_reason=reason,
                governed_memory_id=memory_id,
                governed_memory_version=memory_version,
                governed_at=self._session.info["governed_at"],
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise ResourceWarning("Candidate disappeared during governance.")

    async def add_projection(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
        index_type: IndexType,
        status: IndexStatus,
    ) -> None:
        tenant = self._tenant(ctx)
        await self._session.execute(
            insert(MemoryIndexProjectionModel)
            .values(
                tenant_id=tenant.tenant_id,
                memory_id=memory_id,
                version=version,
                index_type=index_type.value,
                index_status=status.value,
            )
            .on_conflict_do_nothing()
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
        tenant = self._tenant(ctx)
        result = await self._session.execute(
            update(MemoryIndexProjectionModel)
            .where(
                MemoryIndexProjectionModel.tenant_id == tenant.tenant_id,
                MemoryIndexProjectionModel.memory_id == memory_id,
                MemoryIndexProjectionModel.version == version,
                MemoryIndexProjectionModel.index_type == index_type.value,
            )
            .values(
                index_status=status.value,
                index_ref=index_ref,
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise RuntimeError("Tenant-scoped index projection is missing.")

    async def list_projection_types(
        self,
        ctx: TenantContext,
        memory_id: str,
        version: int,
    ) -> tuple[IndexType, ...]:
        tenant = self._tenant(ctx)
        values = await self._session.scalars(
            select(MemoryIndexProjectionModel.index_type).where(
                MemoryIndexProjectionModel.tenant_id == tenant.tenant_id,
                MemoryIndexProjectionModel.memory_id == memory_id,
                MemoryIndexProjectionModel.version == version,
            )
        )
        return tuple(IndexType(value) for value in values.all())

    async def add_outbox_job(
        self,
        ctx: TenantContext,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
    ) -> None:
        tenant = self._tenant(ctx)
        await self._session.execute(
            insert(OutboxJobModel)
            .values(
                tenant_id=tenant.tenant_id,
                job_id=job_id,
                job_type=job_type,
                payload=payload,
                status="pending",
            )
            .on_conflict_do_nothing()
        )

    async def append_audit(
        self,
        ctx: TenantContext,
        entry: AuditLog,
    ) -> None:
        tenant = self._tenant(ctx)
        await self._session.execute(
            insert(MemoryAuditLogModel)
            .values(
                tenant_id=tenant.tenant_id,
                audit_id=entry.audit_id,
                operation=entry.operation,
                result=entry.result,
                principal_id=ctx.principal_id,
                trace_id=ctx.trace_id,
                target_hash=entry.target_hash,
                reject_reason=entry.reason_code,
            )
            .on_conflict_do_nothing()
        )

    async def commit(self) -> None:
        await self._session.commit()
        self._committed = True

    @staticmethod
    def _to_candidate(model: MemoryCandidateModel) -> LongTermCandidate:
        return LongTermCandidate(
            candidate_id=model.candidate_id,
            memory_type=MemoryType(model.memory_type),
            content=model.content,
            normalized_key=model.normalized_key,
            scope=Scope(type=model.scope_type, id=model.scope_id),
            owner=Scope(type=model.owner_type, id=model.owner_id),
            confidence=model.confidence,
            importance=model.importance,
            explicitness=model.explicitness,
            evidence_ids=tuple(model.evidence_ids),
            source_event_ids=tuple(model.source_event_ids),
            semantic_fingerprint=model.semantic_fingerprint,
            suggested_action=model.suggested_action or "CREATE",
            sensitivity=model.sensitivity,
            language=model.language,
            type_payload=model.type_payload,
            valid_from=model.valid_from,
            valid_to=model.valid_to,
            staleness_score=model.staleness_score,
            suggestion_reason=model.suggestion_reason,
            suggestion_confidence=model.suggestion_confidence,
            uncertainties=tuple(model.uncertainties),
            possible_duplicates=tuple(model.possible_duplicates),
            possible_conflicts=tuple(model.possible_conflicts),
        )

    @staticmethod
    def _to_memory(model: LongTermMemoryModel) -> LongTermMemory:
        return LongTermMemory(
            memory_id=model.memory_id,
            memory_type=MemoryType(model.memory_type),
            owner=Scope(type=model.owner_type, id=model.owner_id),
            scope=Scope(type=model.scope_type, id=model.scope_id),
            content=model.content,
            normalized_key=model.normalized_key,
            evidence_ids=tuple(model.evidence_ids),
            confidence=model.confidence,
            importance=model.importance,
            explicitness=model.explicitness,
            version=model.version,
            status=MemoryStatus(model.status),
            valid_from=model.valid_from,
            valid_to=model.valid_to,
            type_payload=model.type_payload,
            content_hash=model.content_hash,
            source_event_ids=tuple(model.source_event_ids),
            semantic_fingerprint=model.semantic_fingerprint,
            language=model.language,
            last_verified_at=model.last_verified_at,
            review_at=model.review_at,
            staleness_score=model.staleness_score,
            supersedes_id=model.supersedes_id,
            superseded_by_id=model.superseded_by_id,
            duplicate_of_id=model.duplicate_of_id,
            merged_into_id=model.merged_into_id,
            conflict_ids=tuple(model.conflict_ids),
            reference_count=model.reference_count,
        )

    @staticmethod
    def _memory_values(memory: LongTermMemory) -> dict[str, Any]:
        return {
            "memory_id": memory.memory_id,
            "memory_type": memory.memory_type.value,
            "owner_type": memory.owner.type,
            "owner_id": memory.owner.id,
            "scope_type": memory.scope.type,
            "scope_id": memory.scope.id,
            "status": memory.status.value,
            "version": memory.version,
            "content": memory.content,
            "normalized_key": memory.normalized_key,
            "content_hash": memory.content_hash,
            "semantic_fingerprint": memory.semantic_fingerprint,
            "language": memory.language,
            "type_payload": memory.type_payload,
            "confidence": memory.confidence,
            "importance": memory.importance,
            "explicitness": memory.explicitness,
            "valid_from": memory.valid_from,
            "valid_to": memory.valid_to,
            "last_verified_at": memory.last_verified_at,
            "review_at": memory.review_at,
            "staleness_score": memory.staleness_score,
            "evidence_ids": list(memory.evidence_ids),
            "source_event_ids": list(memory.source_event_ids),
            "supersedes_id": memory.supersedes_id,
            "superseded_by_id": memory.superseded_by_id,
            "duplicate_of_id": memory.duplicate_of_id,
            "merged_into_id": memory.merged_into_id,
            "conflict_ids": list(memory.conflict_ids),
            "reference_count": memory.reference_count,
        }


class SqlAlchemyGovernanceUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def open(self, ctx: TenantContext) -> SqlAlchemyGovernanceTransaction:
        tenant = require_repository_context(ctx)
        session = self._session_factory()
        from datetime import UTC, datetime

        session.info["governed_at"] = datetime.now(UTC)
        return SqlAlchemyGovernanceTransaction(session, tenant)
