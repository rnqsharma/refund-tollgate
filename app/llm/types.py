"""Plain data types shared by every LLM client. No provider specifics live here."""

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.tokens_in + other.tokens_in, self.tokens_out + other.tokens_out)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[Message, ...]
    # None means "use the client's default model".
    model: str | None = None
    # Zero keeps decisions as repeatable as the provider allows.
    temperature: float = 0.0
    max_tokens: int = 1024
    # Ask the provider for a JSON object. Not every model honours it, so callers still validate.
    json_mode: bool = False


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    # Which provider answered and with which model; recorded on the run_steps row.
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0


class LLMError(Exception):
    """A provider call failed. `retryable` says whether trying again could help."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class StructuredOutputError(Exception):
    """The model never produced output that passes the schema, even after repair attempts."""

    def __init__(self, message: str, *, attempts: int, usage: Usage) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.usage = usage
