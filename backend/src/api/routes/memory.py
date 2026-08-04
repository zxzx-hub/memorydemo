"""The three allowed memory API entry points."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.dependencies import get_memory_service, require_tenant_context
from service.auth.tenant_context import TenantContext
from domain.commands import (
    GcMemoryRequest,
    ReadMemoryRequest,
    WriteRequest,
)
from domain.results import GcMemoryResult, ReadMemoryResult, WriteResult
from service.memory_service import MemoryService

router = APIRouter(prefix="/v1/memory", tags=["memory"])

TenantDependency = Annotated[TenantContext, Depends(require_tenant_context)]
ServiceDependency = Annotated[MemoryService, Depends(get_memory_service)]


@router.post(
    "/write",
    response_model=WriteResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def write_memory(
    request: WriteRequest,
    ctx: TenantDependency,
    service: ServiceDependency,
) -> WriteResult:
    return await service.write(ctx, request)


@router.post("/read", response_model=ReadMemoryResult)
async def read_memory(
    request: ReadMemoryRequest,
    ctx: TenantDependency,
    service: ServiceDependency,
) -> ReadMemoryResult:
    return await service.read(ctx, request)


@router.post(
    "/gc",
    response_model=GcMemoryResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def gc_memory(
    request: GcMemoryRequest,
    ctx: TenantDependency,
    service: ServiceDependency,
) -> GcMemoryResult:
    return await service.gc(ctx, request)
