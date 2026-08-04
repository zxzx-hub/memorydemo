"""Network-free structured query planning for local operation."""

import re

from service.auth.tenant_context import TenantContext
from service.domain.commands import ReadMemoryRequest
from service.domain.enums import RetrievalMode
from service.domain.models import RetrievalPlan


class DeterministicRetrievalPlanProvider:
    async def create_plan(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        recommended_mode: RetrievalMode,
    ) -> RetrievalPlan:
        del ctx
        query = request.query or request.task_goal or ""
        parts = tuple(
            part.strip()
            for part in re.split(r"[\uFF0C,\uFF1B;]|并且|同时|以及", query)
            if part.strip()
        )
        if not parts and query:
            parts = (query,)
        relations: tuple[str, ...] = ()
        if recommended_mode is RetrievalMode.DEEP:
            relations = ("depends_on", "causes", "affects")
        return RetrievalPlan(
            sub_queries=parts,
            memory_types=request.memory_types,
            scopes=request.scope_filters,
            entities=(),
            relations=relations,
            time_range=request.time_range,
            need_evidence=request.need_evidence
            or recommended_mode is RetrievalMode.DEEP,
            recommended_mode=recommended_mode,
        )
