"""Structured query-planning boundary for complex retrieval only."""

from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.commands import ReadMemoryRequest
from app.domain.enums import RetrievalMode
from app.domain.models import RetrievalPlan


class RetrievalPlanProvider(Protocol):
    async def create_plan(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        recommended_mode: RetrievalMode,
    ) -> RetrievalPlan:
        """Plan what to query without selecting final database records."""
