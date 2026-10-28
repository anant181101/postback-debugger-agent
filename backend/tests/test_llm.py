from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError

from postback_debugger.data.models import FailureType
from postback_debugger.diagnosis import Diagnosis
from postback_debugger.llm import LLMError, QuotaExceededError, Usage, get_provider
from postback_debugger.llm.base import cost_usd
from postback_debugger.llm.claude import ClaudeProvider
from postback_debugger.llm.gemini import GeminiProvider

DIAGNOSIS = Diagnosis(
    failure_type=FailureType.PARTNER_5XX, summary="s", evidence=["e"], recommended_fix="f"
)


# --- cost and provider selection -------------------------------------------------------


def test_cost_for_known_model() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)
    assert cost_usd("claude-sonnet-5-5", usage) == pytest.approx(2.00 + 1.00)


def test_cost_for_unknown_model_is_none() -> None:
    assert cost_usd("gemini-3.5-flash", Usage(10, 10)) is None


def test_get_provider_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("nope")


def test_get_provider_uses_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "")  # empty means "use the default"
    provider = get_provider()
    assert provider.name == "gemini" and provider.model == "gemini-3.5-flash"


def test_gemini_without_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMError, match="not configured"):
        GeminiProvider()


# --- Gemini ----------------------------------------------------------------------------


def _gemini_response(text: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        model_version="gemini-served-version",
        candidates=[SimpleNamespace(finish_reason="SAFETY")],
        usage_metadata=SimpleNamespace(
            prompt_token_count=100, candidates_token_count=30, thoughts_token_count=70
        ),
    )


def _gemini(response: Any = None, error: Exception | None = None) -> GeminiProvider:
    def generate_content(**kwargs: Any) -> Any:
        if error:
            raise error
        return response

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiProvider(model="gemini-test", client=client)  # type: ignore[arg-type]


def test_gemini_structured_output_is_validated() -> None:
    provider = _gemini(_gemini_response(DIAGNOSIS.model_dump_json()))
    result = provider.generate_structured("sys", "prompt", Diagnosis)
    assert result.data == DIAGNOSIS
    assert result.model == "gemini-served-version"
    assert result.usage == Usage(input_tokens=100, output_tokens=100, thinking_tokens=70)
    assert result.cost_usd is None


def test_gemini_invalid_json_raises_llm_error() -> None:
    provider = _gemini(_gemini_response('{"failure_type": "not-a-type"}'))
    with pytest.raises(LLMError, match="does not match Diagnosis"):
        provider.generate_structured("sys", "prompt", Diagnosis)


def test_gemini_empty_response_raises_llm_error() -> None:
    with pytest.raises(LLMError, match="SAFETY"):
        _gemini(_gemini_response(None)).generate_text("sys", "prompt")


def test_gemini_api_error_becomes_llm_error() -> None:
    error = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
    with pytest.raises(LLMError, match="503"):
        _gemini(error=error).generate_text("sys", "prompt")


# --- Claude ----------------------------------------------------------------------------


def _claude_response(stop_reason: str = "end_turn", **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-sonnet-5-5",
        content=fields.pop("content", []),
        parsed_output=fields.pop("parsed_output", None),
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            output_tokens_details=SimpleNamespace(thinking_tokens=300),
        ),
    )


def _claude(response: Any = None, error: Exception | None = None) -> ClaudeProvider:
    def call(**kwargs: Any) -> Any:
        assert kwargs["messages"] == [{"role": "user", "content": "prompt"}]
        if error:
            raise error
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=call, parse=call))
    return ClaudeProvider(model="claude-sonnet-5-5", client=client)  # type: ignore[arg-type]


def test_claude_structured_output_and_cost() -> None:
    result = _claude(_claude_response(parsed_output=DIAGNOSIS)).generate_structured(
        "sys", "prompt", Diagnosis
    )
    assert result.data == DIAGNOSIS
    assert result.usage == Usage(1000, 500, 300)
    assert result.cost_usd == pytest.approx((1000 * 2 + 500 * 10) / 1_000_000)


