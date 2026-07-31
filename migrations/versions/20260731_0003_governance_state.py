"""Add candidate governance state and complete version snapshots.

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0003"
down_revision: str | None = "20260731_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    statements = (
        "ADD COLUMN IF NOT EXISTS sensitivity VARCHAR(64) "
        "NOT NULL DEFAULT 'none'",
        "ADD COLUMN IF NOT EXISTS language VARCHAR(32) "
        "NOT NULL DEFAULT 'und'",
        "ADD COLUMN IF NOT EXISTS type_payload JSONB "
        "NOT NULL DEFAULT '{}'::jsonb",
        "ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ",
        "ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ",
        "ADD COLUMN IF NOT EXISTS staleness_score DOUBLE PRECISION "
        "NOT NULL DEFAULT 0",
        "ADD COLUMN IF NOT EXISTS suggestion_reason VARCHAR(512)",
        "ADD COLUMN IF NOT EXISTS suggestion_confidence DOUBLE PRECISION",
        "ADD COLUMN IF NOT EXISTS uncertainties JSONB "
        "NOT NULL DEFAULT '[]'::jsonb",
        "ADD COLUMN IF NOT EXISTS possible_duplicates JSONB "
        "NOT NULL DEFAULT '[]'::jsonb",
        "ADD COLUMN IF NOT EXISTS possible_conflicts JSONB "
        "NOT NULL DEFAULT '[]'::jsonb",
        "ADD COLUMN IF NOT EXISTS governance_action VARCHAR(64)",
        "ADD COLUMN IF NOT EXISTS governance_reason VARCHAR(256)",
        "ADD COLUMN IF NOT EXISTS governed_memory_id VARCHAR(128)",
        "ADD COLUMN IF NOT EXISTS governed_memory_version INTEGER",
        "ADD COLUMN IF NOT EXISTS governed_at TIMESTAMPTZ",
    )
    for statement in statements:
        op.execute(f"ALTER TABLE memory_candidates {statement}")
    op.execute(
        "ALTER TABLE long_term_memory_versions "
        "ADD COLUMN IF NOT EXISTS snapshot JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_candidate_tenant_governed_memory'
          ) THEN
            ALTER TABLE memory_candidates
            ADD CONSTRAINT fk_candidate_tenant_governed_memory
            FOREIGN KEY (tenant_id, governed_memory_id)
            REFERENCES long_term_memory (tenant_id, memory_id);
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE memory_candidates "
        "DROP CONSTRAINT IF EXISTS fk_candidate_tenant_governed_memory"
    )
    op.execute(
        "ALTER TABLE long_term_memory_versions "
        "DROP COLUMN IF EXISTS snapshot"
    )
    for column in (
        "governed_at",
        "governed_memory_version",
        "governed_memory_id",
        "governance_reason",
        "governance_action",
        "possible_conflicts",
        "possible_duplicates",
        "uncertainties",
        "suggestion_confidence",
        "suggestion_reason",
        "staleness_score",
        "valid_to",
        "valid_from",
        "type_payload",
        "language",
        "sensitivity",
    ):
        op.execute(
            f"ALTER TABLE memory_candidates DROP COLUMN IF EXISTS {column}"
        )
