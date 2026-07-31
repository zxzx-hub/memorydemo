"""Structured, non-authoritative governance suggestion boundary."""

from typing import Protocol

from app.auth.tenant_context import TenantContext
from app.domain.models import GovernanceSuggestion, LongTermCandidate


class GovernanceAdvisor(Protocol):
    async def suggest(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> GovernanceSuggestion:
        """Return a schema-validated suggestion without changing state."""
