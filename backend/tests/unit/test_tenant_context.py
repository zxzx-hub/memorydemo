"""TenantContext creation, immutability and middleware tests."""

from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from fastapi.testclient import TestClient

from service.auth.tenant_context import TenantContext
from service.auth.tenant_resolver import DevelopmentTenantResolver
from service.core.errors import TenantContextRequiredError
from service.core.health import ReadinessProbe
from main import create_app
from service.memory_service import MemoryService
from tests.fixtures.tenants import TestTenantResolver


def test_tenant_context_rejects_direct_construction() -> None:
    with pytest.raises(TenantContextRequiredError):
        TenantContext(
            tenant_id="tenant_a",
            principal_id="user_1",
            auth_source="jwt",
            trace_id="trace_1",
        )


def test_resolver_creates_frozen_context() -> None:
    context = TestTenantResolver().context(tenant_id="tenant_a")

    with pytest.raises(FrozenInstanceError):
        context.tenant_id = "tenant_b"  # type: ignore[misc]


def test_development_resolver_is_explicit_and_fails_without_headers(
    ready_probe: ReadinessProbe,
) -> None:
    app = create_app(
        readiness_probe=ready_probe,
        tenant_resolver=DevelopmentTenantResolver(),
    )
    with TestClient(app) as client:
        missing = client.post(
            "/v1/memory/read",
            json={"mode": "quick", "query": "preference"},
        )
        resolved = client.post(
            "/v1/memory/read",
            headers={
                "X-Development-Tenant-ID": "tenant_a",
                "X-Development-Principal-ID": "user_shared",
            },
            json={"mode": "quick", "query": "preference"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "TENANT_CONTEXT_REQUIRED"
    assert resolved.status_code == 501
    assert resolved.json()["error"]["code"] == "FEATURE_NOT_AVAILABLE"


def test_request_body_tenant_id_cannot_override_resolved_context(
    ready_probe: ReadinessProbe,
) -> None:
    app = create_app(
        readiness_probe=ready_probe,
        tenant_resolver=DevelopmentTenantResolver(),
        memory_service=cast(MemoryService, object()),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/memory/read",
            headers={
                "X-Development-Tenant-ID": "tenant_a",
                "X-Development-Principal-ID": "user_shared",
            },
            json={
                "tenant_id": "tenant_b",
                "mode": "quick",
                "query": "preference",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
