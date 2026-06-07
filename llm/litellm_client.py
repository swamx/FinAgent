from __future__ import annotations

from openai import OpenAI
from openai.types.chat import ChatCompletion

from core.config import settings


class LiteLLMClient:
    """Thin wrapper around the LiteLLM proxy.

    All business logic stays outside this class — it just handles the
    HTTP call so nothing else imports openai directly.
    """

    def __init__(self, model: str | None = None):
        self._client = OpenAI(
            api_key=settings.litellm_api_key,
            base_url=settings.litellm_base_url,
        )
        self.model = model or settings.primary_model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ) -> ChatCompletion:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        return self._client.chat.completions.create(**kwargs)
