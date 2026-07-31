"""LLM suggestion boundary; callers must validate every returned mapping."""

from collections.abc import Mapping
from typing import Any, Protocol


class LLMClient(Protocol):
    async def generate(
        self,
        *,
        prompt_name: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return a structured suggestion without executing state changes."""
