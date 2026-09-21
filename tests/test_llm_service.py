from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.services.llm_service import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseValidationError,
    LLMService,
    LLMTimeoutError,
    MissingAPIKeyError,
)


class Summary(BaseModel):
    category: str
    recommendation: str


def response(content: str, *, parsed: object | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, parsed=parsed)
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        model="fake-model",
        id="fake-request-001",
        usage=usage,
    )


class FakeCompletions:
    def __init__(self, result: SimpleNamespace | None = None, failures: list[Exception] | None = None) -> None:
        self.result = result or response("fake response")
        self.failures = failures or []
        self.calls = 0

    def create(self, **_: object) -> SimpleNamespace:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.result


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def test_service_can_be_instantiated_with_mocked_client() -> None:
    service = LLMService(client=FakeClient(FakeCompletions()))
    assert service.model


def test_basic_text_generation_works_with_fake_client() -> None:
    service = LLMService(client=FakeClient(FakeCompletions(response("hello"))))
    result = service.generate(system_instructions="Be concise.", user_prompt="Say hello.")
    assert result.response == "hello"
    assert result.model == "fake-model"
    assert result.usage is not None
    assert result.request_id == "fake-request-001"


def test_structured_pydantic_output_is_validated() -> None:
    payload = '{"category":"demo","recommendation":"review"}'
    service = LLMService(client=FakeClient(FakeCompletions(response(payload))))
    result = service.generate_structured(user_prompt="Classify this.", response_model=Summary)
    assert isinstance(result.response, Summary)
    assert result.response.category == "demo"


def test_invalid_structured_output_is_handled() -> None:
    service = LLMService(client=FakeClient(FakeCompletions(response('{"category": 1}'))))
    with pytest.raises(LLMResponseValidationError):
        service.generate_structured(user_prompt="Classify this.", response_model=Summary)


def test_missing_api_key_is_handled_safely() -> None:
    service = LLMService(api_key="", client=None)
    with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY is not configured"):
        service.generate(user_prompt="Hello")


def test_timeout_retries_are_limited() -> None:
    completions = FakeCompletions(failures=[TimeoutError(), TimeoutError(), TimeoutError()])
    service = LLMService(client=FakeClient(completions), max_retries=2)
    with pytest.raises(LLMTimeoutError):
        service.generate(user_prompt="Retry me")
    assert completions.calls == 3


def test_rate_limit_retries_are_limited() -> None:
    rate_limit_error = type("RateLimitError", (Exception,), {})
    completions = FakeCompletions(failures=[rate_limit_error(), rate_limit_error()])
    service = LLMService(client=FakeClient(completions), max_retries=1)
    with pytest.raises(LLMRateLimitError):
        service.generate(user_prompt="Rate limited")
    assert completions.calls == 2


def test_transient_connection_failure_recovers() -> None:
    completions = FakeCompletions(failures=[ConnectionError("secret-api-key")])
    service = LLMService(client=FakeClient(completions), max_retries=1)
    result = service.generate(user_prompt="Recover")
    assert result.response == "fake response"
    assert completions.calls == 2


def test_api_key_is_not_exposed_in_errors_or_output(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "sk-demo-never-log-this"
    completions = FakeCompletions(failures=[ConnectionError(secret)])
    service = LLMService(client=FakeClient(completions), api_key=secret, max_retries=0)
    with pytest.raises(LLMConnectionError) as error:
        service.generate(user_prompt="Fail safely")
    captured = capsys.readouterr()
    assert secret not in str(error.value)
    assert secret not in captured.out
    assert secret not in captured.err


def test_no_network_call_is_required() -> None:
    completions = FakeCompletions(response("offline"))
    result = LLMService(client=FakeClient(completions)).generate(user_prompt="Offline")
    assert result.response == "offline"
