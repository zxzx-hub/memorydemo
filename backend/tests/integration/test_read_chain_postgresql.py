"""PostgreSQL proof for tenant-scoped canonical rereads and usage."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from service.domain.commands import ReadMemoryRequest
from service.domain.enums import RetrievalMode
from service.infrastructure.db.models.memory import (
    LongTermMemoryModel,
    MemoryUsageStatsModel,
)
from service.infrastructure.db.repositories.retrieval import SqlAlchemyRetrievalStore
from service.infrastructure.memory import (
    InMemoryExactKeyStore,
    InMemoryGraphStore,
    InMemoryVectorStore,
)
from service.infrastructure.retrieval import DeterministicRetrievalPlanProvider
from service.services.context_compiler import DefaultContextCompiler
from service.services.retrieval_service import (
    DefaultRetrievalService,
    MetaPolicy,
    RetrievalRouter,
    RetrievalWeights,
)
from tests.fixtures.tenants import TestTenantResolver

pytestmark = pytest.mark.integration


class FixedClock:
    current = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


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


def database_memory(tenant_id: str, content: str) -> LongTermMemoryModel:
    return LongTermMemoryModel(
        tenant_id=tenant_id,
        memory_id="memory_read_shared",
        memory_type="FACT",
        owner_type="user",
        owner_id="user_shared",
        scope_type="user",
        scope_id="user_shared",
        status="active",
        version=1,
        content=content,
        normalized_key="fact.read.shared",
        content_hash=f"hash_{tenant_id}",
        language="en",
        type_payload={},
        confidence=0.9,
        importance=0.8,
        explicitness=0.9,
        valid_from=FixedClock.current - timedelta(days=1),
        evidence_ids=[],
        source_event_ids=[],
        conflict_ids=[],
    )


@pytest.mark.asyncio
async def test_postgresql_reread_and_usage_are_tenant_scoped(
    db_connection: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                database_memory("tenant_read_a", "A canonical content"),
                database_memory("tenant_read_b", "B canonical content"),
            ]
        )

    vector = InMemoryVectorStore()
    vector.default_results["tenant_read_a"] = ("memory_read_shared",)
    vector.default_results["tenant_read_b"] = ("memory_read_shared",)
    retrieval = DefaultRetrievalService(
        SqlAlchemyRetrievalStore(session_factory),
        InMemoryExactKeyStore(),
        vector,
        InMemoryGraphStore(),
        DeterministicRetrievalPlanProvider(),
        DefaultContextCompiler(),
        RetrievalRouter(),
        MetaPolicy(),
        RetrievalWeights(),
        FixedClock(),
    )
    resolver = TestTenantResolver()
    tenant_a = resolver.context(tenant_id="tenant_read_a")
    tenant_b = resolver.context(tenant_id="tenant_read_b")
    request = ReadMemoryRequest(
        mode=RetrievalMode.QUICK,
        query="shared",
    )

    result_a = await retrieval.retrieve(tenant_a, request)
    result_b = await retrieval.retrieve(tenant_b, request)

    assert result_a.context_package.facts[0].content == "A canonical content"
    assert result_b.context_package.facts[0].content == "B canonical content"
    async with session_factory() as session:
        usage = (
            await session.scalars(
                select(MemoryUsageStatsModel).where(
                    MemoryUsageStatsModel.tenant_id.in_(
                        ("tenant_read_a", "tenant_read_b")
                    )
                )
            )
        ).all()
    assert {(item.tenant_id, item.recall_count, item.use_count) for item in usage} == {
        ("tenant_read_a", 1, 1),
        ("tenant_read_b", 1, 1),
    }
