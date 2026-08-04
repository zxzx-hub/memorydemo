"""Transactional in-memory adapters used by unit tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from domain.enums import IndexStatus, IndexType
from domain.models import (
    AuditLog,
    Evidence,
    GovernanceCandidateState,
    LongTermCandidate,
    LongTermMemory,
    MemoryVersion,
    RawEvent,
    TaskCheckpoint,
    WorkingMemory,
)
from service.auth.tenant_context import TenantContext


@dataclass
class InMemoryWriteDatabase:
    events: dict[tuple[str, str], RawEvent] = field(default_factory=dict)
    idempotency: dict[tuple[str, str], str] = field(default_factory=dict)
    event_order: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    working_anchors: set[tuple[str, str]] = field(default_factory=set)
    cursors: dict[tuple[str, str], str | None] = field(default_factory=dict)
    evidence: dict[tuple[str, str], Evidence] = field(default_factory=dict)
    checkpoints: dict[tuple[str, str], TaskCheckpoint] = field(default_factory=dict)
    candidates: dict[tuple[str, str], LongTermCandidate] = field(default_factory=dict)
    outbox: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    candidate_outcomes: dict[tuple[str, str], GovernanceCandidateState] = field(
        default_factory=dict
    )
    long_term_memories: dict[tuple[str, str], LongTermMemory] = field(
        default_factory=dict
    )
    versions: dict[tuple[str, str, int], MemoryVersion] = field(default_factory=dict)
    projections: dict[
        tuple[str, str, int, IndexType],
        tuple[IndexStatus, str | None],
    ] = field(default_factory=dict)
    audits: dict[tuple[str, str], AuditLog] = field(default_factory=dict)
    usage: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    failure_on: str | None = None
    force_version_conflict: bool = False


class InMemoryWriteTransaction:
    def __init__(self, database: InMemoryWriteDatabase, ctx: TenantContext) -> None:
        self._database = database
        self._ctx = ctx
        self._state: InMemoryWriteDatabase | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._state = deepcopy(self._database)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self._state = None

    def _current(self, ctx: TenantContext) -> InMemoryWriteDatabase:
        if ctx != self._ctx or self._state is None:
            raise RuntimeError("Transaction TenantContext mismatch or not open.")
        return self._state

    async def save_event(
        self,
        ctx: TenantContext,
        workspace_id: str,
        idempotency_key: str,
        event: RawEvent,
    ) -> tuple[RawEvent, bool]:
        state = self._current(ctx)
        existing_event_id = state.idempotency.get((ctx.tenant_id, idempotency_key))
        if existing_event_id is not None:
            return state.events[(ctx.tenant_id, existing_event_id)], False
        key = (ctx.tenant_id, event.event_id)
        existing = state.events.get(key)
        if existing is not None:
            return existing, False
        state.events[key] = event
        state.idempotency[(ctx.tenant_id, idempotency_key)] = event.event_id
        state.event_order.setdefault(
            (ctx.tenant_id, workspace_id),
            [],
        ).append(event.event_id)
        return event, True

    async def ensure_working_memory(
        self,
        ctx: TenantContext,
        workspace_id: str,
        event: RawEvent,
    ) -> None:
        del event
        state = self._current(ctx)
        key = (ctx.tenant_id, workspace_id)
        state.working_anchors.add(key)
        state.cursors.setdefault(key, None)

    async def get_cursor_for_update(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> str | None:
        state = self._current(ctx)
        return state.cursors.setdefault((ctx.tenant_id, workspace_id), None)

    async def list_events_after(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor: str | None,
    ) -> Sequence[RawEvent]:
        state = self._current(ctx)
        order = state.event_order.get((ctx.tenant_id, workspace_id), [])
        start = order.index(cursor) + 1 if cursor in order else 0
        return tuple(
            state.events[(ctx.tenant_id, event_id)] for event_id in order[start:]
        )

    async def next_checkpoint_no(
        self,
        ctx: TenantContext,
        task_id: str,
    ) -> int:
        state = self._current(ctx)
        numbers = [
            item.checkpoint_no
            for (tenant_id, _), item in state.checkpoints.items()
            if tenant_id == ctx.tenant_id and item.task_id == task_id
        ]
        return max(numbers, default=0) + 1

    async def save_evidence(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[Evidence],
    ) -> None:
        del batch_id
        state = self._current(ctx)
        self._fail_if_requested(state, "evidence")
        for item in items:
            state.evidence.setdefault((ctx.tenant_id, item.evidence_id), item)

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: TaskCheckpoint | None,
    ) -> None:
        state = self._current(ctx)
        self._fail_if_requested(state, "checkpoint")
        if checkpoint is not None:
            state.checkpoints.setdefault(
                (ctx.tenant_id, checkpoint.checkpoint_id),
                checkpoint,
            )

    async def save_candidates(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[LongTermCandidate],
    ) -> None:
        del batch_id
        state = self._current(ctx)
        self._fail_if_requested(state, "candidate")
        for item in items:
            state.candidates.setdefault((ctx.tenant_id, item.candidate_id), item)

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor_before: str | None,
        cursor_after: str,
    ) -> None:
        state = self._current(ctx)
        key = (ctx.tenant_id, workspace_id)
        if state.cursors.get(key) != cursor_before:
            raise RuntimeError("Consolidation cursor changed concurrently.")
        state.cursors[key] = cursor_after

    async def add_outbox_job(
        self,
        ctx: TenantContext,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
    ) -> None:
        state = self._current(ctx)
        state.outbox.setdefault(
            (ctx.tenant_id, job_id),
            {"job_type": job_type, "payload": payload},
        )

    async def commit(self) -> None:
        if self._state is None:
            raise RuntimeError("Transaction is not open.")
        preserved_failure = self._database.failure_on
        committed = deepcopy(self._state)
        self._database.__dict__.update(committed.__dict__)
        self._database.failure_on = preserved_failure
        self._committed = True

    @staticmethod
    def _fail_if_requested(
        state: InMemoryWriteDatabase,
        stage: str,
    ) -> None:
        if state.failure_on == stage:
            raise RuntimeError(f"Injected {stage} persistence failure.")


class InMemoryWriteUnitOfWorkFactory:
    def __init__(self, database: InMemoryWriteDatabase) -> None:
        self.database = database

    def open(self, ctx: TenantContext) -> InMemoryWriteTransaction:
        return InMemoryWriteTransaction(self.database, ctx)


class InMemoryWorkingMemoryStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], WorkingMemory] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def get(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> WorkingMemory | None:
        return self._items.get((ctx.tenant_id, workspace_id))

    async def save(
        self,
        ctx: TenantContext,
        working_memory: WorkingMemory,
    ) -> None:
        self._items[(ctx.tenant_id, working_memory.workspace_id)] = working_memory

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        expected_cursor: str | None,
        new_cursor: str,
    ) -> bool:
        key = (ctx.tenant_id, workspace_id)
        working = self._items.get(key)
        if working is None:
            return False
        window = dict(working.conversation_window)
        if window.get("consolidated_until_event_id") != expected_cursor:
            return False
        window["consolidated_until_event_id"] = new_cursor
        self._items[key] = working.model_copy(update={"conversation_window": window})
        return True

    @asynccontextmanager
    async def lock(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> AsyncIterator[None]:
        lock = self._locks.setdefault(
            (ctx.tenant_id, workspace_id),
            asyncio.Lock(),
        )
        async with lock:
            yield
