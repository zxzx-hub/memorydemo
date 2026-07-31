"""Opaque identifier generation."""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Create a non-guessable opaque ID with a human-readable prefix."""

    normalized = prefix.strip().lower().replace(" ", "_")
    if not normalized:
        raise ValueError("ID prefix must not be empty")
    return f"{normalized}_{uuid4().hex}"
