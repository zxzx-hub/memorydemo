"""Background job adapters."""

from app.infrastructure.jobs.synchronous import SynchronousJobDispatcher

__all__ = ["SynchronousJobDispatcher"]
