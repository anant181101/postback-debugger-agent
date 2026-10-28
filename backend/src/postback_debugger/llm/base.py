"""Provider-neutral types for LLM calls: results, token usage, cost and the provider protocol."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """The model call failed or did not return a usable answer."""


class QuotaExceededError(LLMError):
    """The provider's quota is used up for longer than is worth waiting; stop calling it."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s  # when the provider says the quota resets


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int  # everything billed as output, thinking included
    thinking_tokens: int = 0  # the part of output_tokens spent on thinking, when reported


@dataclass(frozen=True)
class Price:
    input_per_mtok: float  # USD per million tokens
    output_per_mtok: float


# Standard paid-tier prices. Models missing here (for example Gemini on the free tier)
# report no cost.
PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(4.00, 20.00),
    "claude-sonnet-5-5": Price(2.00, 10.00),
    "claude-haiku-5-5": Price(0.10, 0.50),
}


def cost_usd(model: str, usage: Usage) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok
    ) / 1_000_000


@dataclass(frozen=True)
class TextResult:
    text: str
    model: str  # model version that actually served the request
    usage: Usage
    cost_usd: float | None
    latency_ms: int


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    data: T
    model: str
    usage: Usage
    cost_usd: float | None
    latency_ms: int


class LLMProvider(Protocol):
    """What the rest of the app needs from a model provider."""

    name: str
    model: str

    def generate_text(self, system: str, prompt: str) -> TextResult: ...

    def generate_structured[T: BaseModel](
        self, system: str, prompt: str, schema: type[T]
    ) -> StructuredResult[T]: ...
