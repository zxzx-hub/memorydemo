"""Liveness and dependency readiness endpoints."""

from fastapi import APIRouter, Request, Response, status

from service.core.health import ReadinessProbe
from domain.schemas import (
    DependencyStatusResponse,
    HealthResponse,
    ReadinessResponse,
)

router = APIRouter(tags=["operations"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=request.app.state.settings.app_name,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    probe: ReadinessProbe = request.app.state.readiness_probe
    report = await probe.check()
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if report.ready else "not_ready",
        dependencies=tuple(
            DependencyStatusResponse(name=item.name, status=item.status)
            for item in report.dependencies
        ),
    )
