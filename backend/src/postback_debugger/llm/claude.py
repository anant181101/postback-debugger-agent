"""Claude provider, using the Anthropic SDK. Reads ANTHROPIC_API_KEY from the environment."""

import os
import time
from collections.abc import Callable
from typing import Any

import anthropic
from anthropic.types import Message
from pydantic import BaseModel, ValidationError

from postback_debugger.llm.base import LLMError, StructuredResult, TextResult, Usage, cost_usd

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str | None = None, client: anthropic.Anthropic | None = None) -> None:
        self.model = model or os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
        self._client = client or anthropic.Anthropic()

    def generate_text(self, system: str, prompt: str) -> TextResult:
        response, latency_ms = self._call(self._client.messages.create, system, prompt)
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise LLMError("Claude returned no text")
        usage = _usage(response)
        return TextResult(
            text=text,
            model=response.model,
            usage=usage,
            cost_usd=cost_usd(self.model, usage),
            latency_ms=latency_ms,
        )

    def generate_structured[T: BaseModel](
        self, system: str, prompt: str, schema: type[T]
    ) -> StructuredResult[T]:
        response, latency_ms = self._call(
            self._client.messages.parse, system, prompt, output_format=schema
        )
        if response.parsed_output is None:
            raise LLMError(f"Claude returned no {schema.__name__}")
        usage = _usage(response)
        return StructuredResult(
            data=response.parsed_output,
            model=response.model,
            usage=usage,
            cost_usd=cost_usd(self.model, usage),
            latency_ms=latency_ms,
        )

    def _call(
        self, method: Callable[..., Any], system: str, prompt: str, **kwargs: Any
    ) -> tuple[Any, int]:
        start = time.perf_counter()
        try:
            response = method(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
        except anthropic.AnthropicError as exc:  # API and connection errors
            raise LLMError(f"Claude API error: {exc}") from exc
        except TypeError as exc:  # raised by the SDK when no credentials are configured
            if "authentication" not in str(exc):
                raise  # a real programming error: do not hide it
            raise LLMError(f"Claude request could not be sent: {exc}") from exc
        except ValidationError as exc:  # parse() output that is truncated, refused or off-schema
            raise LLMError(f"{self.model} returned output that does not match the schema") from exc
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined the request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"Claude hit max_tokens={MAX_TOKENS} before finishing")
        return response, round((time.perf_counter() - start) * 1000)


def _usage(response: Message) -> Usage:
    details = response.usage.output_tokens_details
    return Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        thinking_tokens=details.thinking_tokens if details else 0,
    )
