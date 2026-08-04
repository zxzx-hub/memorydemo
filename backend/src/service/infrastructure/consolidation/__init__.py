"""Consolidator adapters."""

from service.infrastructure.consolidation.deterministic import (
    DeterministicConsolidator,
    MockLLMConsolidator,
)

__all__ = ["DeterministicConsolidator", "MockLLMConsolidator"]
