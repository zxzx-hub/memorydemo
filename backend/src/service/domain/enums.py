"""Stable domain enumerations from the architecture design."""

from enum import StrEnum


class MemoryType(StrEnum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    CONSTRAINT = "CONSTRAINT"
    DECISION = "DECISION"
    PROGRESS = "PROGRESS"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    PENDING_DELETE = "pending_delete"
    TOMBSTONED = "tombstoned"


class RetrievalMode(StrEnum):
    AUTO = "auto"
    META = "meta"
    RESUME = "resume"
    EXPRESS = "express"
    QUICK = "quick"
    NORMAL = "normal"
    DEEP = "deep"


class GovernanceAction(StrEnum):
    CREATE = "create"
    REFINE = "refine"
    CORRECT = "correct"
    MERGE = "merge"
    SUPERSEDE = "supersede"
    DEFER = "defer"
    IGNORE = "ignore"


class IndexType(StrEnum):
    EXACT = "exact"
    VECTOR = "vector"
    GRAPH = "graph"
    CACHE = "cache"


class IndexStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    REBUILDING = "rebuilding"
    DELETED = "deleted"


class ConsolidationReason(StrEnum):
    MESSAGE_COUNT = "message_count"
    TOKEN_RATIO = "token_ratio"
    IDLE_TIMEOUT = "idle_timeout"
    STEP_COMPLETED = "step_completed"
    TASK_SWITCHED = "task_switched"
    SESSION_ENDED = "session_ended"
    EXPLICIT_REMEMBER = "explicit_remember"
    MANUAL = "manual"
