"""PostgreSQL transaction adapter for MemoryService.write."""

from collections.abc import Sequence
from types import TracebackType
from typing import Self

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.auth.tenant_context import TenantContext
from app.domain.models import (
    Evidence,
    LongTermCandidate,
    RawEvent,
    TaskCheckpoint,
)
from app.infrastructure.db.models.memory import (
    ConsolidationCursorModel,
    MemoryCandidateModel,
    MemoryEventModel,
    MemoryEvidenceModel,
    OutboxJobModel,
    TaskCheckpointModel,
    TaskMemoryModel,
    WorkingMemoryModel,
)
from app.infrastructure.db.repositories.base import require_repository_context


class SqlAlchemyWriteTransaction:
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
            raise RuntimeError("Write transaction TenantContext mismatch.")
        return tenant

    async def save_event(
        self,
        ctx: TenantContext,
        workspace_id: str,
        idempotency_key: str,
        event: RawEvent,
    ) -> tuple[RawEvent, bool]:
        tenant = self._tenant(ctx)
        statement = (
            insert(MemoryEventModel)
            .values(
                tenant_id=tenant.tenant_id,
                event_id=event.event_id,
                workspace_id=workspace_id,
                event_type=event.event_type,
                role=event.role,
                content=event.content,
                source=event.source,
                session_id=event.session_id,
                task_id=event.task_id,
                principal_id=tenant.principal_id,
                trace_id=tenant.trace_id,
                idempotency_key=idempotency_key,
                source_refs=[],
                file_refs=list(event.file_refs),
                tool_result_refs=list(event.tool_result_refs),
                artifact_refs=list(event.artifact_refs),
                occurred_at=event.created_at,
                created_at=event.created_at,
            )
            .on_conflict_do_nothing()
            .returning(MemoryEventModel.event_id)
        )
        created_id = await self._session.scalar(statement)
        if created_id is not None:
            return event, True
        existing_statement = select(MemoryEventModel).where(
            MemoryEventModel.tenant_id == tenant.tenant_id,
            or_(
                MemoryEventModel.event_id == event.event_id,
                MemoryEventModel.idempotency_key == idempotency_key,
            ),
        )
        existing = await self._session.scalar(existing_statement)
        if existing is None:
            raise RuntimeError("Event conflict could not be resolved.")
        return self._to_event(existing), False

    async def ensure_working_memory(
        self,
        ctx: TenantContext,
        workspace_id: str,
        event: RawEvent,
    ) -> None:
        tenant = self._tenant(ctx)
        await self._session.execute(
            insert(WorkingMemoryModel)
            .values(
                tenant_id=tenant.tenant_id,
                workspace_id=workspace_id,
                user_id=tenant.principal_id,
                session_id=event.session_id,
                task_id=event.task_id,
                state={},
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(
            insert(ConsolidationCursorModel)
            .values(
                tenant_id=tenant.tenant_id,
                workspace_id=workspace_id,
                consolidated_until_event_id=None,
                batch_version=0,
            )
            .on_conflict_do_nothing()
        )

    async def get_cursor_for_update(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> str | None:
        tenant = self._tenant(ctx)
        statement = (
            select(ConsolidationCursorModel)
            .where(
                ConsolidationCursorModel.tenant_id == tenant.tenant_id,
                ConsolidationCursorModel.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        cursor = await self._session.scalar(statement)
        if cursor is None:
            raise RuntimeError("Tenant-scoped consolidation cursor is missing.")
        return cursor.consolidated_until_event_id

    async def list_events_after(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor: str | None,
    ) -> Sequence[RawEvent]:
        tenant = self._tenant(ctx)
        statement = select(MemoryEventModel).where(
            MemoryEventModel.tenant_id == tenant.tenant_id,
            MemoryEventModel.workspace_id == workspace_id,
        )
        if cursor is not None:
            cursor_sequence = await self._session.scalar(
                select(MemoryEventModel.event_sequence).where(
                    MemoryEventModel.tenant_id == tenant.tenant_id,
                    MemoryEventModel.event_id == cursor,
                )
            )
            if cursor_sequence is None:
                raise RuntimeError("Consolidation cursor does not resolve.")
            statement = statement.where(
                MemoryEventModel.event_sequence > cursor_sequence
            )
        rows = (
            await self._session.scalars(
                statement.order_by(MemoryEventModel.event_sequence)
            )
        ).all()
        return tuple(self._to_event(row) for row in rows)

    async def next_checkpoint_no(
        self,
        ctx: TenantContext,
        task_id: str,
    ) -> int:
        tenant = self._tenant(ctx)
        current = await self._session.scalar(
            select(func.max(TaskCheckpointModel.checkpoint_no)).where(
                TaskCheckpointModel.tenant_id == tenant.tenant_id,
                TaskCheckpointModel.task_id == task_id,
            )
        )
        return int(current or 0) + 1

    async def save_evidence(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[Evidence],
    ) -> None:
        tenant = self._tenant(ctx)
        for item in items:
            await self._session.execute(
                insert(MemoryEvidenceModel)
                .values(
                    tenant_id=tenant.tenant_id,
                    evidence_id=item.evidence_id,
                    consolidation_batch_id=batch_id,
                    source_event_ids=list(item.source_event_ids),
                    source_from_event_id=item.source_from_event_id,
                    source_to_event_id=item.source_to_event_id,
                    excerpt=item.excerpt,
                )
                .on_conflict_do_nothing()
            )

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: TaskCheckpoint | None,
    ) -> None:
        tenant = self._tenant(ctx)
        if checkpoint is None:
            return
        await self._session.execute(
            insert(TaskMemoryModel)
            .values(
                tenant_id=tenant.tenant_id,
                task_memory_id=checkpoint.task_memory_id,
                task_id=checkpoint.task_id,
                status="active",
                current_checkpoint_no=checkpoint.checkpoint_no,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "task_id"],
                set_={"current_checkpoint_no": checkpoint.checkpoint_no},
            )
        )
        await self._session.execute(
            insert(TaskCheckpointModel)
            .values(
                tenant_id=tenant.tenant_id,
                checkpoint_id=checkpoint.checkpoint_id,
                task_memory_id=checkpoint.task_memory_id,
                task_id=checkpoint.task_id,
                checkpoint_no=checkpoint.checkpoint_no,
                status="active",
                completed_steps=[],
                next_actions=[],
                active_constraints=[],
                resume_context=checkpoint.resume_context,
                intermediate_state=checkpoint.intermediate_state,
                open_questions=list(checkpoint.open_questions),
                artifact_refs=[],
                file_refs=[],
                tool_result_refs=[],
                source_event_ids=list(checkpoint.source_event_ids),
                source_from_event_id=checkpoint.source_from_event_id,
                source_to_event_id=checkpoint.source_to_event_id,
            )
            .on_conflict_do_nothing()
        )

    async def save_candidates(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[LongTermCandidate],
    ) -> None:
        tenant = self._tenant(ctx)
        for item in items:
            await self._session.execute(
                insert(MemoryCandidateModel)
                .values(
                    tenant_id=tenant.tenant_id,
                    candidate_id=item.candidate_id,
                    consolidation_batch_id=batch_id,
                    memory_type=item.memory_type.value,
                    content=item.content,
                    normalized_key=item.normalized_key,
                    scope_type=item.scope.type,
                    scope_id=item.scope.id,
                    owner_type="user",
                    owner_id=tenant.principal_id,
                    confidence=item.confidence,
                    importance=item.importance,
                    explicitness=item.explicitness,
                    evidence_ids=list(item.evidence_ids),
                    source_event_ids=list(item.source_event_ids),
                    semantic_fingerprint=item.semantic_fingerprint,
                    suggested_action=item.suggested_action,
                    sensitivity=item.sensitivity,
                    language=item.language,
                    type_payload=item.type_payload,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    staleness_score=item.staleness_score,
                    suggestion_reason=item.suggestion_reason,
                    suggestion_confidence=item.suggestion_confidence,
                    uncertainties=list(item.uncertainties),
                    possible_duplicates=list(item.possible_duplicates),
                    possible_conflicts=list(item.possible_conflicts),
                    governance_status="pending",
                )
                .on_conflict_do_nothing()
            )

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor_before: str | None,
        cursor_after: str,
    ) -> None:
        tenant = self._tenant(ctx)
        cursor_match = (
            ConsolidationCursorModel.consolidated_until_event_id.is_(None)
            if cursor_before is None
            else ConsolidationCursorModel.consolidated_until_event_id == cursor_before
        )
        result = await self._session.execute(
            update(ConsolidationCursorModel)
            .where(
                ConsolidationCursorModel.tenant_id == tenant.tenant_id,
                ConsolidationCursorModel.workspace_id == workspace_id,
                cursor_match,
            )
            .values(
                consolidated_until_event_id=cursor_after,
                batch_version=ConsolidationCursorModel.batch_version + 1,
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise RuntimeError("Consolidation cursor changed concurrently.")

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

    async def commit(self) -> None:
        await self._session.commit()
        self._committed = True

    @staticmethod
    def _to_event(model: MemoryEventModel) -> RawEvent:
        return RawEvent(
            event_id=model.event_id,
            event_type=model.event_type,
            role=model.role,
            content=model.content,
            source=model.source,
            session_id=model.session_id,
            task_id=model.task_id,
            created_at=model.created_at,
            file_refs=tuple(model.file_refs),
            tool_result_refs=tuple(model.tool_result_refs),
            artifact_refs=tuple(model.artifact_refs),
        )


class SqlAlchemyWriteUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def open(self, ctx: TenantContext) -> SqlAlchemyWriteTransaction:
        require_repository_context(ctx)
        return SqlAlchemyWriteTransaction(self._session_factory(), ctx)
