"""Strict business request schemas; tenant identity is intentionally absent."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ConsolidationReason, MemoryType, RetrievalMode
from app.domain.models import ScopeFilter, TimeRange


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EventInput(Command):
    event_id: str | None = Field(default=None, min_length=1)
    event_type: str = Field(min_length=1)
    role: str = Field(min_length=1)
    content: str
    source: str = Field(min_length=1)
    session_id: str | None = None
    task_id: str | None = None
    created_at: datetime | None = None
    file_refs: tuple[str, ...] = ()
    tool_result_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()


class EventSignals(Command):
    token_usage_ratio: float | None = Field(default=None, ge=0, le=1)
    idle_seconds: float | None = Field(default=None, ge=0)
    consolidation_reason: ConsolidationReason | None = None


class EventWriteRequest(Command):
    type: Literal["event"] = "event"
    idempotency_key: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    event: EventInput
    signals: EventSignals = Field(default_factory=EventSignals)


class ConsolidateWriteRequest(Command):
    type: Literal["consolidate"] = "consolidate"
    workspace_id: str = Field(min_length=1)
    trigger: ConsolidationReason = ConsolidationReason.MANUAL


class PromoteCandidatesWriteRequest(Command):
    type: Literal["promote_candidates"] = "promote_candidates"
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


WriteRequest = Annotated[
    EventWriteRequest | ConsolidateWriteRequest | PromoteCandidatesWriteRequest,
    Field(discriminator="type"),
]


class ReadMemoryRequest(Command):
    mode: RetrievalMode = RetrievalMode.AUTO
    query: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    task_goal: str | None = None
    agent_id: str | None = None
    agent_role: str | None = None
    current_stage: str | None = None
    current_step: str | None = None
    memory_id: str | None = None
    memory_key: str | None = None
    normalized_key: str | None = None
    scope_filters: tuple[ScopeFilter, ...] = ()
    memory_types: tuple[MemoryType, ...] = ()
    time_range: TimeRange | None = None
    need_evidence: bool = False
    token_budget: int = Field(default=1200, ge=0, le=100_000)
    top_k: int = Field(default=8, ge=1, le=50)


ReadRequest = ReadMemoryRequest


class GcMemoryRequest(Command):
    action: Literal["evaluate", "expire", "archive", "delete"]
    memory_id: str | None = None
    reason_code: str | None = None
    idempotency_key: str = Field(min_length=1)
    dry_run: bool = False
