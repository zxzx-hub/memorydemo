"""Structured query-planning boundary for complex retrieval only."""

from typing import Protocol

from domain.commands import ReadMemoryRequest
from domain.enums import RetrievalMode
from domain.models import RetrievalPlan
from service.auth.tenant_context import TenantContext


class RetrievalPlanProvider(Protocol):
    async def create_plan(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        recommended_mode: RetrievalMode,
    ) -> RetrievalPlan:
        """Plan what to query without selecting final database records."""
