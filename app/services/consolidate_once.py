"""Atomic Consolidate Once orchestration."""

from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.models import (
    ConsolidateOnceOutput,
    ConsolidationTrigger,
    RawEvent,
    TaskCheckpoint,
)
from app.ports.consolidator import Consolidator
from app.ports.working_memory_store import WorkingMemoryStore
from app.ports.write_store import WriteTransaction, WriteUnitOfWorkFactory


class ConsolidateOnce(Protocol):
    async def execute(
        self,
        ctx: TenantContext,
        workspace_id: str,
        trigger: ConsolidationTrigger,
    ) -> ConsolidateOnceOutput:
        """Consolidate one current-tenant incremental event window."""


class ConsolidationValidationError(ValueError):
    """Raised before persistence when sibling output is not evidence-safe."""


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


class ConsolidateOnceService:
    """Persist Evidence, checkpoint and candidates before advancing the cursor."""

    def __init__(
        self,
        unit_of_work_factory: WriteUnitOfWorkFactory,
        working_memory_store: WorkingMemoryStore,
        consolidator: Consolidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._working_memory_store = working_memory_store
        self._consolidator = consolidator

    async def execute(
        self,
        ctx: TenantContext,
        workspace_id: str,
        trigger: ConsolidationTrigger,
    ) -> ConsolidateOnceOutput:
        async with self._working_memory_store.lock(ctx, workspace_id):
            working_memory = await self._working_memory_store.get(ctx, workspace_id)
            async with self._unit_of_work_factory.open(ctx) as transaction:
                cursor_before = await transaction.get_cursor_for_update(
                    ctx, workspace_id
                )
                events = tuple(
                    await transaction.list_events_after(
                        ctx,
                        workspace_id,
                        cursor_before,
                    )
                )
                if not events:
                    return ConsolidateOnceOutput(
                        cursor_before=cursor_before,
                        cursor_after=cursor_before,
                        idempotent=True,
                    )

                draft = await self._consolidator.consolidate(
                    ctx,
                    workspace_id,
                    trigger,
                    events,
                    working_memory,
                )
                self._validate(draft, events)
                cursor_after = events[-1].event_id
                batch_id = _stable_id(
                    "batch",
                    ctx.tenant_id,
                    workspace_id,
                    events[0].event_id,
                    cursor_after,
                )
                checkpoint = await self._number_checkpoint(
                    ctx,
                    transaction,
                    draft.task_checkpoint,
                )

                await transaction.save_evidence(ctx, batch_id, draft.evidence)
                await transaction.save_checkpoint(ctx, checkpoint)
                await transaction.save_candidates(
                    ctx,
                    batch_id,
                    draft.long_term_candidates,
                )
                await transaction.advance_cursor(
                    ctx,
                    workspace_id,
                    cursor_before,
                    cursor_after,
                )
                if draft.long_term_candidates:
                    await transaction.add_outbox_job(
                        ctx,
                        _stable_id("job", ctx.tenant_id, batch_id),
                        "govern_long_term_candidates",
                        {
                            "batch_id": batch_id,
                            "candidate_ids": [
                                item.candidate_id for item in draft.long_term_candidates
                            ],
                        },
                    )
                await transaction.commit()

            await self._working_memory_store.advance_cursor(
                ctx,
                workspace_id,
                cursor_before,
                cursor_after,
            )
            return ConsolidateOnceOutput(
                evidence=draft.evidence,
                task_checkpoint=checkpoint,
                long_term_candidates=draft.long_term_candidates,
                cursor_before=cursor_before,
                cursor_after=cursor_after,
            )

    @staticmethod
    async def _number_checkpoint(
        ctx: TenantContext,
        transaction: WriteTransaction,
        checkpoint: TaskCheckpoint | None,
    ) -> TaskCheckpoint | None:
        if checkpoint is None:
            return None
        next_number = await transaction.next_checkpoint_no(
            ctx,
            checkpoint.task_id,
        )
        return checkpoint.model_copy(update={"checkpoint_no": next_number})

    @staticmethod
    def _validate(
        output: ConsolidateOnceOutput,
        events: Sequence[RawEvent],
    ) -> None:
        event_ids = {event.event_id for event in events}
        evidence_ids = {item.evidence_id for item in output.evidence}
        for evidence in output.evidence:
            if not set(evidence.source_event_ids) <= event_ids:
                raise ConsolidationValidationError(
                    "Evidence references an event outside the frozen window."
                )
        for candidate in output.long_term_candidates:
            if candidate.source_kind != "raw_event":
                raise ConsolidationValidationError(
                    "Long-term candidates must come from raw events."
                )
            if not set(candidate.source_event_ids) <= event_ids:
                raise ConsolidationValidationError(
                    "Candidate references an event outside the frozen window."
                )
            if not set(candidate.evidence_ids) <= evidence_ids:
                raise ConsolidationValidationError(
                    "Candidate references evidence outside sibling output."
                )
        checkpoint = output.task_checkpoint
        if checkpoint is not None and not set(checkpoint.source_event_ids) <= event_ids:
            raise ConsolidationValidationError(
                "Checkpoint references an event outside the frozen window."
            )
