"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.routes.health import router as health_router
from app.api.routes.memory import router as memory_router
from app.auth.middleware import TenantContextMiddleware
from app.auth.tenant_resolver import (
    DevelopmentTenantResolver,
    TenantResolver,
)
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.core.health import ReadinessProbe
from app.core.logging import configure_logging
from app.infrastructure.consolidation import DeterministicConsolidator
from app.infrastructure.db.repositories.exact_key import SqlAlchemyExactKeyStore
from app.infrastructure.db.repositories.retrieval import SqlAlchemyRetrievalStore
from app.infrastructure.db.repositories.write import (
    SqlAlchemyWriteUnitOfWorkFactory,
)
from app.infrastructure.db.session import DatabaseSessionManager
from app.infrastructure.graph import PostgreSQLGraphStore
from app.infrastructure.llm import MockLLMClient
from app.infrastructure.redis.client import RedisConnection
from app.infrastructure.redis.working_memory import RedisWorkingMemoryStore
from app.infrastructure.retrieval import (
    DeterministicRetrievalPlanProvider,
    LLMRetrievalPlanProvider,
)
from app.infrastructure.vector import PostgreSQLVectorStore
from app.services.consolidate_once import ConsolidateOnceService
from app.services.consolidation_policy import ConsolidationPolicy
from app.services.context_compiler import DefaultContextCompiler
from app.services.default_memory_service import DefaultMemoryService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import (
    DefaultRetrievalService,
    MetaPolicy,
    RetrievalRouter,
    RetrievalWeights,
)


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
            working_memory_store = RedisWorkingMemoryStore(
                redis.client,
                ttl_seconds=app_settings.working_memory_ttl_seconds,
            )
            write_factory = SqlAlchemyWriteUnitOfWorkFactory(database.session_factory)
            consolidate_once = ConsolidateOnceService(
                write_factory,
                working_memory_store,
                DeterministicConsolidator(),
            )
            retrieval_service = DefaultRetrievalService(
                SqlAlchemyRetrievalStore(database.session_factory),
                SqlAlchemyExactKeyStore(database.session_factory),
                PostgreSQLVectorStore(database.session_factory),
                PostgreSQLGraphStore(database.session_factory),
                LLMRetrievalPlanProvider(
                    MockLLMClient(),
                    DeterministicRetrievalPlanProvider(),
                ),
                DefaultContextCompiler(),
                RetrievalRouter(),
                MetaPolicy(),
                RetrievalWeights(
                    semantic_relevance=(app_settings.retrieval_semantic_weight),
                    confidence=app_settings.retrieval_confidence_weight,
                    importance=app_settings.retrieval_importance_weight,
                    explicitness=app_settings.retrieval_explicitness_weight,
                    freshness=app_settings.retrieval_freshness_weight,
                    retrieval_weight=app_settings.retrieval_usage_weight,
                    scope_match=app_settings.retrieval_scope_weight,
                    freshness_half_life_days=(
                        app_settings.retrieval_freshness_half_life_days
                    ),
                ),
                SystemClock(),
            )
            application.state.memory_service = DefaultMemoryService(
                write_factory,
                working_memory_store,
                consolidate_once,
                ConsolidationPolicy(
                    message_count=app_settings.consolidation_message_count,
                    token_ratio=app_settings.consolidation_token_ratio,
                    idle_seconds=app_settings.consolidation_idle_seconds,
                ),
                SystemClock(),
                retrieval_service,
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
