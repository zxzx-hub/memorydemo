"""Default MemoryService orchestration for the complete write chain."""

from hashlib import sha256

from service.auth.tenant_context import TenantContext
from service.core.clock import Clock
from service.core.errors import FeatureNotAvailableError
from service.core.ids import new_id
from domain.commands import (
    ConsolidateWriteRequest,
    EventWriteRequest,
    GcMemoryRequest,
    PromoteCandidatesWriteRequest,
    ReadMemoryRequest,
    WriteRequest,
)
from domain.models import (
    ConsolidationTrigger,
    RawEvent,
    WorkingMemory,
)
from domain.results import (
    ConsolidateWriteResult,
    EventWriteResult,
    GcMemoryResult,
    PromoteCandidatesWriteResult,
    ReadMemoryResult,
    WriteResult,
)
from ports.working_memory_store import WorkingMemoryStore
from ports.write_store import WriteUnitOfWorkFactory
from service.write.consolidate_once import ConsolidateOnce
from service.write.consolidation_policy import ConsolidationPolicy
from service.read.retrieval_service import DefaultRetrievalService


def _operation_id(ctx: TenantContext, value: str) -> str:
    digest = sha256(f"{ctx.tenant_id}\x1f{value}".encode()).hexdigest()[:32]
    return f"operation_{digest}"


