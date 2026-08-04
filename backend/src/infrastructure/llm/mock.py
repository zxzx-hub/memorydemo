"""Deterministic local LLM adapter for tests and demos."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class MockLLMClient:
    """Return configured structured suggestions without external calls."""

    def __init__(
        self,
        responses: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._responses = dict(responses or {})

    async def generate(
        self,
        *,
        prompt_name: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del payload
        response = self._responses.get(
            prompt_name,
            {
                "kind": "mock_suggestion",
                "prompt_name": prompt_name,
                "items": [],
            },
        )
        return deepcopy(response)
