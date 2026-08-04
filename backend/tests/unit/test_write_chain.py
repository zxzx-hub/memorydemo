"""Complete in-memory write and Consolidate Once invariants."""

from datetime import UTC, datetime

import pytest

from domain.commands import (
    ConsolidateWriteRequest,
    EventInput,
    EventSignals,
    EventWriteRequest,
    PromoteCandidatesWriteRequest,
)
from domain.enums import ConsolidationReason
from infrastructure.consolidation import (
    DeterministicConsolidator,
    MockLLMConsolidator,
)
from infrastructure.memory import (
    InMemoryWorkingMemoryStore,
    InMemoryWriteDatabase,
    InMemoryWriteUnitOfWorkFactory,
)
from service.auth.tenant_context import TenantContext
from service.memory_facade import MemoryServiceFacade
from service.write.consolidate_once import ConsolidateOnceService
from service.write.consolidation_policy import ConsolidationPolicy


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def build_service(
    database: InMemoryWriteDatabase | None = None,
    consolidator: DeterministicConsolidator | None = None,
) -> tuple[
    MemoryServiceFacade,
    InMemoryWriteDatabase,
    InMemoryWorkingMemoryStore,
]:
    write_database = database or InMemoryWriteDatabase()
    factory = InMemoryWriteUnitOfWorkFactory(write_database)
    working_store = InMemoryWorkingMemoryStore()
    consolidate_once = ConsolidateOnceService(
        factory,
        working_store,
        consolidator or DeterministicConsolidator(),
    )
    service = MemoryServiceFacade(
        factory,
        working_store,
        consolidate_once,
        ConsolidationPolicy(
            message_count=100,
            token_ratio=0.9,
            idle_seconds=3600,
        ),
        FixedClock(),
    )
    return service, write_database, working_store


def event_request(
    *,
    event_id: str = "event_shared",
    idempotency_key: str = "idempotency_shared",
    content: str = "ordinary task message",
    signals: EventSignals | None = None,
) -> EventWriteRequest:
    return EventWriteRequest(
        idempotency_key=idempotency_key,
        workspace_id="workspace_shared",
        event=EventInput(
            event_id=event_id,
            event_type="user_message",
            role="user",
            content=content,
            source="api",
            session_id="session_shared",
            task_id="task_shared",
        ),
        signals=signals or EventSignals(),
    )


@pytest.mark.asyncio
async def test_duplicate_event_id_does_not_create_a_second_event(
    tenant_a: TenantContext,
) -> None:
    service, database, working_store = build_service()
    request = event_request()

    first = await service.write(tenant_a, request)
    second = await service.write(
        tenant_a,
        event_request(idempotency_key="another_key"),
    )
    working = await working_store.get(tenant_a, "workspace_shared")

    assert first.status == "created"
    assert second.status == "duplicate"
    assert len(database.events) == 1
    assert working is not None
    assert working.conversation_window["event_ids"] == ["event_shared"]
    assert working.conversation_window["message_count"] == 1


@pytest.mark.asyncio
async def test_duplicate_event_never_mutates_original_content_or_references(
    tenant_a: TenantContext,
) -> None:
    service, database, _ = build_service()
    original = event_request(content="immutable original content")
    original = original.model_copy(
        update={
            "event": original.event.model_copy(
                update={
                    "file_refs": ("file_original",),
                    "tool_result_refs": ("tool_original",),
                    "artifact_refs": ("artifact_original",),
                }
            )
        }
    )
    replacement = event_request(
        idempotency_key="replacement_idempotency_key",
        content="attempted replacement content",
    )

    await service.write(tenant_a, original)
    result = await service.write(tenant_a, replacement)

    persisted = database.events[("tenant_a", "event_shared")]
    assert result.status == "duplicate"
    assert persisted.content == "immutable original content"
    assert persisted.file_refs == ("file_original",)
    assert persisted.tool_result_refs == ("tool_original",)
    assert persisted.artifact_refs == ("artifact_original",)