class DefaultMemoryService:
    """Expose one write method while routing its three discriminated commands."""

    def __init__(
        self,
        unit_of_work_factory: WriteUnitOfWorkFactory,
        working_memory_store: WorkingMemoryStore,
        consolidate_once: ConsolidateOnce,
        consolidation_policy: ConsolidationPolicy,
        clock: Clock,
        retrieval_service: DefaultRetrievalService | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._working_memory_store = working_memory_store
        self._consolidate_once = consolidate_once
        self._consolidation_policy = consolidation_policy
        self._clock = clock
        self._retrieval_service = retrieval_service

    async def write(
        self,
        ctx: TenantContext,
        request: WriteRequest,
    ) -> WriteResult:
        if isinstance(request, EventWriteRequest):
            return await self._write_event(ctx, request)
        if isinstance(request, ConsolidateWriteRequest):
            return await self._consolidate(ctx, request)
        if isinstance(request, PromoteCandidatesWriteRequest):
            return await self._promote_candidates(ctx, request)
        raise TypeError("Unsupported WriteRequest variant.")

    async def read(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
    ) -> ReadMemoryResult:
        if self._retrieval_service is None:
            raise FeatureNotAvailableError
        return await self._retrieval_service.retrieve(ctx, request)

    async def gc(
        self,
        ctx: TenantContext,
        request: GcMemoryRequest,
    ) -> GcMemoryResult:
        del ctx, request
        raise FeatureNotAvailableError

    async def _write_event(
        self,
        ctx: TenantContext,
        request: EventWriteRequest,
    ) -> EventWriteResult:
        submitted = request.event
        event = RawEvent(
            event_id=submitted.event_id or new_id("event"),
            event_type=submitted.event_type,
            role=submitted.role,
            content=submitted.content,
            source=submitted.source,
            session_id=submitted.session_id,
            task_id=submitted.task_id,
            created_at=submitted.created_at or self._clock.now(),
            file_refs=submitted.file_refs,
            tool_result_refs=submitted.tool_result_refs,
            artifact_refs=submitted.artifact_refs,
        )
        async with self._unit_of_work_factory.open(ctx) as transaction:
            persisted, created = await transaction.save_event(
                ctx,
                request.workspace_id,
                request.idempotency_key,
                event,
            )
            await transaction.ensure_working_memory(
                ctx,
                request.workspace_id,
                persisted,
            )
            await transaction.commit()

        working_memory = await self._update_working_memory(
            ctx,
            request.workspace_id,
            persisted,
            request,
        )
        reason = self._consolidation_policy.evaluate(
            working_memory,
            request.signals,
        )
        consolidation = None
        if reason is not None:
            consolidation = await self._consolidate_once.execute(
                ctx,
                request.workspace_id,
                ConsolidationTrigger(
                    reason=reason,
                    requested_at=self._clock.now(),
                ),
            )
        return EventWriteResult(
            operation_id=_operation_id(ctx, request.idempotency_key),
            event_id=persisted.event_id,
            workspace_id=request.workspace_id,
            status="created" if created else "duplicate",
            consolidation_reason=reason.value if reason else None,
            consolidation=consolidation,
        )

    async def _update_working_memory(
        self,
        ctx: TenantContext,
        workspace_id: str,
        event: RawEvent,
        request: EventWriteRequest,
    ) -> WorkingMemory:
        current = await self._working_memory_store.get(ctx, workspace_id)
        if current is None:
            current = WorkingMemory(
                workspace_id=workspace_id,
                identity={
                    "tenant_id": ctx.tenant_id,
                    "workspace_id": workspace_id,
                    "principal_id": ctx.principal_id,
                    "session_id": event.session_id,
                    "task_id": event.task_id,
                    "trace_id": ctx.trace_id,
                },
                current_task_state={},
                conversation_window={
                    "event_ids": [],
                    "message_count": 0,
                    "consolidated_until_event_id": None,
                },
                tool_and_file_results={
                    "file_refs": [],
                    "tool_result_refs": [],
                    "artifact_refs": [],
                },
                immediate_instructions={"items": []},
                excluded_paths=(),
            )

        window = dict(current.conversation_window)
        event_ids = list(window.get("event_ids", []))
        is_new_to_window = event.event_id not in event_ids
        if is_new_to_window:
            event_ids.append(event.event_id)
        window["event_ids"] = event_ids
        if is_new_to_window and event.role == "user":
            window["message_count"] = int(window.get("message_count", 0)) + 1
        if request.signals.token_usage_ratio is not None:
            window["token_usage_ratio"] = request.signals.token_usage_ratio

        task_state = dict(current.current_task_state)
        task_state.update(
            {
                "task_id": event.task_id,
                "current_request_event_id": event.event_id,
                "status": "running",
            }
        )
        results = dict(current.tool_and_file_results)
        for name, values in (
            ("file_refs", event.file_refs),
            ("tool_result_refs", event.tool_result_refs),
            ("artifact_refs", event.artifact_refs),
        ):
            merged = list(results.get(name, []))
            for value in values:
                if value not in merged:
                    merged.append(value)
            results[name] = merged

        instructions = dict(current.immediate_instructions)
        instruction_items = list(instructions.get("items", []))
        if (
            request.signals.consolidation_reason is not None
            and request.signals.consolidation_reason.value == "explicit_remember"
            and event.content not in instruction_items
        ):
            instruction_items.append(event.content)
        instructions["items"] = instruction_items

        updated = current.model_copy(
            update={
                "current_task_state": task_state,
                "conversation_window": window,
                "tool_and_file_results": results,
                "immediate_instructions": instructions,
            }
        )
        await self._working_memory_store.save(ctx, updated)
        return updated

    async def _consolidate(
        self,
        ctx: TenantContext,
        request: ConsolidateWriteRequest,
    ) -> ConsolidateWriteResult:
        output = await self._consolidate_once.execute(
            ctx,
            request.workspace_id,
            ConsolidationTrigger(
                reason=request.trigger,
                requested_at=self._clock.now(),
            ),
        )
        return ConsolidateWriteResult(
            operation_id=_operation_id(
                ctx,
                f"{request.workspace_id}:{request.trigger.value}:{output.cursor_after}",
            ),
            output=output,
        )

    async def _promote_candidates(
        self,
        ctx: TenantContext,
        request: PromoteCandidatesWriteRequest,
    ) -> PromoteCandidatesWriteResult:
        job_id = _operation_id(ctx, request.idempotency_key).replace(
            "operation_",
            "job_",
        )
        async with self._unit_of_work_factory.open(ctx) as transaction:
            await transaction.add_outbox_job(
                ctx,
                job_id,
                "govern_long_term_candidates",
                {"candidate_ids": list(request.candidate_ids)},
            )
            await transaction.commit()
        return PromoteCandidatesWriteResult(
            operation_id=_operation_id(ctx, request.idempotency_key),
            candidate_ids=request.candidate_ids,
            status="queued",
        )
