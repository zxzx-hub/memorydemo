"""Transactional persistence boundary for the complete write chain."""

from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from service.auth.tenant_context import TenantContext
from service.domain.models import (
    Evidence,
    LongTermCandidate,
    RawEvent,
    TaskCheckpoint,
)


class WriteTransaction(Protocol):
    async def __aenter__(self) -> Self:
        """Open a write transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back unless commit completed."""

    async def save_event(
        self,
        ctx: TenantContext,
        workspace_id: str,
        idempotency_key: str,
        event: RawEvent,
    ) -> tuple[RawEvent, bool]:
        """Save an immutable event, returning (event, created)."""

    async def ensure_working_memory(
        self,
        ctx: TenantContext,
        workspace_id: str,
        event: RawEvent,
    ) -> None:
        """Ensure the tenant-scoped relational workspace anchor exists."""

    async def get_cursor_for_update(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> str | None:
        """Lock and return the current consolidation cursor."""

    async def list_events_after(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor: str | None,
    ) -> Sequence[RawEvent]:
        """Return ordered current-tenant events after the cursor."""

    async def next_checkpoint_no(
        self,
        ctx: TenantContext,
        task_id: str,
    ) -> int:
        """Return the next tenant + task checkpoint number."""

    async def save_evidence(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[Evidence],
    ) -> None:
        """Persist Evidence siblings idempotently."""

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: TaskCheckpoint | None,
    ) -> None:
        """Persist the optional TaskCheckpoint sibling idempotently."""

    async def save_candidates(
        self,
        ctx: TenantContext,
        batch_id: str,
        items: Sequence[LongTermCandidate],
    ) -> None:
        """Persist candidate siblings without promoting them."""

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        cursor_before: str | None,
        cursor_after: str,
    ) -> None:
        """Advance the cursor only from the expected value."""

    async def add_outbox_job(
        self,
        ctx: TenantContext,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
    ) -> None:
        """Insert a tenant-bound Outbox job in the same transaction."""

    async def commit(self) -> None:
        """Atomically commit every write in this transaction."""


class WriteUnitOfWorkFactory(Protocol):
    def open(self, ctx: TenantContext) -> WriteTransaction:
        """Create a transaction frozen to the supplied TenantContext."""
