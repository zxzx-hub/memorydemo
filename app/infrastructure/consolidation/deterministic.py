"""Network-free structured sibling extraction."""

from collections.abc import Sequence
from hashlib import sha256

from app.auth.tenant_context import TenantContext
from app.domain.enums import MemoryType
from app.domain.models import (
    ConsolidateOnceOutput,
    ConsolidationTrigger,
    Evidence,
    LongTermCandidate,
    RawEvent,
    Scope,
    TaskCheckpoint,
    WorkingMemory,
)

_PREFERENCE_PHRASE = "以后给我讲技术方案时，先讲总体架构，再展开字段和代码"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


class DeterministicConsolidator:
    """Produce conservative siblings using deterministic extraction rules."""

    async def consolidate(
        self,
        ctx: TenantContext,
        workspace_id: str,
        trigger: ConsolidationTrigger,
        events: Sequence[RawEvent],
        working_memory: WorkingMemory | None,
    ) -> ConsolidateOnceOutput:
        del trigger, working_memory
        evidence = tuple(
            Evidence(
                evidence_id=_stable_id(
                    "evidence",
                    ctx.tenant_id,
                    workspace_id,
                    event.event_id,
                ),
                source_event_ids=(event.event_id,),
                source_from_event_id=event.event_id,
                source_to_event_id=event.event_id,
                excerpt=event.content,
            )
            for event in events
        )
        evidence_by_event = {
            item.source_event_ids[0]: item.evidence_id for item in evidence
        }
        candidates = tuple(
            self._preference_candidate(ctx, workspace_id, event, evidence_by_event)
            for event in events
            if _PREFERENCE_PHRASE in event.content.rstrip("。")
        )
        task_id = next(
            (event.task_id for event in reversed(events) if event.task_id),
            None,
        )
        checkpoint = (
            TaskCheckpoint(
                checkpoint_id=_stable_id(
                    "checkpoint",
                    ctx.tenant_id,
                    workspace_id,
                    events[0].event_id,
                    events[-1].event_id,
                ),
                task_memory_id=_stable_id(
                    "task_memory",
                    ctx.tenant_id,
                    task_id,
                ),
                task_id=task_id,
                checkpoint_no=1,
                source_from_event_id=events[0].event_id,
                source_to_event_id=events[-1].event_id,
                source_event_ids=tuple(event.event_id for event in events),
                resume_context={
                    "summary": "Task events were consolidated.",
                    "next_action": None,
                },
                intermediate_state={},
                open_questions=(),
            )
            if task_id is not None
            else None
        )
        return ConsolidateOnceOutput(
            evidence=evidence,
            task_checkpoint=checkpoint,
            long_term_candidates=candidates,
        )

    @staticmethod
    def _preference_candidate(
        ctx: TenantContext,
        workspace_id: str,
        event: RawEvent,
        evidence_by_event: dict[str, str],
    ) -> LongTermCandidate:
        return LongTermCandidate(
            candidate_id=_stable_id(
                "candidate",
                ctx.tenant_id,
                workspace_id,
                event.event_id,
                "preference.solution_explanation_order",
            ),
            memory_type=MemoryType.PREFERENCE,
            content="说明技术方案时，先给出总体架构，再展开字段和代码",
            normalized_key="preference.solution_explanation_order",
            scope=Scope(type="user", id=ctx.principal_id),
            evidence_ids=(evidence_by_event[event.event_id],),
            source_event_ids=(event.event_id,),
            confidence=1.0,
            importance=0.85,
            explicitness=1.0,
            semantic_fingerprint="preference:solution-explanation-order:v1",
        )


class MockLLMConsolidator(DeterministicConsolidator):
    """Deterministic mock of an LLM consolidator for tests and local demos."""
