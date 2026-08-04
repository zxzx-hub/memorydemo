"""Tenant-prefixed Redis key tests."""

import pytest

from service.auth.tenant_context import TenantContext
from service.core.errors import TenantContextRequiredError
from infrastructure.redis.keys import tenant_redis_key


def test_redis_keys_do_not_collide_across_tenants(
    tenant_a: TenantContext,
    tenant_b: TenantContext,
) -> None:
    key_a = tenant_redis_key(tenant_a, "working-memory", "workspace_shared")
    key_b = tenant_redis_key(tenant_b, "working-memory", "workspace_shared")

    assert key_a == "tenant:tenant_a:working-memory:workspace_shared"
    assert key_b == "tenant:tenant_b:working-memory:workspace_shared"
    assert key_a != key_b


def test_redis_key_rejects_missing_context() -> None:
    with pytest.raises(TenantContextRequiredError):
        tenant_redis_key(None, "working-memory", "workspace")  # type: ignore[arg-type]
