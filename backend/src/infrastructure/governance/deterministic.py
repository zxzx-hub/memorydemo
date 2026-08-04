"""Network-free governance suggestions used by default."""

from domain.enums import GovernanceAction
from domain.models import GovernanceSuggestion, LongTermCandidate
from service.auth.tenant_context import TenantContext


class DeterministicGovernanceAdvisor:
    """Normalize candidate suggestions without granting them write authority."""

    async def suggest(
        self,
        ctx: TenantContext,
        candidate: LongTermCandidate,
    ) -> GovernanceSuggestion:
        del ctx
        try:
            action = GovernanceAction(candidate.suggested_action.lower())
            reason = candidate.suggestion_reason or "candidate_suggestion"
            confidence = candidate.suggestion_confidence
            if confidence is None:
                confidence = candidate.confidence
        except ValueError:
            action = GovernanceAction.DEFER
            reason = "invalid_suggested_action"
            confidence = 0
        return GovernanceSuggestion(
            suggested_action=action,
            reason=reason,
            confidence=confidence,
            uncertainties=candidate.uncertainties,
            possible_duplicates=candidate.possible_duplicates,
            possible_conflicts=candidate.possible_conflicts,
        )
