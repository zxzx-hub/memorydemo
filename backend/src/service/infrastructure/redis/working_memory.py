"""Redis Working Memory store with tenant + workspace isolation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from service.auth.tenant_context import TenantContext
from service.domain.models import WorkingMemory
from service.infrastructure.redis.keys import tenant_redis_key


class RedisWorkingMemoryStore:
    def __init__(
        self,
        client: Redis,
        ttl_seconds: int,
        lock_timeout_seconds: int = 30,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._lock_timeout_seconds = lock_timeout_seconds

    async def get(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> WorkingMemory | None:
        payload = await self._client.get(
            tenant_redis_key(ctx, "working-memory", workspace_id)
        )
        if payload is None:
            return None
        return WorkingMemory.model_validate_json(payload)

    async def save(
        self,
        ctx: TenantContext,
        working_memory: WorkingMemory,
    ) -> None:
        await self._client.set(
            tenant_redis_key(
                ctx,
                "working-memory",
                working_memory.workspace_id,
            ),
            working_memory.model_dump_json(),
            ex=self._ttl_seconds,
        )

    async def advance_cursor(
        self,
        ctx: TenantContext,
        workspace_id: str,
        expected_cursor: str | None,
        new_cursor: str,
    ) -> bool:
        working = await self.get(ctx, workspace_id)
        if working is None:
            return False
        window = dict(working.conversation_window)
        if window.get("consolidated_until_event_id") != expected_cursor:
            return False
        window["consolidated_until_event_id"] = new_cursor
        await self.save(
            ctx,
            working.model_copy(update={"conversation_window": window}),
        )
        return True

    @asynccontextmanager
    async def lock(
        self,
        ctx: TenantContext,
        workspace_id: str,
    ) -> AsyncIterator[None]:
        lock = self._client.lock(
            tenant_redis_key(ctx, "consolidation-lock", workspace_id),
            timeout=self._lock_timeout_seconds,
            blocking_timeout=self._lock_timeout_seconds,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise TimeoutError("Could not acquire the workspace consolidation lock.")
        try:
            yield
        finally:
            await lock.release()
