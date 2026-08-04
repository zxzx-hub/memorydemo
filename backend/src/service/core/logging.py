"""Logging configuration that avoids sensitive payload rendering."""

import logging
from typing import Final

_FORMAT: Final = (
    "%(asctime)s %(levelname)s %(name)s trace_id=%(trace_id)s message=%(message)s"
)


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


def configure_logging(level: str) -> None:
    """Configure process logging with a stable, payload-free format."""

    logging.basicConfig(level=level.upper(), format=_FORMAT, force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_TraceIdFilter())
