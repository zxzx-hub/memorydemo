"""PostgreSQL proof that equal business IDs remain tenant-isolated."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from infrastructure.db.models.memory import (
    LongTermMemoryModel,
    TaskMemoryModel,
)
from infrastructure.db.repositories.long_term_memory import (
    SqlAlchemyLongTermMemoryRepository,
)
from service.auth.tenant_context import TenantContext
from service.core.errors import TenantContextRequiredError

pytestmark = pytest.mark.integration


@pytest.fixture
async def db_session() -> AsyncSession:
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
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()
    except OSError as error:
        pytest.skip(f"PostgreSQL integration service unavailable: {error}")
    finally:
        await engine.dispose()


def _memory(
    tenant_id: str,
    content: str,
    memory_id: str = "memory_shared",
) -> LongTermMemoryModel:
    return LongTermMemoryModel(
        tenant_id=tenant_id,
        memory_id=memory_id,
        memory_type="PREFERENCE",
        owner_type="user",
        owner_id="user_shared",
        scope_type="user",
        scope_id="user_shared",
        status="active",
        version=1,
        content=content,
        normalized_key="preference.shared",
        content_hash=f"hash_{tenant_id}",
        language="zh-CN",
        type_payload={},
        confidence=1,
        importance=1,
        explicitness=1,
        valid_from=datetime.now(UTC),
        evidence_ids=[],
        source_event_ids=[],
        conflict_ids=[],
    )


@pytest.mark.asyncio
async def test_equal_user_task_and_normalized_keys_do_not_cross_tenants(
    db_session: AsyncSession,
    tenant_a: TenantContext,
    tenant_b: TenantContext,
) -> None:
    db_session.add_all(
        [
            TaskMemoryModel(
                tenant_id="tenant_a",
                task_memory_id="task_memory_shared",
                task_id="task_shared",
                status="active",
            ),
            TaskMemoryModel(
                tenant_id="tenant_b",
                task_memory_id="task_memory_shared",
                task_id="task_shared",
                status="active",
            ),
            _memory("tenant_a", "A content"),
            _memory("tenant_b", "B content"),
        ]
    )
    await db_session.flush()

    repository = SqlAlchemyLongTermMemoryRepository(db_session)
    record_a = await repository.get_active(tenant_a, "memory_shared")
    record_b = await repository.get_active(tenant_b, "memory_shared")

    assert record_a is not None and record_a.content == "A content"
    assert record_b is not None and record_b.content == "B content"
    assert (
        await db_session.scalar(
            select(TaskMemoryModel).where(
                TaskMemoryModel.tenant_id == "tenant_a",
                TaskMemoryModel.task_id == "task_shared",
            )
        )
    ).tenant_id == "tenant_a"


@pytest.mark.asyncio
async def test_repository_rejects_missing_context(
    db_session: AsyncSession,
) -> None:
    repository = SqlAlchemyLongTermMemoryRepository(db_session)

    with pytest.raises(TenantContextRequiredError):
        await repository.get_active(None, "memory_shared")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unique_constraint_is_tenant_local(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            _memory("tenant_a", "A content"),
            _memory("tenant_b", "B content"),
        ]
    )
    await db_session.flush()

    db_session.add(_memory("tenant_a", "duplicate", memory_id="memory_other"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
