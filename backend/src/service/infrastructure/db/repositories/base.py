"""Shared fail-closed behavior for tenant-scoped repositories."""

from sqlalchemy.ext.asyncio import AsyncSession

from service.auth.tenant_context import TenantContext
from service.core.errors import TenantContextRequiredError


def require_repository_context(ctx: TenantContext | None) -> TenantContext:
    if not isinstance(ctx, TenantContext):
        raise TenantContextRequiredError
    return ctx


class TenantScopedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
