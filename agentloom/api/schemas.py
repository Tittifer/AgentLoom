"""Shared system and error DTOs."""

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class HealthResponse(ApiModel):
    status: str


class ApiErrorDetail(ApiModel):
    path: str
    reason: str


class ApiError(ApiModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: list[ApiErrorDetail] = Field(
        default_factory=lambda: list[ApiErrorDetail](),
    )


__all__ = ["ApiError", "ApiErrorDetail", "HealthResponse"]
