"""Tenant-safe retrieval orchestration for every read mode."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.auth.tenant_context import TenantContext
from app.core.clock import Clock
from app.core.errors import ResourceNotFoundError
from app.domain.commands import ReadMemoryRequest
from app.domain.enums import MemoryStatus, MemoryType, RetrievalMode
from app.domain.models import (
    ContextMeta,
    ContextPackage,
    LongTermMemory,
    RankedMemory,
    RetrievalHit,
    RetrievalPlan,
    ScopeFilter,
    TaskCheckpointView,
)
from app.domain.results import ReadMemoryResult
from app.ports.exact_key_store import ExactKeyStore
from app.ports.graph_store import GraphStore
from app.ports.retrieval_plan_provider import RetrievalPlanProvider
from app.ports.retrieval_store import RetrievalStore
from app.ports.vector_store import VectorStore
from app.services.context_compiler import DefaultContextCompiler


@dataclass(frozen=True, slots=True)
class RetrievalWeights:
    semantic_relevance: float = 0.35
    confidence: float = 0.15
    importance: float = 0.15
    explicitness: float = 0.10
    freshness: float = 0.10
    retrieval_weight: float = 0.05
    scope_match: float = 0.10
    freshness_half_life_days: float = 180


class RetrievalRouter:
    _DEEP_TERMS = (
        "原因",
        "为什么",
        "影响",
        "依赖",
        "关系链",
        "多跳",
        "why",
        "impact",
        "depend",
    )
    _NORMAL_TERMS = ("结合", "同时", "并且", "以及", "分别", "compare")

    def route(self, request: ReadMemoryRequest) -> RetrievalMode:
        if request.mode is not RetrievalMode.AUTO:
            return request.mode
        if (
            request.memory_id is not None
            or request.memory_key is not None
            or (request.normalized_key is not None and len(request.memory_types) == 1)
        ):
            return RetrievalMode.EXPRESS
        if request.task_id is not None and not request.query:
            return RetrievalMode.RESUME
        query = (request.query or "").lower()
        if any(term in query for term in self._DEEP_TERMS):
            return RetrievalMode.DEEP
        if (
            any(term in query for term in self._NORMAL_TERMS)
            or len(request.scope_filters) > 1
            or len(request.memory_types) > 1
            or request.time_range is not None
        ):
            return RetrievalMode.NORMAL
        return RetrievalMode.QUICK


class MetaPolicy:
    """Build tenant-internal controls without trusting scopes as authorization."""

    _MEMORY_TYPES = tuple(MemoryType)

    def build(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        mode: RetrievalMode,
    ) -> ContextMeta:
        allowed = [ScopeFilter(type="user", id=ctx.principal_id)]
        if request.workspace_id is not None:
            allowed.append(ScopeFilter(type="workspace", id=request.workspace_id))
        if request.agent_id is not None:
            allowed.append(ScopeFilter(type="agent", id=request.agent_id))

        requested_types = request.memory_types or self._MEMORY_TYPES
        return ContextMeta(
            principal_id=ctx.principal_id,
            agent_id=request.agent_id,
            agent_role=request.agent_role,
            agent_permissions=("memory:read", "memory:resume"),
            allowed_scopes=tuple(allowed),
            allowed_memory_types=tuple(requested_types),
            retrieval_mode=mode,
            token_budget=request.token_budget,
            top_k=request.top_k,
            system_limits=(
                "tenant_scoped_only",
                "active_and_valid_canonical_only",
                "derived_indexes_return_ids_only",
            ),
        )


class DefaultRetrievalService:
    def __init__(
        self,
        store: RetrievalStore,
        exact_key_store: ExactKeyStore,
        vector_store: VectorStore,
        graph_store: GraphStore,
        plan_provider: RetrievalPlanProvider,
        context_compiler: DefaultContextCompiler,
        router: RetrievalRouter,
        meta_policy: MetaPolicy,
        weights: RetrievalWeights,
        clock: Clock,
    ) -> None:
        self._store = store
        self._exact_key_store = exact_key_store
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._plan_provider = plan_provider
        self._context_compiler = context_compiler
        self._router = router
        self._meta_policy = meta_policy
        self._weights = weights
        self._clock = clock

    async def retrieve(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
    ) -> ReadMemoryResult:
        mode = self._router.route(request)
        meta = self._meta_policy.build(ctx, request, mode)
        if mode is RetrievalMode.META:
            package = self._context_compiler.empty(meta)
            return ReadMemoryResult(
                mode=mode,
                context_package=package,
            )
        if mode is RetrievalMode.RESUME:
            checkpoint = await self._resume(ctx, request)
            package = self._context_compiler.empty(
                meta,
                task_checkpoint=checkpoint,
            )
            return ReadMemoryResult(
                mode=mode,
                context_package=package,
            )

        plan = None
        if mode in (RetrievalMode.NORMAL, RetrievalMode.DEEP):
            plan = await self._plan_provider.create_plan(
                ctx,
                request,
                mode,
            )
        hits = await self._recall(ctx, request, mode, plan)
        package = await self._build_package(
            ctx,
            request,
            meta,
            hits,
            plan,
        )
        return ReadMemoryResult(
            mode=mode,
            retrieval_plan=plan,
            context_package=package,
        )

    async def _resume(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
    ) -> TaskCheckpointView | None:
        if request.task_id is None:
            return None
        return await self._store.latest_checkpoint(
            ctx,
            request.task_id,
            self._clock.now(),
        )

    async def _recall(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        mode: RetrievalMode,
        plan: RetrievalPlan | None,
    ) -> tuple[RetrievalHit, ...]:
        if mode is RetrievalMode.EXPRESS:
            return await self._express(ctx, request)

        query = request.query or request.task_goal or ""
        queries: tuple[str, ...] = (query,)
        if plan is not None and plan.sub_queries:
            queries = plan.sub_queries
        hits = []
        for sub_query in queries:
            ids = await self._vector_store.search(
                ctx,
                sub_query,
                request.top_k,
            )
            hits.extend(self._ranked_hits(ids, "vector", base=1.0))

        if (
            mode in (RetrievalMode.NORMAL, RetrievalMode.DEEP)
            and request.normalized_key is not None
            and len(request.memory_types) == 1
        ):
            exact_id = await self._store.resolve_normalized_key(
                ctx,
                request.memory_types[0],
                request.normalized_key,
                request.scope_filters,
            )
            if exact_id is not None:
                hits.append(
                    RetrievalHit(
                        memory_id=exact_id,
                        relevance=1,
                        matched_reason="exact_filter",
                    )
                )

        if (
            mode in (RetrievalMode.NORMAL, RetrievalMode.DEEP)
            and plan is not None
            and (plan.entities or plan.relations)
        ):
            graph_ids = await self._graph_store.traverse(
                ctx,
                plan.entities,
                plan.relations,
                max_depth=3 if mode is RetrievalMode.DEEP else 1,
            )
            hits.extend(self._ranked_hits(graph_ids, "graph", base=0.85))
        return self._deduplicate_hits(hits)

    async def _express(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
    ) -> tuple[RetrievalHit, ...]:
        memory_id = request.memory_id
        reason = "memory_id"
        if memory_id is None and request.memory_key is not None:
            memory_id = await self._exact_key_store.resolve(
                ctx,
                request.memory_key,
            )
            reason = "memory_key"
        if (
            memory_id is None
            and request.normalized_key is not None
            and len(request.memory_types) == 1
        ):
            memory_id = await self._store.resolve_normalized_key(
                ctx,
                request.memory_types[0],
                request.normalized_key,
                request.scope_filters,
            )
            reason = "type_and_normalized_key"
        if memory_id is None:
            return ()
        return (
            RetrievalHit(
                memory_id=memory_id,
                relevance=1,
                matched_reason=reason,
            ),
        )

    async def _build_package(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        meta: ContextMeta,
        hits: Sequence[RetrievalHit],
        plan: RetrievalPlan | None,
    ) -> ContextPackage:
        now = self._clock.now()
        recalled_ids = []
        excluded = []
        ranked = []
        for hit in hits:
            record = await self._store.get_for_recall(ctx, hit.memory_id)
            if record is None:
                excluded.append(hit.memory_id)
                continue
            recalled_ids.append(record.memory.memory_id)
            if not self._is_allowed(record.memory, request, meta, now):
                excluded.append(record.memory.memory_id)
                continue
            ranked.append(
                RankedMemory(
                    memory=record.memory,
                    score=self._score(
                        record.memory,
                        record.retrieval_weight,
                        hit.relevance,
                        request.scope_filters,
                        now,
                    ),
                    matched_reason=hit.matched_reason,
                )
            )

        await self._store.mark_recalled(ctx, _unique(recalled_ids), now)
        ranked.sort(key=lambda item: (-item.score, item.memory.memory_id))
        need_evidence = request.need_evidence or (
            plan is not None and plan.need_evidence
        )
        compiled = await self._context_compiler.compile(
            ctx,
            meta,
            ranked,
            tuple(dict.fromkeys(excluded)),
            request.top_k,
            request.token_budget,
            need_evidence,
            self._store,
        )
        if meta.retrieval_mode is RetrievalMode.EXPRESS and not ranked:
            raise ResourceNotFoundError
        await self._store.mark_used(ctx, compiled.used_memory_ids, now)
        return compiled.package

    @staticmethod
    def _is_allowed(
        memory: LongTermMemory,
        request: ReadMemoryRequest,
        meta: ContextMeta,
        now: datetime,
    ) -> bool:
        if memory.status is not MemoryStatus.ACTIVE:
            return False
        if memory.valid_from > now:
            return False
        if memory.valid_to is not None and memory.valid_to <= now:
            return False
        if memory.memory_type not in meta.allowed_memory_types:
            return False
        allowed_scopes = {(scope.type, scope.id) for scope in meta.allowed_scopes}
        if (memory.scope.type, memory.scope.id) not in allowed_scopes:
            return False
        if request.scope_filters and (
            memory.scope.type,
            memory.scope.id,
        ) not in {(scope.type, scope.id) for scope in request.scope_filters}:
            return False
        time_range = request.time_range
        if time_range is not None:
            if time_range.start is not None and memory.valid_from < time_range.start:
                return False
            if time_range.end is not None and memory.valid_from > time_range.end:
                return False
        return True

    def _score(
        self,
        memory: LongTermMemory,
        retrieval_weight: float,
        relevance: float,
        requested_scopes: Sequence[ScopeFilter],
        now: datetime,
    ) -> float:
        age_days = max((now - memory.valid_from).total_seconds() / 86400, 0)
        freshness = 1 / (1 + age_days / self._weights.freshness_half_life_days)
        scope_match = 1.0
        if requested_scopes:
            scope_match = float(
                any(
                    memory.scope.type == scope.type and memory.scope.id == scope.id
                    for scope in requested_scopes
                )
            )
        return (
            relevance * self._weights.semantic_relevance
            + memory.confidence * self._weights.confidence
            + memory.importance * self._weights.importance
            + memory.explicitness * self._weights.explicitness
            + freshness * self._weights.freshness
            + min(retrieval_weight, 1) * self._weights.retrieval_weight
            + scope_match * self._weights.scope_match
        )

    @staticmethod
    def _ranked_hits(
        memory_ids: Sequence[str],
        reason: str,
        *,
        base: float,
    ) -> list[RetrievalHit]:
        denominator = max(len(memory_ids), 1)
        return [
            RetrievalHit(
                memory_id=memory_id,
                relevance=max(base - index / denominator * 0.25, 0),
                matched_reason=reason,
            )
            for index, memory_id in enumerate(memory_ids)
        ]

    @staticmethod
    def _deduplicate_hits(
        hits: Iterable[RetrievalHit],
    ) -> tuple[RetrievalHit, ...]:
        best: dict[str, RetrievalHit] = {}
        for hit in hits:
            current = best.get(hit.memory_id)
            if current is None or hit.relevance > current.relevance:
                best[hit.memory_id] = hit
        return tuple(best.values())


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
