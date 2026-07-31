"""TenantContext fixtures created through a test TenantResolver."""

from starlette.requests import Request

from app.auth.tenant_context import AuthSource, TenantContext
from app.auth.tenant_resolver import TenantResolver


class TestTenantResolver(TenantResolver):
    __test__ = False

    async def resolve(self, request: Request) -> TenantContext:
        return self.context(
            tenant_id=request.headers["x-test-tenant-id"],
            principal_id=request.headers["x-test-principal-id"],
        )

    def context(
        self,
        *,
        tenant_id: str,
        principal_id: str = "user_shared",
        trace_id: str = "trace_test",
    ) -> TenantContext:
        return self._create(
            tenant_id=tenant_id,
            principal_id=principal_id,
            auth_source=AuthSource.JWT,
            trace_id=trace_id,
        )
