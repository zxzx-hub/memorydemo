"""FastAPI liveness, readiness and fail-closed boundary tests."""

from fastapi.testclient import TestClient

from main import create_app
from service.core.health import ReadinessProbe
from tests.conftest import StubDependency


def test_health_returns_success_without_dependency_checks(
    ready_probe: ReadinessProbe,
) -> None:
    with TestClient(create_app(readiness_probe=ready_probe)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agent-memory-service",
    }


def test_ready_returns_success_when_all_dependencies_are_available(
    ready_probe: ReadinessProbe,
) -> None:
    with TestClient(create_app(readiness_probe=ready_probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": [
            {"name": "postgresql", "status": "ok"},
            {"name": "redis", "status": "ok"},
        ],
    }


def test_ready_returns_503_without_leaking_failure_details() -> None:
    probe = ReadinessProbe(
        dependencies=(
            StubDependency("postgresql", available=False),
            StubDependency("redis"),
        ),
        timeout_seconds=0.1,
    )

    with TestClient(create_app(readiness_probe=probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": [
            {"name": "postgresql", "status": "unavailable"},
            {"name": "redis", "status": "ok"},
        ],
    }


def test_backend_does_not_mount_frontend_root(
    ready_probe: ReadinessProbe,
) -> None:
    with TestClient(create_app(readiness_probe=ready_probe)) as client:
        response = client.get("/")

    assert response.status_code == 404


def test_memory_route_fails_closed_without_tenant_context(
    ready_probe: ReadinessProbe,
) -> None:
    with TestClient(create_app(readiness_probe=ready_probe)) as client:
        response = client.post(
            "/v1/memory/read",
            json={"mode": "quick", "query": "similar preference"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TENANT_CONTEXT_REQUIRED"
