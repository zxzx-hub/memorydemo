"""Tenant-scoped SQLAlchemy models for the Agent Memory domain."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base

ID = String(128)
KIND = String(64)
JSON_EMPTY_ARRAY = text("'[]'::jsonb")
JSON_EMPTY_OBJECT = text("'{}'::jsonb")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MemoryEventModel(Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_memory_events_tenant_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_sequence",
            name="uq_memory_events_tenant_sequence",
        ),
        Index(
            "ix_memory_events_tenant_workspace_created",
            "tenant_id",
            "workspace_id",
            "created_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    event_sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(ID, nullable=False)
    event_type: Mapped[str] = mapped_column(KIND, nullable=False)
    role: Mapped[str] = mapped_column(KIND, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ID)
    task_id: Mapped[str | None] = mapped_column(ID)
    principal_id: Mapped[str] = mapped_column(ID, nullable=False)
    trace_id: Mapped[str] = mapped_column(ID, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(ID, nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=JSON_EMPTY_ARRAY,
    )
    file_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=JSON_EMPTY_ARRAY,
    )
    tool_result_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=JSON_EMPTY_ARRAY,
    )
    artifact_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=JSON_EMPTY_ARRAY,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WorkingMemoryModel(TimestampMixin, Base):
    __tablename__ = "working_memory"

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ID)
    session_id: Mapped[str | None] = mapped_column(ID)
    task_id: Mapped[str | None] = mapped_column(ID)
    agent_id: Mapped[str | None] = mapped_column(ID)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=JSON_EMPTY_OBJECT,
    )
    consolidated_until_event_id: Mapped[str | None] = mapped_column(ID)


class TaskMemoryModel(TimestampMixin, Base):
    __tablename__ = "task_memory"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "task_id",
            name="uq_task_memory_tenant_task",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    task_memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    task_id: Mapped[str] = mapped_column(ID, nullable=False)
    status: Mapped[str] = mapped_column(KIND, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_checkpoint_no: Mapped[int | None] = mapped_column(Integer)


class TaskCheckpointModel(TimestampMixin, Base):
    __tablename__ = "task_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_memory_id"],
            ["task_memory.tenant_id", "task_memory.task_memory_id"],
            name="fk_task_checkpoints_tenant_task_memory",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "task_id",
            "checkpoint_no",
            name="uq_task_checkpoints_tenant_task_number",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(ID, primary_key=True)
    task_memory_id: Mapped[str] = mapped_column(ID, nullable=False)
    task_id: Mapped[str] = mapped_column(ID, nullable=False)
    checkpoint_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(KIND, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_stage: Mapped[str | None] = mapped_column(String(256))
    completed_steps: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    next_actions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    active_constraints: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    resume_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    intermediate_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    open_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    artifact_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    file_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    tool_result_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_from_event_id: Mapped[str] = mapped_column(ID, nullable=False)
    source_to_event_id: Mapped[str] = mapped_column(ID, nullable=False)


class MemoryEvidenceModel(Base):
    __tablename__ = "memory_evidence"
    __table_args__ = (
        Index(
            "ix_memory_evidence_tenant_window",
            "tenant_id",
            "source_from_event_id",
            "source_to_event_id",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ID, primary_key=True)
    consolidation_batch_id: Mapped[str] = mapped_column(ID, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_from_event_id: Mapped[str] = mapped_column(ID, nullable=False)
    source_to_event_id: Mapped[str] = mapped_column(ID, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryCandidateModel(Base):
    __tablename__ = "memory_candidates"
    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('FACT','PREFERENCE','CONSTRAINT','DECISION','PROGRESS')",
            name="memory_candidate_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "governed_memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_candidate_tenant_governed_memory",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ID, primary_key=True)
    consolidation_batch_id: Mapped[str] = mapped_column(ID, nullable=False)
    memory_type: Mapped[str] = mapped_column(KIND, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(512), nullable=False)
    scope_type: Mapped[str] = mapped_column(KIND, nullable=False)
    scope_id: Mapped[str] = mapped_column(ID, nullable=False)
    owner_type: Mapped[str] = mapped_column(KIND, nullable=False)
    owner_id: Mapped[str] = mapped_column(ID, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    explicitness: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(256))
    suggested_action: Mapped[str | None] = mapped_column(KIND)
    sensitivity: Mapped[str] = mapped_column(
        KIND, nullable=False, server_default="none"
    )
    language: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="und"
    )
    type_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staleness_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    suggestion_reason: Mapped[str | None] = mapped_column(String(512))
    suggestion_confidence: Mapped[float | None] = mapped_column(Float)
    uncertainties: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    possible_duplicates: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    possible_conflicts: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    governance_status: Mapped[str] = mapped_column(
        KIND, nullable=False, server_default="pending"
    )
    governance_action: Mapped[str | None] = mapped_column(KIND)
    governance_reason: Mapped[str | None] = mapped_column(String(256))
    governed_memory_id: Mapped[str | None] = mapped_column(ID)
    governed_memory_version: Mapped[int | None] = mapped_column(Integer)
    governed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LongTermMemoryModel(TimestampMixin, Base):
    __tablename__ = "long_term_memory"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope_type",
            "scope_id",
            "memory_type",
            "normalized_key",
            name="uq_ltm_tenant_scope_type_key",
        ),
        CheckConstraint(
            "memory_type IN ('FACT','PREFERENCE','CONSTRAINT','DECISION','PROGRESS')",
            name="long_term_memory_type",
        ),
        CheckConstraint(
            "status IN "
            "('active','superseded','archived','pending_delete','tombstoned')",
            name="long_term_memory_status",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_ltm_tenant_supersedes",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "superseded_by_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_ltm_tenant_superseded_by",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "duplicate_of_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_ltm_tenant_duplicate",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "merged_into_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_ltm_tenant_merged",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_type: Mapped[str] = mapped_column(KIND, nullable=False)
    owner_type: Mapped[str] = mapped_column(KIND, nullable=False)
    owner_id: Mapped[str] = mapped_column(ID, nullable=False)
    scope_type: Mapped[str] = mapped_column(KIND, nullable=False)
    scope_id: Mapped[str] = mapped_column(ID, nullable=False)
    status: Mapped[str] = mapped_column(KIND, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(256))
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    type_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    explicitness: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staleness_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    source_event_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    supersedes_id: Mapped[str | None] = mapped_column(ID)
    superseded_by_id: Mapped[str | None] = mapped_column(ID)
    duplicate_of_id: Mapped[str | None] = mapped_column(ID)
    merged_into_id: Mapped[str | None] = mapped_column(ID)
    conflict_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    reference_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )


class LongTermMemoryVersionModel(Base):
    __tablename__ = "long_term_memory_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_ltm_versions_tenant_memory",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(KIND, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    type_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_ARRAY
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryUsageStatsModel(Base):
    __tablename__ = "memory_usage_stats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_usage_tenant_memory",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    last_recalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recall_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    last_corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    decay_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    retrieval_weight: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="1"
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryLifecycleStateModel(Base):
    __tablename__ = "memory_lifecycle_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_lifecycle_tenant_memory",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    payload_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    index_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    retention_class: Mapped[str] = mapped_column(
        KIND, nullable=False, server_default="standard"
    )
    eviction_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    eviction_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    legal_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantMemoryQuotaModel(Base):
    __tablename__ = "tenant_memory_quota"

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    quota_scope: Mapped[str] = mapped_column(KIND, primary_key=True)
    scope_id: Mapped[str] = mapped_column(ID, primary_key=True)
    max_record_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_record_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    max_storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    high_watermark: Mapped[float] = mapped_column(Float, nullable=False)
    low_watermark: Mapped[float] = mapped_column(Float, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryDeletionRequestModel(TimestampMixin, Base):
    __tablename__ = "memory_deletion_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_deletion_tenant_memory",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    deletion_request_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, nullable=False)
    requested_by: Mapped[str] = mapped_column(ID, nullable=False)
    reason_code: Mapped[str] = mapped_column(KIND, nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_status: Mapped[str] = mapped_column(
        KIND, nullable=False, server_default="pending"
    )
    purge_job_id: Mapped[str | None] = mapped_column(ID)


class MemoryIndexProjectionModel(Base):
    __tablename__ = "memory_index_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id", "version"],
            [
                "long_term_memory_versions.tenant_id",
                "long_term_memory_versions.memory_id",
                "long_term_memory_versions.version",
            ],
            name="fk_projection_tenant_memory_version",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_type: Mapped[str] = mapped_column(KIND, primary_key=True)
    index_ref: Mapped[str | None] = mapped_column(String(512))
    index_status: Mapped[str] = mapped_column(KIND, nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryExactKeyModel(Base):
    __tablename__ = "memory_exact_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id", "version"],
            [
                "long_term_memory_versions.tenant_id",
                "long_term_memory_versions.memory_id",
                "long_term_memory_versions.version",
            ],
            name="fk_exact_tenant_memory_version",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "memory_key",
            name="uq_exact_tenant_memory_key",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryVectorIndexModel(Base):
    __tablename__ = "memory_vector_indexes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id", "version"],
            [
                "long_term_memory_versions.tenant_id",
                "long_term_memory_versions.memory_id",
                "long_term_memory_versions.version",
            ],
            name="fk_vector_tenant_memory_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(metadata ->> 'tenant_id') = tenant_id "
            "AND (metadata ->> 'memory_id') = memory_id "
            "AND (metadata ->> 'version') = version::text",
            name="vector_metadata_identity",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    vector_kind: Mapped[str] = mapped_column(KIND, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    index_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryGraphNodeModel(Base):
    __tablename__ = "memory_graph_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_graph_node_tenant_memory",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_type",
            "normalized_key",
            name="uq_graph_node_tenant_type_key",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    node_id: Mapped[str] = mapped_column(ID, primary_key=True)
    memory_id: Mapped[str | None] = mapped_column(ID)
    node_type: Mapped[str] = mapped_column(KIND, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(512), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryGraphEdgeModel(Base):
    __tablename__ = "memory_graph_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_node_id"],
            ["memory_graph_nodes.tenant_id", "memory_graph_nodes.node_id"],
            name="fk_graph_edge_tenant_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_node_id"],
            ["memory_graph_nodes.tenant_id", "memory_graph_nodes.node_id"],
            name="fk_graph_edge_tenant_target",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["long_term_memory.tenant_id", "long_term_memory.memory_id"],
            name="fk_graph_edge_tenant_memory",
            ondelete="CASCADE",
        ),
        Index(
            "ix_graph_edges_tenant_source_relation",
            "tenant_id",
            "source_node_id",
            "relation_type",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    edge_id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_node_id: Mapped[str] = mapped_column(ID, nullable=False)
    target_node_id: Mapped[str] = mapped_column(ID, nullable=False)
    memory_id: Mapped[str | None] = mapped_column(ID)
    relation_type: Mapped[str] = mapped_column(KIND, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=JSON_EMPTY_OBJECT
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryAuditLogModel(Base):
    __tablename__ = "memory_audit_logs"
    __table_args__ = (
        Index(
            "ix_audit_tenant_operation_created",
            "tenant_id",
            "operation",
            "created_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    audit_id: Mapped[str] = mapped_column(ID, primary_key=True)
    operation: Mapped[str] = mapped_column(KIND, nullable=False)
    result: Mapped[str] = mapped_column(KIND, nullable=False)
    principal_id: Mapped[str] = mapped_column(ID, nullable=False)
    trace_id: Mapped[str] = mapped_column(ID, nullable=False)
    target_hash: Mapped[str | None] = mapped_column(String(256))
    reject_reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConsolidationCursorModel(TimestampMixin, Base):
    __tablename__ = "consolidation_cursors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["working_memory.tenant_id", "working_memory.workspace_id"],
            name="fk_cursor_tenant_workspace",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ID, primary_key=True)
    consolidated_until_event_id: Mapped[str | None] = mapped_column(ID)
    batch_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )


class OutboxJobModel(TimestampMixin, Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        Index(
            "ix_outbox_tenant_status_available",
            "tenant_id",
            "status",
            "available_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(ID, primary_key=True)
    job_id: Mapped[str] = mapped_column(ID, primary_key=True)
    job_type: Mapped[str] = mapped_column(KIND, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(KIND, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
