"""Synchronous, tenant-bound JobDispatcher for the local MVP."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.auth.tenant_context import TenantContext
from app.core.ids import new_id

JobHandler = Callable[
    [TenantContext, Mapping[str, Any]],
    Awaitable[None],
]


class SynchronousJobDispatcher:
    """Execute registered jobs immediately while preserving TenantContext."""

    def __init__(self, handlers: Mapping[str, JobHandler] | None = None) -> None:
        self._handlers = dict(handlers or {})

    async def dispatch(
        self,
        ctx: TenantContext,
        job_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise ValueError(f"No handler registered for job type: {job_type}")
        await handler(ctx, payload)
        return new_id("job")
