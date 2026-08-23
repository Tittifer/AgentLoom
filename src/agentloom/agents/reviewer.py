"""Deterministic structured-output review for worker attempts."""

from collections.abc import Iterable
from typing import Literal, Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

ReviewDecision = Literal["accept", "retry", "reject"]


class JsonSchemaValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[JsonSchemaValidationError]: ...


class ReviewResult(BaseModel):
    """Bounded reviewer decision persisted with a node attempt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: ReviewDecision
    score: float = Field(ge=0, le=1)
    feedback: str = Field(min_length=1)


class DeterministicReviewer:
    """Validate structured output without spending an LLM call."""

    def review(
        self,
        output: dict[str, JsonValue] | None,
        output_schema: dict[str, JsonValue],
    ) -> ReviewResult:
        """Return an actionable decision in a stable validation order."""

        if output is None:
            return ReviewResult(
                decision="retry",
                score=0,
                feedback="A structured JSON object is required.",
            )

        try:
            Draft202012Validator.check_schema(output_schema)
        except SchemaError as error:
            return ReviewResult(
                decision="reject",
                score=0,
                feedback=f"The configured output schema is invalid: {error.message}",
            )

        validator = cast(JsonSchemaValidator, Draft202012Validator(output_schema))
        validation_errors = sorted(
            validator.iter_errors(output),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if validation_errors:
            error = validation_errors[0]
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            return ReviewResult(
                decision="retry",
                score=0,
                feedback=f"Output does not match the JSON Schema at {path}: {error.message}",
            )

        empty_path = _find_empty_required_string(output, output_schema)
        if empty_path is not None:
            return ReviewResult(
                decision="retry",
                score=0,
                feedback=f"Required string at {empty_path} must not be empty.",
            )

        return ReviewResult(
            decision="accept",
            score=1,
            feedback="Structured output passed deterministic review.",
        )


def _find_empty_required_string(
    value: JsonValue,
    schema: dict[str, JsonValue],
    path: str = "$",
) -> str | None:
    schema_type = schema.get("type")
    if schema_type == "object" and isinstance(value, dict):
        required = schema.get("required")
        required_names = (
            {item for item in required if isinstance(item, str)}
            if isinstance(required, list)
            else set[str]()
        )
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return None
        for name, child_schema in properties.items():
            if not isinstance(child_schema, dict) or name not in value:
                continue
            child_value = value[name]
            child_path = f"{path}.{name}"
            if name in required_names and child_schema.get("type") == "string":
                if isinstance(child_value, str) and not child_value.strip():
                    return child_path
            empty_path = _find_empty_required_string(child_value, child_schema, child_path)
            if empty_path is not None:
                return empty_path
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                empty_path = _find_empty_required_string(item, item_schema, f"{path}.{index}")
                if empty_path is not None:
                    return empty_path
    return None


__all__ = ["DeterministicReviewer", "ReviewDecision", "ReviewResult"]
