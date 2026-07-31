"""Configuration and transport schema invariants."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.domain.commands import WriteRequest


def test_settings_are_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_APP_NAME", "memory-test")
    monkeypatch.setenv("MEMORY_PORT", "8123")

    settings = Settings()

    assert settings.app_name == "memory-test"
    assert settings.port == 8123


def test_write_request_forbids_tenant_id() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(WriteRequest).validate_python(
            {
                "type": "event",
                "tenant_id": "untrusted",
                "idempotency_key": "request_1",
                "workspace_id": "workspace_1",
                "event": {
                    "event_id": "event_1",
                    "event_type": "user_message",
                    "role": "user",
                    "source": "api",
                    "content": "hello",
                },
            }
        )
