"""PostgreSQL exact-key adapter returning memory IDs only."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.auth.tenant_context import TenantContext
from infrastructure.db.models.memory import MemoryExactKeyModel
from infrastructure.db.repositories.base import require_repository_context


class SqlAlchemyExactKeyStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        ctx: TenantContext,
        memory_key: str,
    ) -> str | None:
        tenant = require_repository_context(ctx)
        async with self._session_factory() as session:
            value = await session.scalar(
                select(MemoryExactKeyModel.memory_id).where(
                    MemoryExactKeyModel.tenant_id == tenant.tenant_id,
                    MemoryExactKeyModel.memory_key == memory_key,
                )
            )
        return str(value) if value is not None else None

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        tenant = require_repository_context(ctx)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(MemoryExactKeyModel).where(
                    MemoryExactKeyModel.tenant_id == tenant.tenant_id,
                    MemoryExactKeyModel.memory_id == memory_id,
                )
            )
