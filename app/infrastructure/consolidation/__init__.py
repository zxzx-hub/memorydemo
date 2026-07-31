"""Consolidator adapters."""

from app.infrastructure.consolidation.deterministic import (
    DeterministicConsolidator,
    MockLLMConsolidator,
)

__all__ = ["DeterministicConsolidator", "MockLLMConsolidator"]
