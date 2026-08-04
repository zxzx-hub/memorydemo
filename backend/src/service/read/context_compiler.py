"""Minimal Context Package compiler with deterministic token budgeting."""

from dataclasses import dataclass
from math import ceil

from service.auth.tenant_context import TenantContext
from domain.enums import MemoryType
from domain.models import (
    ContextMeta,
    ContextPackage,
    EvidenceExcerpt,
    MemoryContextItem,
    RankedMemory,
    TaskCheckpointView,
    TokenUsage,
)
from ports.retrieval_store import RetrievalStore


@dataclass(frozen=True, slots=True)
class CompiledContext:
    package: ContextPackage
    used_memory_ids: tuple[str, ...]


class DefaultContextCompiler:
    def empty(
        self,
        meta: ContextMeta,
        *,
        task_checkpoint: TaskCheckpointView | None = None,
    ) -> ContextPackage:
        return ContextPackage(
            meta=meta,
            task_checkpoint=task_checkpoint,
            token_usage=TokenUsage(
                budget=meta.token_budget,
                used=0,
                remaining=meta.token_budget,
            ),
        )

    async def compile(
        self,
        ctx: TenantContext,
        meta: ContextMeta,
        ranked: list[RankedMemory],
        excluded_memory_ids: tuple[str, ...],
        top_k: int,
        token_budget: int,
        need_evidence: bool,
        store: RetrievalStore,
    ) -> CompiledContext:
        selected: list[MemoryContextItem] = []
        selected_ranked: list[RankedMemory] = []
        excluded = list(excluded_memory_ids)
        tokens_used = 0
        truncated = False
        for item in ranked:
            if len(selected) >= top_k:
                excluded.append(item.memory.memory_id)
                truncated = True
                continue
            tokens = estimate_tokens(item.memory.content)
            if tokens_used + tokens > token_budget:
                excluded.append(item.memory.memory_id)
                truncated = True
                continue
            selected.append(
                MemoryContextItem(
                    memory_id=item.memory.memory_id,
                    memory_type=item.memory.memory_type,
                    content=item.memory.content,
                    confidence=item.memory.confidence,
                    scope=item.memory.scope,
                    version=item.memory.version,
                    matched_reason=item.matched_reason,
                    evidence_ids=item.memory.evidence_ids,
                )
            )
            selected_ranked.append(item)
            tokens_used += tokens

        evidence: tuple[EvidenceExcerpt, ...] = ()
        if need_evidence and selected_ranked:
            evidence_ids = tuple(
                dict.fromkeys(
                    evidence_id
                    for item in selected_ranked
                    for evidence_id in item.memory.evidence_ids
                )
            )
            fetched = await store.get_evidence(ctx, evidence_ids)
            admitted = []
            for excerpt in fetched:
                excerpt_tokens = estimate_tokens(excerpt.excerpt or "")
                if tokens_used + excerpt_tokens > token_budget:
                    truncated = True
                    break
                admitted.append(excerpt)
                tokens_used += excerpt_tokens
            evidence = tuple(admitted)

        grouped: dict[MemoryType, list[MemoryContextItem]] = {
            MemoryType.FACT: [],
            MemoryType.PREFERENCE: [],
            MemoryType.CONSTRAINT: [],
            MemoryType.DECISION: [],
            MemoryType.PROGRESS: [],
        }
        for memory_item in selected:
            grouped[memory_item.memory_type].append(memory_item)

        package = ContextPackage(
            meta=meta,
            facts=tuple(grouped[MemoryType.FACT]),
            preferences=tuple(grouped[MemoryType.PREFERENCE]),
            constraints=tuple(grouped[MemoryType.CONSTRAINT]),
            decisions=tuple(grouped[MemoryType.DECISION]),
            progress=tuple(grouped[MemoryType.PROGRESS]),
            evidence=evidence,
            excluded_memory_ids=tuple(dict.fromkeys(excluded)),
            token_usage=TokenUsage(
                budget=token_budget,
                used=tokens_used,
                remaining=max(token_budget - tokens_used, 0),
                truncated=truncated,
            ),
        )
        return CompiledContext(
            package=package,
            used_memory_ids=tuple(item.memory.memory_id for item in selected_ranked),
        )


def estimate_tokens(content: str) -> int:
    if not content:
        return 0
    return max(1, ceil(len(content) / 4))
