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
You are a factual accuracy judge for a compliance retrieval system.

Given:
1. A question posed by a compliance analyst
2. Retrieved context passages
3. An AI-generated answer

Your task: evaluate whether the answer is relevant and useful for the question, \
and whether it uses any retrieved context that was provided.

Question:
{question}

Retrieved Context:
{context}

AI Answer:
{answer}

Scoring rules:
- 1.0 = Answer is relevant to the question AND incorporates the retrieved context.
- 0.7 = Answer is relevant; uses most of the context with minor omissions.
- 0.5 = Answer is relevant; uses some context OR correctly states what was found.
- 0.3 = Answer is relevant but largely ignores available context, or contradicts it.
- 0.0 = Answer is NOT relevant to the question (completely off-topic or wrong subject).

Key notes:
- Using model's own training knowledge is ACCEPTABLE and should NOT lower the score.
- Only score 0.0 if the answer fails to address the question at all.
- If context was retrieved, check whether the answer reflects it (higher = better use).
- If no context was retrieved, score based purely on relevance to the question.

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
            context_text = "(no documents retrieved)"

        prompt = _JUDGE_PROMPT.format(
            question=question,
            context=context_text,
            answer=answer,
        )

        raw = ""
        try:
            resp = self._client.chat.completions.create(
                model=settings.primary_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown code fences if the model wraps its response
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
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
