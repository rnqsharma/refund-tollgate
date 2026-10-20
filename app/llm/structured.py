"""Structured output: ask for JSON, check it against a Pydantic model, and repair if it fails.

Models sometimes return prose around the JSON, a missing field, or an extra one. Rather than
failing the stage, this feeds the validation errors back and asks again, a bounded number
of times. Provider failures (LLMError) are not repaired here: they propagate to the caller.
"""

import json
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.client import LLMClient
from app.llm.types import LLMRequest, Message, Role, StructuredOutputError, Usage

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_MAX_ERRORS_SHOWN = 10


@dataclass(frozen=True, slots=True)
class StructuredResult(Generic[T]):
    value: T
    attempts: int
    usage: Usage
    provider: str
    model: str

    @property
    def repairs(self) -> int:
        return self.attempts - 1


def schema_instruction(model_cls: type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema(), separators=(",", ":"))
    return (
        "Reply with a single JSON object and nothing else, matching this JSON Schema. "
        "Do not add fields the schema does not list.\n" + schema
    )


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


def _describe(error: ValidationError) -> str:
    """Summarise validation errors for the model. Field paths and reasons only: never the
    offending values, which may hold customer text."""
    lines = []
    for item in error.errors(include_input=False, include_url=False, include_context=False)[
        :_MAX_ERRORS_SHOWN
    ]:
        path = ".".join(str(part) for part in item["loc"]) or "(whole reply)"
        lines.append(f"- {path}: {item['msg']}")
    return "\n".join(lines)


async def run_structured(
    client: LLMClient,
    model_cls: type[T],
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_repairs: int = 2,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> StructuredResult[T]:
    """Return a validated `model_cls`, or raise StructuredOutputError.

    One initial attempt plus up to `max_repairs` corrections, so at most max_repairs + 1 calls.
    """
    messages = [
        Message(Role.SYSTEM, f"{system}\n\n{schema_instruction(model_cls)}"),
        Message(Role.USER, user),
    ]
    total = Usage()
    last_problem = ""

    for attempt in range(1, max_repairs + 2):
        response = await client.complete(
            LLMRequest(
                messages=tuple(messages),
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )
        )
        total = total + response.usage
        try:
            value = model_cls.model_validate_json(_strip_fences(response.text))
        except ValidationError as exc:
            last_problem = _describe(exc)
            messages.append(Message(Role.ASSISTANT, response.text))
            messages.append(
                Message(
                    Role.USER,
                    "Your reply did not match the schema:\n"
                    f"{last_problem}\n"
                    "Reply again with only the corrected JSON object.",
                )
            )
            continue
        return StructuredResult(
            value=value,
            attempts=attempt,
            usage=total,
            provider=response.provider,
            model=response.model,
        )

    raise StructuredOutputError(
        f"no valid {model_cls.__name__} after {max_repairs + 1} attempts; last problems:\n"
        f"{last_problem}",
        attempts=max_repairs + 1,
        usage=total,
    )
