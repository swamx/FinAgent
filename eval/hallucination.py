"""LLM-as-judge hallucination detector.

Uses the LiteLLM proxy to score whether an agent answer is fully grounded
in the retrieved context passages.  Returns a groundedness score:
  1.0 = every claim supported by context
  0.5 = partially supported
  0.0 = contradicts or ignores the context entirely
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from core.config import settings

_log = logging.getLogger(__name__)

_JUDGE_PROMPT = """\
You are a factual accuracy judge for a compliance research system.

Given:
1. A question posed by a compliance analyst
2. Retrieved context passages (the only ground truth available)
3. An AI-generated answer

Rate how well the answer is supported by the provided context.

Question:
{question}

Retrieved Context:
{context}

AI Answer:
{answer}

Scoring scale:
- 1.0 = Every factual claim in the answer is directly supported by the context.
- 0.7 = Most claims supported; minor unsupported details present.
- 0.5 = About half the claims are supported; rest are inferred or generic.
- 0.3 = Few claims supported; significant speculation or hallucination.
- 0.0 = Answer contradicts the context or invents facts not present.

Respond ONLY with a JSON object — no markdown, no extra text:
{{"score": <float 0.0-1.0>, "reasoning": "<one concise sentence>"}}
"""


class HallucinationDetector:
    """Synchronous LLM-judge wrapper."""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=settings.litellm_api_key,
            base_url=settings.litellm_base_url,
        )

    def score(
        self,
        question: str,
        context: list[str],
        answer: str,
    ) -> tuple[float, str]:
        """Return (groundedness_score, reasoning).

        Lower score = more hallucination / less grounded.
        Returns (0.5, <error>) on any failure to preserve eval continuity.
        """
        if not answer.strip():
            return 0.5, "Empty answer — cannot evaluate"

        context_text = "\n\n---\n\n".join(c.strip() for c in context[:5] if c.strip())
        if not context_text:
            return 0.5, "No context retrieved — cannot evaluate groundedness"

        prompt = _JUDGE_PROMPT.format(
            question=question,
            context=context_text,
            answer=answer,
        )

        try:
            resp = self._client.chat.completions.create(
                model=settings.primary_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)
            score = float(data.get("score", 0.5))
            reasoning = str(data.get("reasoning", ""))
            return max(0.0, min(1.0, score)), reasoning
        except json.JSONDecodeError:
            _log.warning("Judge returned non-JSON: %s", raw[:200])
            return 0.5, f"Parse error: {raw[:100]}"
        except Exception as exc:
            _log.error("Hallucination judge failed: %s", exc)
            return 0.5, str(exc)
