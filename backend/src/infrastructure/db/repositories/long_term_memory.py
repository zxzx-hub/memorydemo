"""SQLAlchemy canonical Long-Term Memory repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.auth.tenant_context import TenantContext
from domain.enums import MemoryStatus, MemoryType
from domain.models import (
    LongTermMemory,
    MemoryVersion,
    Scope,
)
from infrastructure.db.models.memory import (
    LongTermMemoryModel,
    LongTermMemoryVersionModel,
)
from infrastructure.db.repositories.base import (
    TenantScopedRepository,
    require_repository_context,
)


class SqlAlchemyLongTermMemoryRepository(TenantScopedRepository):
    """Read canonical records with tenant ID as the first predicate."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_active(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> LongTermMemory | None:
        tenant = require_repository_context(ctx)
        statement = select(LongTermMemoryModel).where(
            LongTermMemoryModel.tenant_id == tenant.tenant_id,
            LongTermMemoryModel.memory_id == memory_id,
            LongTermMemoryModel.status == MemoryStatus.ACTIVE.value,
        )
        model = await self._session.scalar(statement)
        if model is None:
            return None
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

    async def save_with_version(
        self,
        ctx: TenantContext,
        memory: LongTermMemory,
        version: MemoryVersion,
    ) -> None:
        tenant = require_repository_context(ctx)
        self._session.add(
            LongTermMemoryModel(
                tenant_id=tenant.tenant_id,
                memory_id=memory.memory_id,
                memory_type=memory.memory_type.value,
                owner_type=memory.owner.type,
                owner_id=memory.owner.id,
                scope_type=memory.scope.type,
                scope_id=memory.scope.id,
                status=memory.status.value,
                version=memory.version,
                content=memory.content,
                normalized_key=memory.normalized_key,
                content_hash=version.content_hash,
                type_payload=memory.type_payload,
                confidence=memory.confidence,
                importance=memory.importance,
                explicitness=memory.explicitness,
                valid_from=memory.valid_from,
                valid_to=memory.valid_to,
                evidence_ids=list(memory.evidence_ids),
                source_event_ids=list(memory.source_event_ids),
                semantic_fingerprint=memory.semantic_fingerprint,
                language=memory.language,
                last_verified_at=memory.last_verified_at,
                review_at=memory.review_at,
                staleness_score=memory.staleness_score,
                supersedes_id=memory.supersedes_id,
                superseded_by_id=memory.superseded_by_id,
                duplicate_of_id=memory.duplicate_of_id,
                merged_into_id=memory.merged_into_id,
                conflict_ids=list(memory.conflict_ids),
                reference_count=memory.reference_count,
            )
        )
        self._session.add(
            LongTermMemoryVersionModel(
                tenant_id=tenant.tenant_id,
                memory_id=memory.memory_id,
                version=version.version,
                operation=version.operation,
                content=memory.content,
                content_hash=version.content_hash,
                type_payload=memory.type_payload,
                evidence_ids=list(memory.evidence_ids),
                created_at=version.created_at,
                snapshot=version.snapshot,
            )
        )
