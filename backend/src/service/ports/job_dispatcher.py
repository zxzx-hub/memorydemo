"""Tenant-bound background job dispatch contract."""

from collections.abc import Mapping
from typing import Any, Protocol

from service.auth.tenant_context import TenantContext


class JobDispatcher(Protocol):
    async def dispatch(
        self,
        ctx: TenantContext,
        job_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        """Dispatch one job frozen to the current tenant."""
