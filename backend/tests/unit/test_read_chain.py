"""Unified MemoryService.read and Context Package invariants."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from domain.commands import ReadMemoryRequest
from domain.enums import MemoryStatus, MemoryType, RetrievalMode
from domain.models import (
    Evidence,
    LongTermMemory,
    RetrievalPlan,
    Scope,
    TaskCheckpoint,
)
from infrastructure.consolidation import DeterministicConsolidator
from infrastructure.memory import (
    InMemoryExactKeyStore,
    InMemoryGraphStore,
    InMemoryRetrievalStore,
    InMemoryVectorStore,
    InMemoryWorkingMemoryStore,
    InMemoryWriteDatabase,
    InMemoryWriteUnitOfWorkFactory,
)
from service.auth.tenant_context import TenantContext
from service.core.errors import ResourceNotFoundError
from service.memory_facade import MemoryServiceFacade
from service.read.context_compiler import DefaultContextCompiler
from service.read.retrieval_service import (
    DefaultRetrievalService,
    MetaPolicy,
    RetrievalRouter,
    RetrievalWeights,
)
from service.write.consolidate_once import ConsolidateOnceService
from service.write.consolidation_policy import ConsolidationPolicy


class FixedClock:
    current = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


class CountingPlanProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def create_plan(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        recommended_mode: RetrievalMode,
    ) -> RetrievalPlan:
        del ctx
        self.calls += 1
        query = request.query or "planned"
        return RetrievalPlan(
            sub_queries=(query, f"{query} detail"),
            memory_types=request.memory_types,
            scopes=request.scope_filters,
            entities=("module_a",),
            relations=("depends_on", "affects"),
            time_range=request.time_range,
            need_evidence=request.need_evidence
            or recommended_mode is RetrievalMode.DEEP,
            recommended_mode=recommended_mode,
        )


def build_service() -> tuple[
    MemoryServiceFacade,
    InMemoryWriteDatabase,
    InMemoryExactKeyStore,
    InMemoryVectorStore,
    InMemoryGraphStore,
    CountingPlanProvider,
]:
    database = InMemoryWriteDatabase()
    write_factory = InMemoryWriteUnitOfWorkFactory(database)
    working_store = InMemoryWorkingMemoryStore()
    consolidate = ConsolidateOnceService(
        write_factory,
        working_store,
        DeterministicConsolidator(),
    )
    exact = InMemoryExactKeyStore()
    vector = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    planner = CountingPlanProvider()
    retrieval = DefaultRetrievalService(
        InMemoryRetrievalStore(database),
        exact,
        vector,
        graph,
        planner,
        DefaultContextCompiler(),
        RetrievalRouter(),
        MetaPolicy(),
        RetrievalWeights(),
        FixedClock(),
    )
    service = MemoryServiceFacade(
        write_factory,
        working_store,
        consolidate,
        ConsolidationPolicy(
            message_count=100,
            token_ratio=0.9,
            idle_seconds=3600,
        ),
        FixedClock(),
        retrieval,
    )
    return service, database, exact, vector, graph, planner


def memory(
    memory_id: str,
    *,
    memory_type: MemoryType = MemoryType.FACT,
    content: str = "persistent tenant memory",
    status: MemoryStatus = MemoryStatus.ACTIVE,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    scope_id: str = "user_shared",
    evidence_ids: tuple[str, ...] = (),
) -> LongTermMemory:
    return LongTermMemory(
        memory_id=memory_id,
        memory_type=memory_type,
        owner=Scope(type="user", id=scope_id),
        scope=Scope(type="user", id=scope_id),
        content=content,
        normalized_key=f"{memory_type.value.lower()}.{memory_id}",
        evidence_ids=evidence_ids,
        confidence=0.9,
        importance=0.8,
        explicitness=0.95,
        version=1,
        status=status,
        valid_from=valid_from or FixedClock.current - timedelta(days=1),
        valid_to=valid_to,
        content_hash=sha256(content.encode()).hexdigest(),
    )


def add_memory(
    database: InMemoryWriteDatabase,
    tenant_id: str,
    item: LongTermMemory,
) -> None:
    database.long_term_memories[(tenant_id, item.memory_id)] = item


def context_items(result: object) -> tuple[object, ...]:
    package = result.context_package  # type: ignore[attr-defined]
    return (
        *package.facts,
        *package.preferences,
        *package.constraints,
        *package.decisions,
        *package.progress,
    )


@pytest.mark.asyncio
async def test_meta_returns_only_tenant_control_information(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, planner = build_service()
    add_memory(database, "tenant_a", memory("memory_hidden"))

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.META,
            agent_id="agent_1",
            agent_role="planner",
        ),
    )

    assert result.mode == "meta"
    assert result.context_package.meta.principal_id == "user_shared"
    assert result.context_package.meta.agent_id == "agent_1"
    assert context_items(result) == ()
    assert planner.calls == vector.search_calls == graph.traverse_calls == 0


@pytest.mark.asyncio
async def test_resume_uses_tenant_and_task_for_latest_checkpoint(
    tenant_a: TenantContext,
    tenant_b: TenantContext,
) -> None:
    service, database, _, _, _, _ = build_service()
    for tenant_id, checkpoint_no, summary in (
        ("tenant_a", 1, "A old"),
        ("tenant_a", 2, "A latest"),
        ("tenant_b", 9, "B secret"),
    ):
        checkpoint = TaskCheckpoint(
            checkpoint_id=f"checkpoint_{tenant_id}_{checkpoint_no}",
            task_memory_id=f"task_memory_{tenant_id}",
            task_id="task_shared",
            checkpoint_no=checkpoint_no,
            source_from_event_id=f"event_{checkpoint_no}",
            source_to_event_id=f"event_{checkpoint_no}",
            source_event_ids=(f"event_{checkpoint_no}",),
            resume_context={"summary": summary},
        )
        database.checkpoints[(tenant_id, checkpoint.checkpoint_id)] = checkpoint

    result_a = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.RESUME, task_id="task_shared"),
    )
    result_b = await service.read(
        tenant_b,
        ReadMemoryRequest(mode=RetrievalMode.RESUME, task_id="task_shared"),
    )

    assert result_a.context_package.task_checkpoint is not None
    assert result_a.context_package.task_checkpoint.resume_context == {
        "summary": "A latest"
    }
    assert result_b.context_package.task_checkpoint is not None
    assert result_b.context_package.task_checkpoint.resume_context == {
        "summary": "B secret"
    }


@pytest.mark.asyncio
async def test_express_uses_known_id_without_llm_vector_or_graph(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, planner = build_service()
    add_memory(database, "tenant_a", memory("memory_express"))

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.EXPRESS,
            memory_id="memory_express",
        ),
    )

    assert [item.memory_id for item in context_items(result)] == ["memory_express"]
    assert planner.calls == vector.search_calls == graph.traverse_calls == 0


@pytest.mark.asyncio
async def test_express_supports_memory_key_and_type_normalized_key(
    tenant_a: TenantContext,
) -> None:
    service, database, exact, vector, graph, planner = build_service()
    item = memory(
        "memory_exact",
        memory_type=MemoryType.PREFERENCE,
    )
    item = item.model_copy(update={"normalized_key": "preference.exact"})
    add_memory(database, "tenant_a", item)
    exact.items[("tenant_a", "preference:exact")] = "memory_exact"

    by_key = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.EXPRESS,
            memory_key="preference:exact",
        ),
    )
    by_normalized_key = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.EXPRESS,
            normalized_key="preference.exact",
            memory_types=(MemoryType.PREFERENCE,),
        ),
    )

    assert by_key.context_package.preferences[0].memory_id == "memory_exact"
    assert by_normalized_key.context_package.preferences[0].memory_id == "memory_exact"
    assert exact.resolve_calls == 1
    assert planner.calls == vector.search_calls == graph.traverse_calls == 0


@pytest.mark.asyncio
async def test_express_cross_tenant_memory_id_returns_not_found(
    tenant_a: TenantContext,
) -> None:
    service, database, _, _, _, _ = build_service()
    add_memory(database, "tenant_b", memory("memory_private"))

    with pytest.raises(ResourceNotFoundError):
        await service.read(
            tenant_a,
            ReadMemoryRequest(
                mode=RetrievalMode.EXPRESS,
                memory_id="memory_private",
            ),
        )


@pytest.mark.asyncio
async def test_quick_uses_vector_without_complex_planner(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, planner = build_service()
    add_memory(database, "tenant_a", memory("memory_quick"))
    vector.results[("tenant_a", "ordinary question")] = ("memory_quick",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.QUICK,
            query="ordinary question",
        ),
    )

    assert [item.memory_id for item in context_items(result)] == ["memory_quick"]
    assert vector.search_calls == 1
    assert planner.calls == graph.traverse_calls == 0


@pytest.mark.asyncio
async def test_normal_uses_plan_multi_query_and_one_hop_graph(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, planner = build_service()
    add_memory(database, "tenant_a", memory("memory_vector"))
    add_memory(database, "tenant_a", memory("memory_graph"))
    vector.default_results["tenant_a"] = ("memory_vector",)
    graph.results["tenant_a"] = ("memory_graph",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.NORMAL,
            query="combine prior decisions",
        ),
    )

    assert {item.memory_id for item in context_items(result)} == {
        "memory_vector",
        "memory_graph",
    }
    assert planner.calls == 1
    assert vector.search_calls == 2
    assert graph.traverse_calls == 1
    assert graph.last_max_depth == 1


@pytest.mark.asyncio
async def test_deep_uses_multi_hop_graph_and_evidence(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, planner = build_service()
    add_memory(
        database,
        "tenant_a",
        memory("memory_deep", evidence_ids=("evidence_deep",)),
    )
    database.evidence[("tenant_a", "evidence_deep")] = Evidence(
        evidence_id="evidence_deep",
        source_event_ids=("event_deep",),
        source_from_event_id="event_deep",
        source_to_event_id="event_deep",
        excerpt="tenant A evidence",
    )
    vector.default_results["tenant_a"] = ("memory_deep",)
    graph.results["tenant_a"] = ("memory_deep",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.DEEP,
            query="why does module A affect module B",
            token_budget=100,
        ),
    )

    assert planner.calls == 1
    assert graph.last_max_depth == 3
    assert [item.evidence_id for item in result.context_package.evidence] == [
        "evidence_deep"
    ]


@pytest.mark.parametrize(
    ("read_request", "expected_mode"),
    [
        (ReadMemoryRequest(memory_id="known"), "express"),
        (ReadMemoryRequest(task_id="task_shared"), "resume"),
        (ReadMemoryRequest(query="ordinary preference"), "quick"),
        (ReadMemoryRequest(query="结合之前方案同时考虑限制"), "normal"),
        (ReadMemoryRequest(query="为什么这个决定影响模块 B"), "deep"),
    ],
)
@pytest.mark.asyncio
async def test_auto_routes_deterministically(
    tenant_a: TenantContext,
    read_request: ReadMemoryRequest,
    expected_mode: str,
) -> None:
    service, database, _, _, _, _ = build_service()
    if read_request.memory_id == "known":
        add_memory(database, "tenant_a", memory("known"))

    result = await service.read(tenant_a, read_request)

    assert result.mode == expected_mode


@pytest.mark.asyncio
async def test_context_package_groups_all_memory_types(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    ids = []
    for memory_type in MemoryType:
        memory_id = f"memory_{memory_type.value.lower()}"
        ids.append(memory_id)
        add_memory(
            database,
            "tenant_a",
            memory(memory_id, memory_type=memory_type),
        )
    vector.default_results["tenant_a"] = tuple(ids)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="all", top_k=10),
    )

    package = result.context_package
    assert len(package.facts) == 1
    assert len(package.preferences) == 1
    assert len(package.constraints) == 1
    assert len(package.decisions) == 1
    assert len(package.progress) == 1


@pytest.mark.asyncio
async def test_token_budget_excludes_items_that_do_not_fit(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    add_memory(
        database,
        "tenant_a",
        memory("memory_large", content="x" * 80),
    )
    vector.default_results["tenant_a"] = ("memory_large",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.QUICK,
            query="large",
            token_budget=5,
        ),
    )

    assert context_items(result) == ()
    assert result.context_package.excluded_memory_ids == ("memory_large",)
    assert result.context_package.token_usage.truncated is True
    assert database.usage[("tenant_a", "memory_large")]["recall_count"] == 1
    assert "use_count" not in database.usage[("tenant_a", "memory_large")]


@pytest.mark.asyncio
async def test_duplicate_recall_results_are_used_once(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, graph, _ = build_service()
    add_memory(database, "tenant_a", memory("memory_duplicate"))
    vector.default_results["tenant_a"] = (
        "memory_duplicate",
        "memory_duplicate",
    )
    graph.results["tenant_a"] = ("memory_duplicate",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.NORMAL, query="duplicate"),
    )

    assert [item.memory_id for item in context_items(result)] == ["memory_duplicate"]
    assert database.usage[("tenant_a", "memory_duplicate")]["use_count"] == 1


@pytest.mark.asyncio
async def test_expired_and_superseded_records_are_recalled_but_not_used(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    add_memory(
        database,
        "tenant_a",
        memory(
            "memory_expired",
            valid_to=FixedClock.current - timedelta(seconds=1),
        ),
    )
    add_memory(
        database,
        "tenant_a",
        memory("memory_superseded", status=MemoryStatus.SUPERSEDED),
    )
    vector.default_results["tenant_a"] = (
        "memory_expired",
        "memory_superseded",
    )

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="old"),
    )

    assert context_items(result) == ()
    for memory_id in ("memory_expired", "memory_superseded"):
        usage = database.usage[("tenant_a", memory_id)]
        assert usage["recall_count"] == 1
        assert "use_count" not in usage


@pytest.mark.asyncio
async def test_evidence_is_loaded_only_when_requested(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    add_memory(
        database,
        "tenant_a",
        memory("memory_evidence", evidence_ids=("evidence_1",)),
    )
    database.evidence[("tenant_a", "evidence_1")] = Evidence(
        evidence_id="evidence_1",
        source_event_ids=("event_1",),
        source_from_event_id="event_1",
        source_to_event_id="event_1",
        excerpt="safe excerpt",
    )
    vector.default_results["tenant_a"] = ("memory_evidence",)

    without = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="evidence"),
    )
    with_evidence = await service.read(
        tenant_a,
        ReadMemoryRequest(
            mode=RetrievalMode.QUICK,
            query="evidence",
            need_evidence=True,
        ),
    )

    assert without.context_package.evidence == ()
    assert len(with_evidence.context_package.evidence) == 1


@pytest.mark.asyncio
async def test_vector_cross_tenant_id_is_blocked_by_canonical_reread(
    tenant_a: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    add_memory(
        database,
        "tenant_b",
        memory("memory_cross", content="tenant B secret"),
    )
    vector.default_results["tenant_a"] = ("memory_cross",)

    result = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="malicious hit"),
    )

    assert context_items(result) == ()
    assert ("tenant_b", "memory_cross") not in database.usage


@pytest.mark.asyncio
async def test_same_memory_id_is_reread_from_each_tenant(
    tenant_a: TenantContext,
    tenant_b: TenantContext,
) -> None:
    service, database, _, vector, _, _ = build_service()
    add_memory(
        database,
        "tenant_a",
        memory("memory_shared", content="A content"),
    )
    add_memory(
        database,
        "tenant_b",
        memory("memory_shared", content="B content"),
    )
    vector.default_results["tenant_a"] = ("memory_shared",)
    vector.default_results["tenant_b"] = ("memory_shared",)

    result_a = await service.read(
        tenant_a,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="shared"),
    )
    result_b = await service.read(
        tenant_b,
        ReadMemoryRequest(mode=RetrievalMode.QUICK, query="shared"),
    )

    assert result_a.context_package.facts[0].content == "A content"
    assert result_b.context_package.facts[0].content == "B content"
