"""Authentication adapters that are the sole TenantContext factories."""

from abc import ABC, abstractmethod

from starlette.requests import Request

from service.auth.tenant_context import (
    AuthSource,
    TenantContext,
    _create_tenant_context,
)
from service.core.errors import TenantContextRequiredError
from service.core.ids import new_id


class TenantResolver(ABC):
    """Verified identity boundary."""

    @abstractmethod
    async def resolve(self, request: Request) -> TenantContext:
        """Verify request authentication and return a trusted context."""

    @staticmethod
    def _create(
        *,
        tenant_id: str,
        principal_id: str,
        auth_source: str,
        trace_id: str,
    ) -> TenantContext:
        return _create_tenant_context(
            tenant_id=tenant_id,
            principal_id=principal_id,
            auth_source=auth_source,
            trace_id=trace_id,
        )


class DevelopmentTenantResolver(TenantResolver):
    """Explicit local-only resolver backed by development test headers."""

    tenant_header = "X-Development-Tenant-ID"
    principal_header = "X-Development-Principal-ID"
    trace_header = "X-Trace-ID"

    async def resolve(self, request: Request) -> TenantContext:
        tenant_id = request.headers.get(self.tenant_header)
        principal_id = request.headers.get(self.principal_header)
        if tenant_id is None or principal_id is None:
            raise TenantContextRequiredError(
                "Development tenant identity headers are required."
            )
        return self._create(
            tenant_id=tenant_id,
            principal_id=principal_id,
            auth_source=AuthSource.DEVELOPMENT,
            trace_id=request.headers.get(self.trace_header) or new_id("trace"),
        )
