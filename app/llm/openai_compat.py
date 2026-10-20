"""A client for any provider that speaks the OpenAI chat-completions protocol.

Groq, OpenAI, vLLM and Ollama all do, so one small httpx client covers them. Only the
base URL, key and default model differ.
"""

import time

import httpx

from app.llm.types import LLMError, LLMRequest, LLMResponse, Usage


class OpenAICompatClient:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self._model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._model
        body: dict = {
            "model": model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            resp = await self._http.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            # Timeouts, refused connections, dropped sockets: the next attempt may well work.
            raise LLMError(f"{self.name}: {type(exc).__name__}", retryable=True) from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise LLMError(f"{self.name}: HTTP {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise LLMError(
                f"{self.name}: HTTP {resp.status_code}: {_error_message(resp)}", retryable=False
            )

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError("content is not a string")
            usage = data.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens", 0))
            tokens_out = int(usage.get("completion_tokens", 0))
            answered_by = str(data.get("model") or model)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # A reply with the wrong shape is the provider's fault; another provider may do better.
            raise LLMError(f"{self.name}: malformed response ({exc})", retryable=True) from exc

        return LLMResponse(
            text=text,
            provider=self.name,
            model=answered_by,
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _error_message(resp: httpx.Response) -> str:
    """Pull the provider's own error message, capped, without echoing the whole body."""
    try:
        message = resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return "no error message"
    return str(message)[:200]
