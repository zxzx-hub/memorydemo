"""PostgreSQL canonical reread, checkpoint, evidence and usage adapter."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.auth.tenant_context import TenantContext
from domain.enums import MemoryStatus, MemoryType
from domain.models import (
    EvidenceExcerpt,
    LongTermMemory,
    RetrievalRecord,
    Scope,
    ScopeFilter,
    TaskCheckpointView,
)
from infrastructure.db.models.memory import (
    LongTermMemoryModel,
    MemoryEvidenceModel,
    MemoryUsageStatsModel,
    TaskCheckpointModel,
)
from infrastructure.db.repositories.base import require_repository_context


class SqlAlchemyRetrievalStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def latest_checkpoint(
        self,
        ctx: TenantContext,
        task_id: str,
        now: datetime,
    ) -> TaskCheckpointView | None:
        tenant = require_repository_context(ctx)
        async with self._session_factory() as session:
            model = await session.scalar(
                select(TaskCheckpointModel)
                .where(
                    TaskCheckpointModel.tenant_id == tenant.tenant_id,
                    TaskCheckpointModel.task_id == task_id,
                    TaskCheckpointModel.status == "active",
                    or_(
                        TaskCheckpointModel.expires_at.is_(None),
                        TaskCheckpointModel.expires_at > now,
                    ),
                )
                .order_by(TaskCheckpointModel.checkpoint_no.desc())
                .limit(1)
            )
        if model is None:
            return None
        return TaskCheckpointView(
            checkpoint_id=model.checkpoint_id,
            task_id=model.task_id,
            checkpoint_no=model.checkpoint_no,
            status=model.status,
            current_stage=model.current_stage,
            resume_context=model.resume_context,
            intermediate_state=model.intermediate_state,
            next_actions=tuple(model.next_actions),
            open_questions=tuple(model.open_questions),
            source_event_ids=tuple(model.source_event_ids),
            expires_at=model.expires_at,
        )

    async def resolve_normalized_key(
        self,
        ctx: TenantContext,
        memory_type: MemoryType,
        normalized_key: str,
        scopes: Sequence[ScopeFilter],
    ) -> str | None:
        tenant = require_repository_context(ctx)
        allowed = tuple(scopes) or (ScopeFilter(type="user", id=tenant.principal_id),)
        scope_predicates = tuple(
            (LongTermMemoryModel.scope_type == scope.type)
            & (LongTermMemoryModel.scope_id == scope.id)
            for scope in allowed
        )
        async with self._session_factory() as session:
            value = await session.scalar(
                select(LongTermMemoryModel.memory_id).where(
                    LongTermMemoryModel.tenant_id == tenant.tenant_id,
                    LongTermMemoryModel.memory_type == memory_type.value,
                    LongTermMemoryModel.normalized_key == normalized_key,
                    LongTermMemoryModel.status == MemoryStatus.ACTIVE.value,
                    or_(*scope_predicates),
                )
            )
        return str(value) if value is not None else None

    async def get_for_recall(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> RetrievalRecord | None:
        tenant = require_repository_context(ctx)
        async with self._session_factory() as session:
            model = await session.scalar(
                select(LongTermMemoryModel).where(
                    LongTermMemoryModel.tenant_id == tenant.tenant_id,
                    LongTermMemoryModel.memory_id == memory_id,
                )
            )
            if model is None:
                return None
            weight = await session.scalar(
                select(MemoryUsageStatsModel.retrieval_weight).where(
                    MemoryUsageStatsModel.tenant_id == tenant.tenant_id,
                    MemoryUsageStatsModel.memory_id == memory_id,
                )
            )
        return RetrievalRecord(
            memory=self._to_memory(model),
            retrieval_weight=float(weight if weight is not None else 1),
        )

    async def get_evidence(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> tuple[EvidenceExcerpt, ...]:
        tenant = require_repository_context(ctx)
        if not evidence_ids:
            return ()
        async with self._session_factory() as session:
            models = (
                await session.scalars(
                    select(MemoryEvidenceModel).where(
                        MemoryEvidenceModel.tenant_id == tenant.tenant_id,
                        MemoryEvidenceModel.evidence_id.in_(evidence_ids),
                    )
                )
            ).all()
        by_id = {model.evidence_id: model for model in models}
        return tuple(
            EvidenceExcerpt(
                evidence_id=evidence_id,
                excerpt=by_id[evidence_id].excerpt,
                source_event_ids=tuple(by_id[evidence_id].source_event_ids),
            )
            for evidence_id in evidence_ids
            if evidence_id in by_id
        )

    async def mark_recalled(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        recalled_at: datetime,
    ) -> None:
        await self._increment_usage(
            ctx,
            memory_ids,
            count_column="recall_count",
            time_column="last_recalled_at",
            at=recalled_at,
        )

    async def mark_used(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        used_at: datetime,
    ) -> None:
        await self._increment_usage(
            ctx,
            memory_ids,
            count_column="use_count",
            time_column="last_used_at",
            at=used_at,
        )

    async def _increment_usage(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        *,
        count_column: str,
        time_column: str,
        at: datetime,
    ) -> None:
        tenant = require_repository_context(ctx)
        unique_ids = tuple(dict.fromkeys(memory_ids))
        if not unique_ids:
            return
        count_attribute = getattr(MemoryUsageStatsModel, count_column)
        async with self._session_factory() as session, session.begin():
            for memory_id in unique_ids:
                await session.execute(
                    insert(MemoryUsageStatsModel)
                    .values(
                        tenant_id=tenant.tenant_id,
                        memory_id=memory_id,
                        **{count_column: 1, time_column: at},
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "memory_id"],
                        set_={
                            count_column: count_attribute + 1,
                            time_column: at,
                        },
                    )
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
