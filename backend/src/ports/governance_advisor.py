"""Structured, non-authoritative governance suggestion boundary."""

from typing import Protocol

from domain.models import GovernanceSuggestion, LongTermCandidate
from service.auth.tenant_context import TenantContext


class GovernanceAdvisor(Protocol):
    async def suggest(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> GovernanceSuggestion:
        """Return a schema-validated suggestion without changing state."""
