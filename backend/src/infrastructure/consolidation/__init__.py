"""Consolidator adapters."""

from infrastructure.consolidation.deterministic import (
    DeterministicConsolidator,
    MockLLMConsolidator,
)

__all__ = ["DeterministicConsolidator", "MockLLMConsolidator"]