@pytest.mark.asyncio
async def test_repeated_window_consolidation_is_idempotent(
    tenant_a: TenantContext,
) -> None:
    service, database, _ = build_service(consolidator=MockLLMConsolidator())
    await service.write(
        tenant_a,
        event_request(
            content=("以后给我讲技术方案时，先讲总体架构，再展开字段和代码。")
        ),
    )

    request = ConsolidateWriteRequest(
        workspace_id="workspace_shared",
        trigger=ConsolidationReason.MANUAL,
    )
    first = await service.write(tenant_a, request)
    second = await service.write(tenant_a, request)

    assert first.output.cursor_before is None
    assert first.output.cursor_after == "event_shared"
    assert len(first.output.evidence) == 1
    assert first.output.task_checkpoint is not None
    assert len(first.output.long_term_candidates) == 1
    assert second.output.idempotent is True
    assert second.output.evidence == ()
    assert len(database.checkpoints) == 1
    assert len(database.candidates) == 1
    assert len(database.evidence) == 1
    assert len(database.outbox) == 1

    candidate = first.output.long_term_candidates[0]
    assert candidate.memory_type.value == "PREFERENCE"
    assert candidate.content == "说明技术方案时，先给出总体架构，再展开字段和代码"
    assert candidate.normalized_key == "preference.solution_explanation_order"


@pytest.mark.parametrize("failure_stage", ["evidence", "checkpoint", "candidate"])
@pytest.mark.asyncio
async def test_sibling_failure_never_advances_cursor(
    tenant_a: TenantContext,
    failure_stage: str,
) -> None:
    service, database, _ = build_service()
    await service.write(tenant_a, event_request())
    database.failure_on = failure_stage

    with pytest.raises(RuntimeError, match=failure_stage):
        await service.write(
            tenant_a,
            ConsolidateWriteRequest(
                workspace_id="workspace_shared",
                trigger=ConsolidationReason.MANUAL,
            ),
        )

    assert database.cursors[("tenant_a", "workspace_shared")] is None
    assert database.evidence == {}
    assert database.checkpoints == {}
    assert database.candidates == {}
    assert len(database.events) == 1


@pytest.mark.asyncio
async def test_tenant_cursor_isolation_for_same_workspace_and_event_ids(
    tenant_a: TenantContext,
    tenant_b: TenantContext,
) -> None:
    service, database, _ = build_service()
    request = event_request()
    await service.write(tenant_a, request)
    await service.write(tenant_b, request)

    await service.write(
        tenant_a,
        ConsolidateWriteRequest(
            workspace_id="workspace_shared",
            trigger=ConsolidationReason.MANUAL,
        ),
    )

    assert database.cursors[("tenant_a", "workspace_shared")] == "event_shared"
    assert database.cursors[("tenant_b", "workspace_shared")] is None
    assert len(database.events) == 2


@pytest.mark.asyncio
async def test_candidate_sources_are_raw_events_not_short_term_memory(
    tenant_a: TenantContext,
) -> None:
    service, _, _ = build_service()
    await service.write(
        tenant_a,
        event_request(
            content=("以后给我讲技术方案时，先讲总体架构，再展开字段和代码。")
        ),
    )
    result = await service.write(
        tenant_a,
        ConsolidateWriteRequest(
            workspace_id="workspace_shared",
            trigger=ConsolidationReason.EXPLICIT_REMEMBER,
        ),
    )

    checkpoint = result.output.task_checkpoint
    candidate = result.output.long_term_candidates[0]
    assert checkpoint is not None
    assert candidate.source_kind == "raw_event"
    assert candidate.source_event_ids == ("event_shared",)
    assert checkpoint.checkpoint_id not in candidate.source_event_ids
    assert "resume_context" not in candidate.model_dump()


@pytest.mark.asyncio
async def test_promote_candidates_only_queues_governance(
    tenant_a: TenantContext,
) -> None:
    service, database, _ = build_service()

    result = await service.write(
        tenant_a,
        PromoteCandidatesWriteRequest(
            candidate_ids=("candidate_1",),
            idempotency_key="promote_1",
        ),
    )

    assert result.status == "queued"
    assert result.candidate_ids == ("candidate_1",)
    assert len(database.outbox) == 1
    assert database.candidates == {}


@pytest.mark.asyncio
async def test_thresholds_come_from_policy_configuration(
    tenant_a: TenantContext,
) -> None:
    database = InMemoryWriteDatabase()
    factory = InMemoryWriteUnitOfWorkFactory(database)
    store = InMemoryWorkingMemoryStore()
    consolidate = ConsolidateOnceService(
        factory,
        store,
        DeterministicConsolidator(),
    )
    service = MemoryServiceFacade(
        factory,
        store,
        consolidate,
        ConsolidationPolicy(message_count=1, token_ratio=0.99, idle_seconds=9999),
        FixedClock(),
    )

    result = await service.write(tenant_a, event_request())

    assert result.consolidation_reason == "message_count"
    assert result.consolidation is not None
    assert result.consolidation.cursor_after == "event_shared"
