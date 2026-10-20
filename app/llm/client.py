"""The client contract, plus the two clients that need no network: a fallback chain and a fake."""

from collections.abc import Sequence
from typing import Protocol

from app.llm.types import LLMError, LLMRequest, LLMResponse, Usage


class LLMClient(Protocol):
    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class FallbackClient:
    """Tries each client in order and returns the first answer.

    Any LLMError moves on to the next provider, including a rejected key: one provider being
    misconfigured should not stop returns from being processed. If every provider fails, the
    error is retryable when at least one of the failures was.
    """

    name = "fallback"

    def __init__(self, clients: Sequence[LLMClient]) -> None:
        if not clients:
            raise ValueError("FallbackClient needs at least one client")
        self._clients = list(clients)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        failures: list[LLMError] = []
        for client in self._clients:
            try:
                return await client.complete(request)
            except LLMError as exc:
                failures.append(exc)
        raise LLMError(
            "all providers failed: " + "; ".join(str(f) for f in failures),
            retryable=any(f.retryable for f in failures),
        )


class FakeClient:
    """A scripted client for tests: each call pops the next reply.

    A reply is either text, or an exception to raise. Every request is kept in `requests`
    so a test can check exactly what the code under test sent.
    """

    name = "fake"

    def __init__(self, replies: Sequence[str | Exception], *, model: str = "fake-model") -> None:
        self._replies = list(replies)
        self._model = model
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("FakeClient was called more times than it has scripted replies")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(
            text=reply,
            provider=self.name,
            model=request.model or self._model,
            usage=Usage(tokens_in=10, tokens_out=5),
        )
