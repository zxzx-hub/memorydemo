"""Tenant-partitioned graph traversal over PostgreSQL nodes and edges."""

from collections.abc import Sequence

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.tenant_context import TenantContext
from app.infrastructure.db.models.memory import (
    MemoryGraphEdgeModel,
    MemoryGraphNodeModel,
)
from app.infrastructure.db.repositories.base import require_repository_context


class PostgreSQLGraphStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def traverse(
        self,
        ctx: TenantContext,
        entity_ids: Sequence[str],
        relations: Sequence[str],
        max_depth: int,
    ) -> Sequence[str]:
        tenant = require_repository_context(ctx)
        if not entity_ids or max_depth < 1:
            return ()
        async with self._session_factory() as session:
            start_nodes = (
                await session.scalars(
                    select(MemoryGraphNodeModel.node_id).where(
                        MemoryGraphNodeModel.tenant_id == tenant.tenant_id,
                        or_(
                            MemoryGraphNodeModel.node_id.in_(entity_ids),
                            MemoryGraphNodeModel.normalized_key.in_(entity_ids),
                        ),
                    )
                )
            ).all()
            frontier = set(start_nodes)
            visited = set(frontier)
            memory_ids: set[str] = set()
            for _ in range(max_depth):
                if not frontier:
                    break
                statement = select(MemoryGraphEdgeModel).where(
                    MemoryGraphEdgeModel.tenant_id == tenant.tenant_id,
                    MemoryGraphEdgeModel.source_node_id.in_(frontier),
                )
                if relations:
                    statement = statement.where(
                        MemoryGraphEdgeModel.relation_type.in_(relations)
                    )
                edges = (await session.scalars(statement)).all()
                next_frontier = set()
                for edge in edges:
                    if edge.memory_id is not None:
                        memory_ids.add(edge.memory_id)
                    if edge.target_node_id not in visited:
                        next_frontier.add(edge.target_node_id)
                visited.update(next_frontier)
                frontier = next_frontier
        return tuple(sorted(memory_ids))

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        tenant = require_repository_context(ctx)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(MemoryGraphEdgeModel).where(
                    MemoryGraphEdgeModel.tenant_id == tenant.tenant_id,
                    MemoryGraphEdgeModel.memory_id == memory_id,
                )
            )
            await session.execute(
                delete(MemoryGraphNodeModel).where(
                    MemoryGraphNodeModel.tenant_id == tenant.tenant_id,
                    MemoryGraphNodeModel.memory_id == memory_id,
                )
            )
