"""Collision-safe tenant-prefixed Redis key construction."""

from urllib.parse import quote

from app.auth.tenant_context import TenantContext
from app.core.errors import TenantContextRequiredError


def tenant_redis_key(
    ctx: TenantContext,
    namespace: str,
    *parts: str,
) -> str:
    """Build `tenant:{tenant_id}:...` without accepting a raw tenant string."""

    if not isinstance(ctx, TenantContext):
        raise TenantContextRequiredError
    encoded = [quote(namespace, safe="-_.")]
    encoded.extend(quote(part, safe="-_.") for part in parts)
    if any(not part for part in encoded):
        raise ValueError("Redis key segments must not be empty")
    return f"tenant:{ctx.tenant_id}:{':'.join(encoded)}"
