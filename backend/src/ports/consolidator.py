"""Structured sibling extraction boundary for Consolidate Once."""

from collections.abc import Sequence
from typing import Protocol

from domain.models import (
    ConsolidateOnceOutput,
    ConsolidationTrigger,
    RawEvent,
    WorkingMemory,
)
from service.auth.tenant_context import TenantContext


class Consolidator(Protocol):
    async def consolidate(
        self,
        ctx: TenantContext,
        workspace_id: str,
        trigger: ConsolidationTrigger,
        events: Sequence[RawEvent],
        working_memory: WorkingMemory | None,
    ) -> ConsolidateOnceOutput:
        """Return schema-validated siblings sourced directly from raw events."""
