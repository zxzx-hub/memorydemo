"""Configuration-driven consolidation trigger evaluation."""

from dataclasses import dataclass

from domain.commands import EventSignals
from domain.enums import ConsolidationReason
from domain.models import WorkingMemory


@dataclass(frozen=True, slots=True)
class ConsolidationPolicy:
    message_count: int
    token_ratio: float
    idle_seconds: int

    def evaluate(
        self,
        working_memory: WorkingMemory,
        signals: EventSignals,
    ) -> ConsolidationReason | None:
        if signals.consolidation_reason is not None:
            return signals.consolidation_reason
        window = working_memory.conversation_window
        if int(window.get("message_count", 0)) >= self.message_count:
            return ConsolidationReason.MESSAGE_COUNT
        if (
            signals.token_usage_ratio is not None
            and signals.token_usage_ratio >= self.token_ratio
        ):
            return ConsolidationReason.TOKEN_RATIO
        if (
            signals.idle_seconds is not None
            and signals.idle_seconds >= self.idle_seconds
        ):
            return ConsolidationReason.IDLE_TIMEOUT
        return None
