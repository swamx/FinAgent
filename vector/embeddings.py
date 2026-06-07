import time

from openai import OpenAI

from core.config import settings
from observability.metrics import embed_duration, embed_errors
from observability.tracing import traced

# Reuses the LiteLLM proxy so embeddings are routed through the same
# gateway as chat completions — one place to swap models/keys.
_client = OpenAI(
    api_key=settings.litellm_api_key,
    base_url=settings.litellm_base_url,
)


@traced("embed.create", model="nomic-embed-text")
def embed(text: str) -> list[float]:
    t0 = time.time()
    try:
        result = _client.embeddings.create(
            model=settings.embedding_model,
            input=text,
        )
        embed_duration.record(time.time() - t0)
        return result.data[0].embedding
    except Exception:
        embed_errors.add(1)
        raise
