"""Immutable tenant context created only through a TenantResolver."""

import re
from dataclasses import dataclass
from enum import StrEnum

from service.core.errors import TenantContextRequiredError


class AuthSource(StrEnum):
    JWT = "jwt"
    MTLS = "mtls"
    SERVICE_ACCOUNT = "service_account"
    DEVELOPMENT = "development_header"


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_FACTORY_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class TenantContext:
    """Server-sourced identity used by every tenant-scoped operation."""

    tenant_id: str
    principal_id: str
    auth_source: str
    trace_id: str

    def __init__(
        self,
        tenant_id: str,
        principal_id: str,
        auth_source: str,
        trace_id: str,
        *,
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _FACTORY_TOKEN:
            raise TenantContextRequiredError(
                "TenantContext must be created by a TenantResolver."
            )
        if not _IDENTIFIER_PATTERN.fullmatch(tenant_id):
            raise TenantContextRequiredError("The resolved tenant ID is invalid.")
        if not _IDENTIFIER_PATTERN.fullmatch(principal_id):
            raise TenantContextRequiredError("The resolved principal ID is invalid.")
        if not trace_id.strip():
            raise TenantContextRequiredError("The resolved trace ID is invalid.")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "auth_source", str(auth_source))
        object.__setattr__(self, "trace_id", trace_id)


def _create_tenant_context(
    *,
    tenant_id: str,
    principal_id: str,
    auth_source: str,
    trace_id: str,
) -> TenantContext:
    """Resolver-only factory kept outside the public package surface."""

    return TenantContext(
        tenant_id=tenant_id,
        principal_id=principal_id,
        auth_source=auth_source,
        trace_id=trace_id,
        _factory_token=_FACTORY_TOKEN,
    )
