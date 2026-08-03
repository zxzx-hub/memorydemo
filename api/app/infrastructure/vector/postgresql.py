"""Tenant-filtered pgvector search with deterministic local embeddings."""

from collections.abc import Sequence
from hashlib import sha256
from math import sqrt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.tenant_context import TenantContext
from app.infrastructure.db.models.memory import MemoryVectorIndexModel
from app.infrastructure.db.repositories.base import require_repository_context


class PostgreSQLVectorStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dimensions: int = 1536,
    ) -> None:
        self._session_factory = session_factory
        self._dimensions = dimensions

    async def search(
        self,
        ctx: TenantContext,
        query: str,
        limit: int,
    ) -> Sequence[str]:
        tenant = require_repository_context(ctx)
        embedding = deterministic_embedding(query, self._dimensions)
        async with self._session_factory() as session:
            values = await session.scalars(
                select(MemoryVectorIndexModel.memory_id)
                .where(
                    MemoryVectorIndexModel.tenant_id == tenant.tenant_id,
                )
                .order_by(MemoryVectorIndexModel.embedding.cosine_distance(embedding))
                .limit(limit)
            )
            return tuple(values.all())

    async def delete(self, ctx: TenantContext, memory_id: str) -> None:
        from sqlalchemy import delete

        tenant = require_repository_context(ctx)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(MemoryVectorIndexModel).where(
                    MemoryVectorIndexModel.tenant_id == tenant.tenant_id,
                    MemoryVectorIndexModel.memory_id == memory_id,
                )
            )


def deterministic_embedding(content: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in content.lower().split():
        digest = sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1 if digest[4] % 2 == 0 else -1
    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1
        return vector
    return [value / norm for value in vector]
