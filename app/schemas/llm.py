from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(BaseModel, Generic[T]):
    model: str
    response: T
    confidence: float | None = None
    usage: LLMUsage | None = None
    request_id: str | None = None
    processing_time_ms: float | None = None


class LLMErrorResponse(BaseModel):
    error_type: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
