"""Tenant-scoped task memory queries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tenant_context import TenantContext
from app.infrastructure.db.models.memory import TaskMemoryModel
from app.infrastructure.db.repositories.base import (
    TenantScopedRepository,
    require_repository_context,
)


class SqlAlchemyTaskMemoryRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_task(
        self,
        ctx: TenantContext,
        task_id: str,
    ) -> TaskMemoryModel | None:
        tenant = require_repository_context(ctx)
        statement = select(TaskMemoryModel).where(
            TaskMemoryModel.tenant_id == tenant.tenant_id,
            TaskMemoryModel.task_id == task_id,
        )
        result = await self._session.scalar(statement)
        return result