def test_claude_text_joins_text_blocks() -> None:
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Hello "),
        SimpleNamespace(type="text", text="world"),
    ]
    result = _claude(_claude_response(content=blocks)).generate_text("sys", "prompt")
    assert result.text == "Hello world"


@pytest.mark.parametrize(
    ("stop_reason", "message"), [("refusal", "declined"), ("max_tokens", "max_tokens")]
)
def test_claude_unusable_stop_reasons_raise(stop_reason: str, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _claude(_claude_response(stop_reason)).generate_text("sys", "prompt")


def test_claude_api_error_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="Claude API error"):
        _claude(error=anthropic.AnthropicError("no credentials")).generate_text("sys", "prompt")


def test_gemini_network_error_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="request failed"):
        _gemini(error=httpx.ConnectError("connection refused")).generate_text("sys", "prompt")


def test_claude_missing_credentials_become_llm_error() -> None:
    error = TypeError("Could not resolve authentication method")
    with pytest.raises(LLMError, match="could not be sent"):
        _claude(error=error).generate_text("sys", "prompt")


def test_claude_unparseable_structured_output_becomes_llm_error() -> None:
    try:
        Diagnosis.model_validate_json('{"failure_type": "none"')  # truncated JSON
    except ValidationError as exc:
        error = exc
    with pytest.raises(LLMError, match="does not match the schema"):
        _claude(error=error).generate_structured("sys", "prompt", Diagnosis)


# --- Gemini quota (429) handling -------------------------------------------------------

DAILY_429 = "Quota exceeded for metric: ...requests per day... Please retry in 15h5m47.43s."
MINUTE_429 = "Quota exceeded for metric: ...requests per minute... Please retry in 12.5s."


def _gemini_sequence(outcomes: list[Any]) -> tuple[GeminiProvider, list[int]]:
    """Each call pops the next outcome: an exception to raise or a response to return."""
    calls: list[int] = []

    def generate_content(**kwargs: Any) -> Any:
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiProvider(model="gemini-test", client=client), calls  # type: ignore[arg-type]


def _quota_error(message: str) -> errors.ClientError:
    return errors.ClientError(429, {"error": {"message": message, "status": "RESOURCE_EXHAUSTED"}})


def test_daily_quota_stops_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("postback_debugger.llm.gemini.time.sleep", sleeps.append)
    provider, calls = _gemini_sequence([_quota_error(DAILY_429)])

    with pytest.raises(QuotaExceededError, match=r"about 15\.1 h"):
        provider.generate_text("sys", "prompt")
    assert calls == [1] and sleeps == []


def test_minute_quota_waits_once_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("postback_debugger.llm.gemini.time.sleep", sleeps.append)
    provider, calls = _gemini_sequence([_quota_error(MINUTE_429), _gemini_response("hi")])

    assert provider.generate_text("sys", "prompt").text == "hi"
    assert sleeps == [12.5] and len(calls) == 2


def test_minute_quota_twice_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("postback_debugger.llm.gemini.time.sleep", lambda s: None)
    provider, calls = _gemini_sequence([_quota_error(MINUTE_429), _quota_error(MINUTE_429)])

    with pytest.raises(QuotaExceededError):
        provider.generate_text("sys", "prompt")
    assert len(calls) == 2


def test_configured_default_model_comes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from postback_debugger.llm import _models

    monkeypatch.setenv("X_MODELS", "a, b ,c")
    monkeypatch.setenv("X_MODEL", "c")
    assert _models("X_MODELS", "X_MODEL", ("z",)) == ("c", "a", "b")

    monkeypatch.setenv("X_MODELS", " , ")
    monkeypatch.setenv("X_MODEL", "")
    assert _models("X_MODELS", "X_MODEL", ("z", "y")) == ("z", "y")

    monkeypatch.setenv("X_MODEL", "custom")
    assert _models("X_MODELS", "X_MODEL", ("z",)) == ("custom", "z")
