"""Tests for application environment settings."""

import pytest
from pydantic import ValidationError

from agentloom.config import Settings


def test_llm_response_format_defaults_to_strict_json_schema() -> None:
    settings = Settings.model_validate({})

    assert settings.llm_response_format == "json_schema"


def test_llm_response_format_accepts_json_object() -> None:
    settings = Settings.model_validate({"llm_response_format": "json_object"})

    assert settings.llm_response_format == "json_object"


def test_llm_response_format_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"llm_response_format": "plain_text"})
