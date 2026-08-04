"""PostgreSQL proof for the atomic write and Consolidate Once path."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    async_sessionmaker,
    create_async_engine,
)

from domain.commands import (
    ConsolidateWriteRequest,
    EventInput,
    EventWriteRequest,
)
from domain.enums import ConsolidationReason
from infrastructure.consolidation import DeterministicConsolidator
from infrastructure.db.models.memory import (
    ConsolidationCursorModel,
    MemoryCandidateModel,
    MemoryEventModel,
    MemoryEvidenceModel,
    OutboxJobModel,
    TaskCheckpointModel,
)
from infrastructure.db.repositories.write import (
    SqlAlchemyWriteUnitOfWorkFactory,
)
from infrastructure.memory import InMemoryWorkingMemoryStore
from service.write.consolidate_once import ConsolidateOnceService
from service.write.consolidation_policy import ConsolidationPolicy
from service.memory_facade import MemoryServiceFacade
from tests.fixtures.tenants import TestTenantResolver

pytestmark = pytest.mark.integration


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
async def db_connection() -> AsyncConnection:
    database_url = os.getenv(
        "MEMORY_TEST_DATABASE_URL",
        "postgresql+asyncpg://memory:memory@localhost:5432/memory",
    )
    engine = create_async_engine(
        database_url,
        connect_args={"timeout": 1},
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                if transaction.is_active:
                    await transaction.rollback()
    except OSError as error:
        pytest.skip(f"PostgreSQL integration service unavailable: {error}")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_write_chain_commits_one_sibling_set_and_cursor(
    db_connection: AsyncConnection,
) -> None:
    ctx = TestTenantResolver().context(
        tenant_id="tenant_write_integration",
        principal_id="principal_write_integration",
        trace_id="trace_write_integration",
    )
    session_factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    write_factory = SqlAlchemyWriteUnitOfWorkFactory(session_factory)
    working_store = InMemoryWorkingMemoryStore()
    consolidate_once = ConsolidateOnceService(
        write_factory,
        working_store,
        DeterministicConsolidator(),
    )
    service = MemoryServiceFacade(
        write_factory,
        working_store,
        consolidate_once,
        ConsolidationPolicy(
            message_count=100,
            token_ratio=0.9,
            idle_seconds=3600,
        ),
        FixedClock(),
    )

    event_result = await service.write(
        ctx,
        EventWriteRequest(
            idempotency_key="write_integration_1",
            workspace_id="workspace_write_integration",
            event=EventInput(
                event_id="event_write_integration",
                event_type="user_message",
                role="user",
                content=("以后给我讲技术方案时，先讲总体架构，再展开字段和代码。"),
                source="integration_test",
                session_id="session_write_integration",
                task_id="task_write_integration",
            ),
        ),
    )
    consolidation_request = ConsolidateWriteRequest(
        workspace_id="workspace_write_integration",
        trigger=ConsolidationReason.MANUAL,
    )
    first = await service.write(ctx, consolidation_request)
    repeated = await service.write(ctx, consolidation_request)

    assert event_result.status == "created"
    assert first.output.cursor_after == "event_write_integration"
    assert len(first.output.evidence) == 1
    assert first.output.task_checkpoint is not None
    assert len(first.output.long_term_candidates) == 1
    assert repeated.output.idempotent is True

    async with session_factory() as session:
        tenant_filter = "tenant_write_integration"
        counts = {}
        for name, model in (
            ("events", MemoryEventModel),
            ("evidence", MemoryEvidenceModel),
            ("checkpoints", TaskCheckpointModel),
            ("candidates", MemoryCandidateModel),
            ("outbox", OutboxJobModel),
        ):
            counts[name] = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant_filter)
            )
        cursor = await session.scalar(
            select(ConsolidationCursorModel).where(
                ConsolidationCursorModel.tenant_id == tenant_filter,
                ConsolidationCursorModel.workspace_id == "workspace_write_integration",
            )
        )

    assert counts == {
        "events": 1,
        "evidence": 1,
        "checkpoints": 1,
        "candidates": 1,
        "outbox": 1,
    }
    assert cursor is not None
    assert cursor.consolidated_until_event_id == "event_write_integration"
