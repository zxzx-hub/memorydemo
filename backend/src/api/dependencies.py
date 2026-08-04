"""Fail-closed API dependencies."""

from typing import cast

from fastapi import Request

from service.auth.tenant_context import TenantContext
from service.core.errors import FeatureNotAvailableError, TenantContextRequiredError
from service.memory_service import MemoryService


def require_tenant_context(request: Request) -> TenantContext:
    """Return only a context previously installed by trusted middleware."""

    context = getattr(request.state, "tenant_context", None)
    if not isinstance(context, TenantContext):
        raise TenantContextRequiredError
    return context


def get_memory_service(request: Request) -> MemoryService:
    """Resolve the bound service without substituting a fake success path."""

    service = getattr(request.app.state, "memory_service", None)
    if service is None:
        raise FeatureNotAvailableError
    return cast(MemoryService, service)
