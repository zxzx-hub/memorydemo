"""Transport-independent domain value objects for the service skeleton."""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.enums import (
    ConsolidationReason,
    GovernanceAction,
    IndexStatus,
    IndexType,
    MemoryStatus,
    MemoryType,
    RetrievalMode,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(DomainModel):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class ScopeFilter(DomainModel):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class TimeRange(DomainModel):
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("TimeRange.start must not be after TimeRange.end.")
        return self


class RawEvent(DomainModel):
    event_id: str
    event_type: str
    role: str
    content: str
    source: str
    session_id: str | None = None
    task_id: str | None = None
    created_at: datetime
    file_refs: tuple[str, ...] = ()
    tool_result_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()


class WorkingMemory(DomainModel):
    workspace_id: str
    identity: dict[str, Any] = Field(default_factory=dict)
    current_task_state: dict[str, Any] = Field(default_factory=dict)
    conversation_window: dict[str, Any] = Field(default_factory=dict)
    tool_and_file_results: dict[str, Any] = Field(default_factory=dict)
    immediate_instructions: dict[str, Any] = Field(default_factory=dict)
    excluded_paths: tuple[dict[str, Any], ...] = ()


class TaskMemory(DomainModel):
    task_memory_id: str
    task_id: str
    status: str
    expires_at: datetime | None = None


class TaskCheckpoint(DomainModel):
    checkpoint_id: str
    task_memory_id: str
    task_id: str
    checkpoint_no: int = Field(ge=1)
    source_from_event_id: str
    source_to_event_id: str
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    resume_context: dict[str, Any] = Field(default_factory=dict)
    intermediate_state: dict[str, Any] = Field(default_factory=dict)
    open_questions: tuple[dict[str, Any], ...] = ()


class Evidence(DomainModel):
    evidence_id: str
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    source_from_event_id: str
    source_to_event_id: str
    excerpt: str | None = None


class LongTermCandidate(DomainModel):
    candidate_id: str
    memory_type: MemoryType
    content: str = Field(min_length=1)
    normalized_key: str
    scope: Scope
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    explicitness: float = Field(default=0.5, ge=0, le=1)
    semantic_fingerprint: str | None = None
    suggested_action: str = "CREATE"
    source_kind: Literal["raw_event"] = "raw_event"
    owner: Scope | None = None
    sensitivity: Literal["none", "internal", "sensitive", "restricted"] = "none"
    language: str = "und"
    type_payload: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    staleness_score: float = Field(default=0, ge=0, le=1)
    suggestion_reason: str | None = None
    suggestion_confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainties: tuple[str, ...] = ()
    possible_duplicates: tuple[str, ...] = ()
    possible_conflicts: tuple[str, ...] = ()


class ConsolidateOnceOutput(DomainModel):
    evidence: tuple[Evidence, ...] = ()
    task_checkpoint: TaskCheckpoint | None = None
    long_term_candidates: tuple[LongTermCandidate, ...] = ()
    cursor_before: str | None = None
    cursor_after: str | None = None
    idempotent: bool = False


class LongTermMemory(DomainModel):
    memory_id: str
    memory_type: MemoryType
    owner: Scope
    scope: Scope
    content: str
    normalized_key: str
    evidence_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    explicitness: float = Field(ge=0, le=1)
    version: int = Field(ge=1)
    status: MemoryStatus
    valid_from: datetime
    valid_to: datetime | None = None
    type_payload: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    source_event_ids: tuple[str, ...] = ()
    semantic_fingerprint: str | None = None
    language: str = "und"
    last_verified_at: datetime | None = None
    review_at: datetime | None = None
    staleness_score: float = Field(default=0, ge=0, le=1)
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    duplicate_of_id: str | None = None
    merged_into_id: str | None = None
    conflict_ids: tuple[str, ...] = ()
    reference_count: int = Field(default=0, ge=0)


class MemoryVersion(DomainModel):
    memory_id: str
    version: int = Field(ge=1)
    content_hash: str
    operation: str
    created_at: datetime
    snapshot: dict[str, Any] = Field(default_factory=dict)


class GovernanceSuggestion(DomainModel):
    suggested_action: GovernanceAction
    reason: str
    confidence: float = Field(ge=0, le=1)
    uncertainties: tuple[str, ...] = ()
    possible_duplicates: tuple[str, ...] = ()
    possible_conflicts: tuple[str, ...] = ()


class GovernanceChecks(DomainModel):
    schema_valid: bool
    evidence_valid: bool
    future_value: float = Field(ge=0, le=1)
    explicitness: float = Field(ge=0, le=1)
    sensitivity: str
    scope_valid: bool
    exact_duplicate_id: str | None = None
    semantic_duplicate_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    validity_valid: bool
    staleness_score: float = Field(ge=0, le=1)
    active_version: int | None = None


class GovernanceCandidateState(DomainModel):
    candidate: LongTermCandidate
    governance_status: str
    governance_action: GovernanceAction | None = None
    governance_reason: str | None = None
    governed_memory_id: str | None = None
    governed_memory_version: int | None = None


class MemoryUsageStats(DomainModel):
    memory_id: str
    recall_count: int = Field(default=0, ge=0)
    use_count: int = Field(default=0, ge=0)
    retrieval_weight: float = Field(default=1, ge=0)
    last_recalled_at: datetime | None = None
    last_used_at: datetime | None = None


class MemoryLifecycleState(DomainModel):
    memory_id: str
    pinned: bool = False
    protected: bool = False
    reference_count: int = Field(default=0, ge=0)
    eviction_eligible: bool = True
    legal_hold: bool = False


class MemoryDeletionRequest(DomainModel):
    deletion_request_id: str
    memory_id: str
    reason_code: str
    requested_at: datetime
    stage: str


class MemoryIndexProjection(DomainModel):
    memory_id: str
    version: int = Field(ge=1)
    index_type: IndexType
    index_status: IndexStatus
    index_ref: str | None = None


class ContextMeta(DomainModel):
    principal_id: str
    agent_id: str | None = None
    agent_role: str | None = None
    agent_permissions: tuple[str, ...] = ()
    allowed_scopes: tuple[ScopeFilter, ...] = ()
    allowed_memory_types: tuple[MemoryType, ...] = ()
    retrieval_mode: RetrievalMode
    token_budget: int = Field(ge=0)
    top_k: int = Field(ge=1)
    system_limits: tuple[str, ...] = ()


class TaskCheckpointView(DomainModel):
    checkpoint_id: str
    task_id: str
    checkpoint_no: int = Field(ge=1)
    status: str
    current_stage: str | None = None
    resume_context: dict[str, Any] = Field(default_factory=dict)
    intermediate_state: dict[str, Any] = Field(default_factory=dict)
    next_actions: tuple[str, ...] = ()
    open_questions: tuple[dict[str, Any], ...] = ()
    source_event_ids: tuple[str, ...] = ()
    expires_at: datetime | None = None


class MemoryContextItem(DomainModel):
    memory_id: str
    memory_type: MemoryType
    content: str
    confidence: float = Field(ge=0, le=1)
    scope: Scope
    version: int = Field(ge=1)
    matched_reason: str
    evidence_ids: tuple[str, ...] = ()


class EvidenceExcerpt(DomainModel):
    evidence_id: str
    excerpt: str | None = None
    source_event_ids: tuple[str, ...] = ()


class TokenUsage(DomainModel):
    budget: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)
    truncated: bool = False


