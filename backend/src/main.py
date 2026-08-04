"""FastAPI application factory and HTTP composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.error_handlers import register_error_handlers
from api.routes.health import router as health_router
from api.routes.memory import router as memory_router
from bootstrap import build_memory_service
from infrastructure.db.session import DatabaseSessionManager
from infrastructure.redis.client import RedisConnection
from service.auth.middleware import TenantContextMiddleware
from service.auth.tenant_resolver import (
    DevelopmentTenantResolver,
    TenantResolver,
)
from service.core.config import Settings, get_settings
from service.core.health import ReadinessProbe
from service.core.logging import configure_logging
from service.memory_service import MemoryService


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    memory_service: MemoryService | None = None,
    tenant_resolver: TenantResolver | None = None,
) -> FastAPI:
    """Build an application with explicit adapter injection."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = app_settings
        application.state.memory_service = memory_service

        if readiness_probe is not None:
            application.state.readiness_probe = readiness_probe
            yield
            return

        database = DatabaseSessionManager(app_settings.database_url)
        redis = RedisConnection(app_settings.redis_url)
        if memory_service is None:
            application.state.memory_service = build_memory_service(
                app_settings,
                database,
                redis,
            )
        application.state.readiness_probe = ReadinessProbe(
            dependencies=(database, redis),
            timeout_seconds=app_settings.readiness_timeout_seconds,
        )
        try:
            yield
        finally:
            await redis.close()
            await database.close()

    application = FastAPI(
        title="Agent Memory Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(memory_router)

    register_error_handlers(application)
    resolved_tenant_resolver = tenant_resolver
    if (
        resolved_tenant_resolver is None
        and app_settings.enable_development_tenant_resolver
    ):
        resolved_tenant_resolver = DevelopmentTenantResolver()
    if resolved_tenant_resolver is not None:
        application.add_middleware(
            TenantContextMiddleware,
            resolver=resolved_tenant_resolver,
        )
    # CORS 必须在 TenantContextMiddleware 之后注册 —— Starlette 的
    # add_middleware 是「最后调用、最外层」，需要 CORS 作为最外层
    # 才能在 OPTIONS 预检时正确响应，不被 TenantContext 提前拒绝。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_headers=[
            "Content-Type",
            "X-Development-Tenant-ID",
            "X-Development-Principal-ID",
            "X-Trace-ID",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        expose_headers=["X-Trace-ID"],
        max_age=600,
    )
    return application


app = create_app()
