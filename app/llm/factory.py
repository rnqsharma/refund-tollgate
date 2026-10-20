"""Builds the LLM client from settings: a primary provider with an optional fallback."""


from app.config import Settings
from app.llm.client import FallbackClient, LLMClient
from app.llm.openai_compat import OpenAICompatClient


class LLMNotConfigured(RuntimeError):
    pass


def build_llm_client(settings: Settings) -> LLMClient:
    clients: list[LLMClient] = []
    for name, url, key, model in (
        ("primary", settings.llm_primary_base_url, settings.llm_primary_api_key,
         settings.llm_primary_model),
        ("fallback", settings.llm_fallback_base_url, settings.llm_fallback_api_key,
         settings.llm_fallback_model),
    ):
        if url and key and model:
            clients.append(
                OpenAICompatClient(
                    name=name,
                    base_url=url,
                    api_key=key.get_secret_value(),
                    model=model,
                    timeout_s=settings.llm_timeout_s,
                )
            )
    if not clients:
        raise LLMNotConfigured(
            "set TOLLGATE_LLM_PRIMARY_BASE_URL, _API_KEY and _MODEL to enable model-based stages"
        )
    return clients[0] if len(clients) == 1 else FallbackClient(clients)


