"""Schema-validating LLM retrieval-plan adapter with deterministic fallback."""

from pydantic import ValidationError

from app.auth.tenant_context import TenantContext
from app.domain.commands import ReadMemoryRequest
from app.domain.enums import RetrievalMode
from app.domain.models import RetrievalPlan
from app.ports.llm_client import LLMClient
from app.ports.retrieval_plan_provider import RetrievalPlanProvider


class LLMRetrievalPlanProvider:
    def __init__(
        self,
        llm_client: LLMClient,
        fallback: RetrievalPlanProvider,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback

    async def create_plan(
        self,
        ctx: TenantContext,
        request: ReadMemoryRequest,
        recommended_mode: RetrievalMode,
    ) -> RetrievalPlan:
        response = await self._llm_client.generate(
            prompt_name="retrieval_plan",
            payload={
                "query": request.query,
                "task_goal": request.task_goal,
                "agent_role": request.agent_role,
                "current_stage": request.current_stage,
                "current_step": request.current_step,
                "scope_filters": [
                    scope.model_dump() for scope in request.scope_filters
                ],
                "memory_types": [
                    memory_type.value for memory_type in request.memory_types
                ],
                "time_range": (
                    request.time_range.model_dump(mode="json")
                    if request.time_range is not None
                    else None
                ),
                "need_evidence": request.need_evidence,
                "recommended_mode": recommended_mode.value,
            },
        )
        try:
            plan = RetrievalPlan.model_validate(response)
        except ValidationError:
            return await self._fallback.create_plan(
                ctx,
                request,
                recommended_mode,
            )
        if plan.recommended_mode is not recommended_mode:
            plan = plan.model_copy(update={"recommended_mode": recommended_mode})
        return plan
