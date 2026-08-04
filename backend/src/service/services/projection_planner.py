"""Deterministic derived-index selection rules."""

from dataclasses import dataclass

from service.domain.enums import IndexType, MemoryStatus, MemoryType
from service.domain.models import LongTermMemory


@dataclass(frozen=True, slots=True)
class ProjectionPlanner:
    minimum_confidence: float = 0.6

    def plan(self, memory: LongTermMemory) -> tuple[IndexType, ...]:
        if (
            memory.status is not MemoryStatus.ACTIVE
            or memory.confidence < self.minimum_confidence
            or memory.staleness_score >= 1
        ):
            return ()

        selected = [IndexType.EXACT]
        if (
            memory.memory_type is MemoryType.PREFERENCE
            or memory.semantic_fingerprint is not None
        ):
            selected.append(IndexType.VECTOR)
        if self._has_stable_relations(memory):
            selected.append(IndexType.GRAPH)
        selected.append(IndexType.CACHE)
        return tuple(selected)

    @staticmethod
    def _has_stable_relations(memory: LongTermMemory) -> bool:
        relations = memory.type_payload.get("relations")
        if not isinstance(relations, list) or not relations:
            return False
        for relation in relations:
            if not isinstance(relation, dict):
                return False
            if not all(
                isinstance(relation.get(field), str) and relation[field]
                for field in ("subject", "predicate", "object")
            ):
                return False
        return True
