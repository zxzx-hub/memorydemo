"""Strict service result schemas."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from service.domain.enums import (
    GovernanceAction,
    IndexStatus,
    IndexType,
    RetrievalMode,
)
from service.domain.models import (
    ConsolidateOnceOutput,
    ContextPackage,
    GovernanceChecks,
    RetrievalPlan,
)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EventWriteResult(Result):
    type: Literal["event"] = "event"
    operation_id: str
    event_id: str
    workspace_id: str
    status: str
    consolidation_reason: str | None = None
    consolidation: ConsolidateOnceOutput | None = None


class ConsolidateWriteResult(Result):
    type: Literal["consolidate"] = "consolidate"
    operation_id: str
    output: ConsolidateOnceOutput


class PromoteCandidatesWriteResult(Result):
    type: Literal["promote_candidates"] = "promote_candidates"
    operation_id: str
    candidate_ids: tuple[str, ...]
    status: str


WriteResult = Annotated[
    EventWriteResult | ConsolidateWriteResult | PromoteCandidatesWriteResult,
    Field(discriminator="type"),
]


class ReadMemoryResult(Result):
    mode: RetrievalMode
    retrieval_plan: RetrievalPlan | None = None
    context_package: ContextPackage


class GcMemoryResult(Result):
    operation_id: str
    status: str
    lifecycle_stage: str


class GovernanceResult(Result):
    candidate_id: str
    action: GovernanceAction
    status: str
    reason: str
    checks: GovernanceChecks
    memory_id: str | None = None
    version: int | None = None
    index_types: tuple[IndexType, ...] = ()
    idempotent: bool = False


class IndexProjectionResult(Result):
    memory_id: str
    version: int
    index_type: IndexType
    status: IndexStatus
    retryable: bool


ReadResult = ReadMemoryResult
