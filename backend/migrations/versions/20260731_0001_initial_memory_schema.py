"""Create the initial tenant-scoped Agent Memory schema.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

from service.infrastructure.db import models as memory_models
from service.infrastructure.db.base import Base

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ = memory_models

_TABLE_NAMES = (
    "memory_events",
    "working_memory",
    "task_memory",
    "task_checkpoints",
    "memory_evidence",
    "memory_candidates",
    "long_term_memory",
    "long_term_memory_versions",
    "memory_usage_stats",
    "memory_lifecycle_state",
    "tenant_memory_quota",
    "memory_deletion_requests",
    "memory_index_projections",
    "memory_exact_keys",
    "memory_vector_indexes",
    "memory_graph_nodes",
    "memory_graph_edges",
    "memory_audit_logs",
    "consolidation_cursors",
    "outbox_jobs",
)


def _schema_tables() -> list[object]:
    return [Base.metadata.tables[name] for name in _TABLE_NAMES]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=_schema_tables(),
        checkfirst=False,
    )


def downgrade() -> None:
    Base.metadata.drop_all(
        bind=op.get_bind(),
        tables=list(reversed(_schema_tables())),
        checkfirst=False,
    )
