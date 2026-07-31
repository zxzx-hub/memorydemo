"""HTTP response schemas shared by routes."""

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiSchema):
    status: str
    service: str


class DependencyStatusResponse(ApiSchema):
    name: str
    status: str


class ReadinessResponse(ApiSchema):
    status: str
    dependencies: tuple[DependencyStatusResponse, ...]


class ErrorDetail(ApiSchema):
    code: str
    message: str
    trace_id: str


class ErrorResponse(ApiSchema):
    error: ErrorDetail
