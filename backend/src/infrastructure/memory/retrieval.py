"""Tenant-scoped in-memory retrieval adapters."""

from collections.abc import Sequence
from datetime import datetime

from service.auth.tenant_context import TenantContext
from domain.enums import MemoryType
from domain.models import (
    EvidenceExcerpt,
    RetrievalRecord,
    ScopeFilter,
    TaskCheckpointView,
)
from infrastructure.memory.in_memory import InMemoryWriteDatabase


class InMemoryRetrievalStore:
    def __init__(self, database: InMemoryWriteDatabase) -> None:
        self.database = database

    async def latest_checkpoint(
        self,
        ctx: TenantContext,
        task_id: str,
        now: datetime,
    ) -> TaskCheckpointView | None:
        del now
        candidates = [
            checkpoint
            for (tenant_id, _), checkpoint in self.database.checkpoints.items()
            if tenant_id == ctx.tenant_id and checkpoint.task_id == task_id
        ]
        if not candidates:
            return None
        checkpoint = max(candidates, key=lambda item: item.checkpoint_no)
        return TaskCheckpointView(
            checkpoint_id=checkpoint.checkpoint_id,
            task_id=checkpoint.task_id,
            checkpoint_no=checkpoint.checkpoint_no,
            status="active",
            resume_context=checkpoint.resume_context,
            intermediate_state=checkpoint.intermediate_state,
            open_questions=checkpoint.open_questions,
            source_event_ids=checkpoint.source_event_ids,
        )

    async def resolve_normalized_key(
        self,
        ctx: TenantContext,
        memory_type: MemoryType,
        normalized_key: str,
        scopes: Sequence[ScopeFilter],
    ) -> str | None:
        scope_keys = {(scope.type, scope.id) for scope in scopes}
        for (tenant_id, memory_id), memory in self.database.long_term_memories.items():
            if tenant_id != ctx.tenant_id:
                continue
            if (
                memory.memory_type is memory_type
                and memory.normalized_key == normalized_key
                and (
                    not scope_keys or (memory.scope.type, memory.scope.id) in scope_keys
                )
            ):
                return memory_id
        return None

    async def get_for_recall(
        self,
        ctx: TenantContext,
        memory_id: str,
    ) -> RetrievalRecord | None:
        memory = self.database.long_term_memories.get((ctx.tenant_id, memory_id))
        if memory is None:
            return None
        usage = self.database.usage.get((ctx.tenant_id, memory_id), {})
        return RetrievalRecord(
            memory=memory,
            retrieval_weight=_as_float(usage.get("retrieval_weight"), 1),
        )

    async def get_evidence(
        self,
        ctx: TenantContext,
        evidence_ids: Sequence[str],
    ) -> tuple[EvidenceExcerpt, ...]:
        excerpts = []
        for evidence_id in evidence_ids:
            evidence = self.database.evidence.get((ctx.tenant_id, evidence_id))
            if evidence is not None:
                excerpts.append(
                    EvidenceExcerpt(
                        evidence_id=evidence.evidence_id,
                        excerpt=evidence.excerpt,
                        source_event_ids=evidence.source_event_ids,
                    )
                )
        return tuple(excerpts)

    async def mark_recalled(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        recalled_at: datetime,
    ) -> None:
        for memory_id in dict.fromkeys(memory_ids):
            if (ctx.tenant_id, memory_id) not in self.database.long_term_memories:
                continue
            usage = self.database.usage.setdefault(
                (ctx.tenant_id, memory_id),
                {"retrieval_weight": 1},
            )
            usage["recall_count"] = _as_int(usage.get("recall_count")) + 1
            usage["last_recalled_at"] = recalled_at

    async def mark_used(
        self,
        ctx: TenantContext,
        memory_ids: Sequence[str],
        used_at: datetime,
    ) -> None:
        for memory_id in dict.fromkeys(memory_ids):
            if (ctx.tenant_id, memory_id) not in self.database.long_term_memories:
                continue
            usage = self.database.usage.setdefault(
                (ctx.tenant_id, memory_id),
                {"retrieval_weight": 1},
            )
            usage["use_count"] = _as_int(usage.get("use_count")) + 1
            usage["last_used_at"] = used_at


class InMemoryExactKeyStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.resolve_calls = 0

    async def resolve(
        self,
        ctx: TenantContext,
        memory_key: str,
    ) -> str | None:
        self.resolve_calls += 1
        return self.items.get((ctx.tenant_id, memory_key))

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        keys = [
            key
            for key, value in self.items.items()
            if key[0] == ctx.tenant_id and value == memory_id
        ]
        for key in keys:
            del self.items[key]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.results: dict[tuple[str, str], tuple[str, ...]] = {}
        self.default_results: dict[str, tuple[str, ...]] = {}
        self.search_calls = 0

    async def search(
        self,
        ctx: TenantContext,
        query: str,
        limit: int,
    ) -> Sequence[str]:
        self.search_calls += 1
        values = self.results.get(
            (ctx.tenant_id, query),
            self.default_results.get(ctx.tenant_id, ()),
        )
        return values[:limit]

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        for key, values in tuple(self.results.items()):
            if key[0] == ctx.tenant_id:
                self.results[key] = tuple(
                    value for value in values if value != memory_id
                )


class InMemoryGraphStore:
    def __init__(self) -> None:
        self.results: dict[str, tuple[str, ...]] = {}
        self.traverse_calls = 0
        self.last_max_depth: int | None = None

    async def traverse(
        self,
        ctx: TenantContext,
        entity_ids: Sequence[str],
        relations: Sequence[str],
        max_depth: int,
    ) -> Sequence[str]:
        del entity_ids, relations
        self.traverse_calls += 1
        self.last_max_depth = max_depth
        return self.results.get(ctx.tenant_id, ())

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        self.results[ctx.tenant_id] = tuple(
            value for value in self.results.get(ctx.tenant_id, ()) if value != memory_id
        )


def _as_int(value: object | None) -> int:
    return value if isinstance(value, int) else 0


def _as_float(value: object | None, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return default