class ContextPackage(DomainModel):
    meta: ContextMeta
    task_checkpoint: TaskCheckpointView | None = None
    facts: tuple[MemoryContextItem, ...] = ()
    preferences: tuple[MemoryContextItem, ...] = ()
    constraints: tuple[MemoryContextItem, ...] = ()
    decisions: tuple[MemoryContextItem, ...] = ()
    progress: tuple[MemoryContextItem, ...] = ()
    evidence: tuple[EvidenceExcerpt, ...] = ()
    excluded_memory_ids: tuple[str, ...] = ()
    token_usage: TokenUsage


class RetrievalPlan(DomainModel):
    sub_queries: tuple[str, ...] = ()
    memory_types: tuple[MemoryType, ...] = ()
    scopes: tuple[ScopeFilter, ...] = ()
    entities: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    time_range: TimeRange | None = None
    need_evidence: bool = False
    recommended_mode: RetrievalMode


class RetrievalHit(DomainModel):
    memory_id: str
    relevance: float = Field(ge=0, le=1)
    matched_reason: str


class RetrievalRecord(DomainModel):
    memory: LongTermMemory
    retrieval_weight: float = Field(default=1, ge=0)


class RankedMemory(DomainModel):
    memory: LongTermMemory
    score: float
    matched_reason: str


class AuditLog(DomainModel):
    audit_id: str
    operation: str
    result: str
    principal_id: str
    trace_id: str
    target_hash: str | None = None
    reason_code: str | None = None


class ConsolidationTrigger(DomainModel):
    reason: ConsolidationReason
    requested_at: datetime
