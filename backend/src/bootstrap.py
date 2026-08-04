"""Application dependency assembly for the local MVP runtime."""

from service.core.clock import SystemClock
from service.core.config import Settings
from infrastructure.consolidation import DeterministicConsolidator
from infrastructure.db.repositories.exact_key import SqlAlchemyExactKeyStore
from infrastructure.db.repositories.retrieval import SqlAlchemyRetrievalStore
from infrastructure.db.repositories.write import SqlAlchemyWriteUnitOfWorkFactory
from infrastructure.db.session import DatabaseSessionManager
from infrastructure.graph import PostgreSQLGraphStore
from infrastructure.llm import MockLLMClient
from infrastructure.redis.client import RedisConnection
from infrastructure.redis.working_memory import RedisWorkingMemoryStore
from infrastructure.retrieval import (
    DeterministicRetrievalPlanProvider,
    LLMRetrievalPlanProvider,
)
from infrastructure.vector import PostgreSQLVectorStore
from service.memory_facade import DefaultMemoryService
from service.read.context_compiler import DefaultContextCompiler
from service.read.retrieval_service import (
    DefaultRetrievalService,
    MetaPolicy,
    RetrievalRouter,
    RetrievalWeights,
)
from service.write.consolidate_once import ConsolidateOnceService
from service.write.consolidation_policy import ConsolidationPolicy


def build_memory_service(
    settings: Settings,
    database: DatabaseSessionManager,
    redis: RedisConnection,
) -> DefaultMemoryService:
    """Build the concrete MemoryService and its tenant-safe adapters."""

    working_memory_store = RedisWorkingMemoryStore(
        redis.client,
        ttl_seconds=settings.working_memory_ttl_seconds,
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
            semantic_relevance=settings.retrieval_semantic_weight,
            confidence=settings.retrieval_confidence_weight,
            importance=settings.retrieval_importance_weight,
            explicitness=settings.retrieval_explicitness_weight,
            freshness=settings.retrieval_freshness_weight,
            retrieval_weight=settings.retrieval_usage_weight,
            scope_match=settings.retrieval_scope_weight,
            freshness_half_life_days=settings.retrieval_freshness_half_life_days,
        ),
        SystemClock(),
    )
    return DefaultMemoryService(
        write_factory,
        working_memory_store,
        consolidate_once,
        ConsolidationPolicy(
            message_count=settings.consolidation_message_count,
            token_ratio=settings.consolidation_token_ratio,
            idle_seconds=settings.consolidation_idle_seconds,
        ),
        SystemClock(),
        retrieval_service,
    )
