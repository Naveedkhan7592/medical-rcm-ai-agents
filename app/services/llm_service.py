from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import DEFAULT_OPENAI_MODEL, settings
from app.schemas import LLMResponse, LLMUsage


T = TypeVar("T", bound=BaseModel)


class LLMServiceError(RuntimeError):
    """Base exception for safe, application-facing LLM service failures."""


class MissingAPIKeyError(LLMServiceError):
    """Raised when a production request has no configured API key."""


class LLMConfigurationError(LLMServiceError):
    """Raised when the LLM client configuration is invalid."""


class LLMTimeoutError(LLMServiceError):
    """Raised after timeout retries are exhausted."""


class LLMConnectionError(LLMServiceError):
    """Raised after connection retries are exhausted."""


class LLMRateLimitError(LLMServiceError):
    """Raised after rate-limit retries are exhausted."""


class LLMResponseError(LLMServiceError):
    """Raised when the provider returns an unusable response."""


class LLMResponseValidationError(LLMResponseError):
    """Raised when structured output cannot be validated by Pydantic."""


class LLMService(Generic[T]):
    """Small, domain-agnostic wrapper around the official OpenAI client.

    The client is injectable so tests and future application services can use a
    deterministic implementation without credentials or network access.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if timeout <= 0:
            raise LLMConfigurationError("timeout must be greater than zero")
        if max_retries < 0:
            raise LLMConfigurationError("max_retries cannot be negative")

        self.api_key = settings.OPENAI_API_KEY if api_key is None else api_key
        self.model = model or settings.OPENAI_MODEL or DEFAULT_OPENAI_MODEL
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise MissingAPIKeyError("OPENAI_API_KEY is not configured")
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0)
            except Exception as exc:
                raise LLMConfigurationError("Unable to initialize the OpenAI client") from exc
        return self._client

    def generate(
        self,
        *,
        system_instructions: str | None = None,
        user_prompt: str,
        temperature: float | None = None,
    ) -> LLMResponse[str]:
        messages = self._build_messages(system_instructions, user_prompt)
        started = time.perf_counter()
        raw_response = self._request(
            messages=messages,
            temperature=temperature,
            structured_model=None,
        )
        content = self._extract_content(raw_response)
        return LLMResponse(
            model=self._response_model(raw_response),
            response=content,
            usage=self._extract_usage(raw_response),
            request_id=self._response_request_id(raw_response),
            processing_time_ms=self._elapsed_ms(started),
        )

    def generate_structured(
        self,
        *,
        system_instructions: str | None = None,
        user_prompt: str,
        response_model: type[T],
        temperature: float | None = None,
    ) -> LLMResponse[T]:
        messages = self._build_messages(system_instructions, user_prompt)
        started = time.perf_counter()
        raw_response = self._request(
            messages=messages,
            temperature=temperature,
            structured_model=response_model,
        )
        parsed = self._extract_structured(raw_response, response_model)
        return LLMResponse(
            model=self._response_model(raw_response),
            response=parsed,
            usage=self._extract_usage(raw_response),
            request_id=self._response_request_id(raw_response),
            processing_time_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _build_messages(system_instructions: str | None, user_prompt: str) -> list[dict[str, str]]:
        if not user_prompt.strip():
            raise LLMConfigurationError("user_prompt cannot be empty")
        messages: list[dict[str, str]] = []
        if system_instructions:
            messages.append({"role": "system", "content": system_instructions})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _request(
        self,
        *,
        messages: Sequence[dict[str, str]],
        temperature: float | None,
        structured_model: type[BaseModel] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {"model": self.model, "messages": list(messages)}
        if temperature is not None:
            kwargs["temperature"] = temperature
        client = self.client
        for attempt in range(self.max_retries + 1):
            try:
                if structured_model is not None:
                    parser = getattr(getattr(client, "beta", None), "chat", None)
                    parser = getattr(getattr(parser, "completions", None), "parse", None)
                    if parser is not None:
                        return parser(**kwargs, response_format=structured_model)
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                error = self._safe_provider_error(exc)
                if not error[1] or attempt >= self.max_retries:
                    raise error[0] from exc
        raise LLMResponseError("LLM request failed")

    @staticmethod
    def _safe_provider_error(exc: Exception) -> tuple[LLMServiceError, bool]:
        name = type(exc).__name__.lower()
        if isinstance(exc, TimeoutError) or "timeout" in name:
            return LLMTimeoutError("LLM request timed out"), True
        if isinstance(exc, ConnectionError) or "connection" in name:
            return LLMConnectionError("LLM connection failed"), True
        if "ratelimit" in name or "rate_limit" in name:
            return LLMRateLimitError("LLM rate limit reached"), True
        if "authentication" in name or "permission" in name:
            return LLMServiceError("LLM authentication failed"), False
        if "badrequest" in name or "invalidrequest" in name:
            return LLMConfigurationError("LLM request configuration is invalid"), False
        return LLMResponseError("LLM provider returned an unexpected error"), False

    @staticmethod
    def _extract_content(raw_response: Any) -> str:
        try:
            content = raw_response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response did not contain text content") from exc
        if not isinstance(content, str):
            raise LLMResponseError("LLM response content was not text")
        return content

    @classmethod
    def _extract_structured(cls, raw_response: Any, response_model: type[T]) -> T:
        try:
            message = raw_response.choices[0].message
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response did not contain structured content") from exc
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            try:
                return response_model.model_validate(parsed)
            except ValidationError as exc:
                raise LLMResponseValidationError("Structured LLM response failed validation") from exc
        content = cls._extract_content(raw_response)
        try:
            return response_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise LLMResponseValidationError("Structured LLM response failed validation") from exc

    @staticmethod
    def _extract_usage(raw_response: Any) -> LLMUsage | None:
        usage = getattr(raw_response, "usage", None)
        if usage is None:
            return None
        return LLMUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    @staticmethod
    def _response_model(raw_response: Any) -> str:
        return str(getattr(raw_response, "model", settings.OPENAI_MODEL or DEFAULT_OPENAI_MODEL))

    @staticmethod
    def _response_request_id(raw_response: Any) -> str | None:
        request_id = getattr(raw_response, "_request_id", None) or getattr(raw_response, "id", None)
        return str(request_id) if request_id is not None else None

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
