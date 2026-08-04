"""Static proofs for tenant-scoped database constraints."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from infrastructure.db import models as memory_models
from infrastructure.db.base import Base

_ = memory_models

EXPECTED_TABLES = {
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
}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_all_required_tables_are_mapped() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_required_primary_and_unique_keys_are_tenant_scoped() -> None:
    working = Base.metadata.tables["working_memory"]
    long_term = Base.metadata.tables["long_term_memory"]

    assert tuple(column.name for column in working.primary_key.columns) == (
        "tenant_id",
        "workspace_id",
    )
    assert tuple(column.name for column in long_term.primary_key.columns) == (
        "tenant_id",
        "memory_id",
    )
    assert (
        "tenant_id",
        "task_id",
        "checkpoint_no",
    ) in _unique_column_sets("task_checkpoints")
    assert (
        "tenant_id",
        "scope_type",
        "scope_id",
        "memory_type",
        "normalized_key",
    ) in _unique_column_sets("long_term_memory")


def test_every_foreign_key_contains_tenant_on_both_sides() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            local_columns = {column.name for column in constraint.columns}
            remote_columns = {element.column.name for element in constraint.elements}
            assert "tenant_id" in local_columns, table.name
            assert "tenant_id" in remote_columns, table.name


def test_usage_and_lifecycle_are_separate_from_canonical_content() -> None:
    long_term_columns = {
        column.name for column in Base.metadata.tables["long_term_memory"].columns
    }
    usage_columns = {
        column.name for column in Base.metadata.tables["memory_usage_stats"].columns
    }
    lifecycle_columns = {
        column.name for column in Base.metadata.tables["memory_lifecycle_state"].columns
    }

    assert "recall_count" not in long_term_columns
    assert "use_count" not in long_term_columns
    assert {"recall_count", "use_count", "retrieval_weight"} <= usage_columns
    assert {"pinned", "protected", "eviction_eligible"} <= lifecycle_columns


def test_vector_and_graph_records_have_tenant_identity() -> None:
    vector = Base.metadata.tables["memory_vector_indexes"]
    node = Base.metadata.tables["memory_graph_nodes"]
    edge = Base.metadata.tables["memory_graph_edges"]

    vector_columns = {column.name for column in vector.columns}
    assert {"tenant_id", "memory_id", "version", "metadata"} <= vector_columns
    assert "tenant_id" in node.columns
    assert "tenant_id" in edge.columns
