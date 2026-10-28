"""Gemini provider, using the google-genai SDK. Reads GEMINI_API_KEY from the environment."""

import os
import re
import time

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from postback_debugger.llm.base import (
    LLMError,
    QuotaExceededError,
    StructuredResult,
    TextResult,
    Usage,
    cost_usd,
)

DEFAULT_MODEL = "gemini-3.5-flash"
# Free-tier models are often overloaded (503): retry with backoff. 429 (quota) is handled in
# _generate instead, because a daily quota cannot be fixed by retrying a few seconds later.
RETRY = types.HttpRetryOptions(attempts=4, initial_delay=2.0, http_status_codes=[500, 503])
# A per-minute 429 says "retry in 20s": worth waiting once. A daily one says "retry in 15h".
MAX_QUOTA_WAIT_S = 60.0
RETRY_IN = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s")


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None, client: genai.Client | None = None) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        if client is None:
            try:
                client = genai.Client(http_options=types.HttpOptions(retry_options=RETRY))
            except ValueError as exc:  # raised when no API key is configured
                raise LLMError(f"Gemini client not configured: {exc}") from exc
        self._client = client

    def generate_text(self, system: str, prompt: str) -> TextResult:
        config = types.GenerateContentConfig(system_instruction=system)
        response, latency_ms = self._generate(prompt, config)
        usage = _usage(response)
        return TextResult(
            text=_text(response),
            model=response.model_version or self.model,
            usage=usage,
            cost_usd=cost_usd(self.model, usage),
            latency_ms=latency_ms,
        )

    def generate_structured[T: BaseModel](
        self, system: str, prompt: str, schema: type[T]
    ) -> StructuredResult[T]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
        )
        response, latency_ms = self._generate(prompt, config)
        try:
            data = schema.model_validate_json(_text(response))
        except ValidationError as exc:
            raise LLMError(
                f"{self.model} returned JSON that does not match {schema.__name__}"
            ) from exc
        usage = _usage(response)
        return StructuredResult(
            data=data,
            model=response.model_version or self.model,
            usage=usage,
            cost_usd=cost_usd(self.model, usage),
            latency_ms=latency_ms,
        )

    def _generate(
        self, prompt: str, config: types.GenerateContentConfig
    ) -> tuple[types.GenerateContentResponse, int]:
        waited = False
        while True:
            start = time.perf_counter()
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return response, round((time.perf_counter() - start) * 1000)
            except errors.APIError as exc:
                if exc.code != 429:
                    raise LLMError(
                        f"Gemini API error {exc.code} {exc.status}: {exc.message}"
                    ) from exc
                wait = _retry_after_seconds(str(exc.message))
                if waited or wait is None or wait > MAX_QUOTA_WAIT_S:
                    raise QuotaExceededError(_quota_message(self.model, wait), wait) from exc
                time.sleep(wait)  # per-minute limit: wait it out once
                waited = True
            except httpx.HTTPError as exc:  # timeouts and connection errors left after retries
                raise LLMError(f"Gemini request failed: {exc!r}") from exc


def _retry_after_seconds(message: str) -> float | None:
    match = RETRY_IN.search(message)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds)


def _quota_message(model: str, wait: float | None) -> str:
    when = f"in about {wait / 3600:.1f} h" if wait and wait >= 3600 else "later"
    return (
        f"Gemini quota exceeded for {model}. Try again {when}, set GEMINI_MODEL to another "
        "model (quotas are per model; see https://ai.dev/rate-limit), "
        "or use --provider claude."
    )


def _text(response: types.GenerateContentResponse) -> str:
    if not response.text:
        reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
        raise LLMError(f"Gemini returned no text (finish_reason={reason})")
    return response.text


def _usage(response: types.GenerateContentResponse) -> Usage:
    meta = response.usage_metadata
    if meta is None:
        return Usage(input_tokens=0, output_tokens=0)
    thinking = meta.thoughts_token_count or 0
    return Usage(
        input_tokens=meta.prompt_token_count or 0,
        output_tokens=(meta.candidates_token_count or 0) + thinking,
        thinking_tokens=thinking,
    )
