"""Evaluation orchestrator.

Runs the full eval loop:
  1. For each test case, call the FinAgent API to get an answer and contexts.
  2. Run LLM-judge hallucination detection on each (question, contexts, answer).
  3. Run RAGAS evaluation over the full batch.
  4. Export all scores to OTel metrics and print a summary.

Usage:
  python -m eval.runner                      # all cases
  python -m eval.runner --tag sanctions      # cases tagged 'sanctions'
  python -m eval.runner --tag hallucination_trap --api http://api:8000
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

import httpx

from core.config import settings
from eval.hallucination import HallucinationDetector
from eval.test_cases import EVAL_CASES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
_log = logging.getLogger(__name__)


async def _search(client: httpx.AsyncClient, api_base: str, question: str) -> list[str]:
    """Return retrieved context texts.  Empty list on any failure."""
    try:
        resp = await client.post(
            f"{api_base}/search",
            json={"query": question, "limit": 5},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # Tolerate both {"documents": [...]} and list responses
        docs = data.get("documents", data) if isinstance(data, dict) else data
        return [d.get("text", d.get("content", "")) for d in docs if isinstance(d, dict)]
    except Exception as exc:
        _log.warning("search failed for %r: %s", question[:60], exc)
        return []


async def _chat(client: httpx.AsyncClient, api_base: str, question: str) -> str:
    """Return the agent answer.  Empty string on any failure."""
    try:
        resp = await client.post(
            f"{api_base}/chat",
            json={"message": question},
            timeout=360.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("answer", data.get("response", str(data)))
    except Exception as exc:
        _log.warning("chat failed for %r: %s", question[:60], exc)
        return ""


async def run_eval(tag_filter: str | None = None, api_base: str = "http://localhost:8000") -> None:
    from observability.setup import setup_telemetry
    setup_telemetry("finagent-eval")

    cases = EVAL_CASES
    if tag_filter:
        cases = [c for c in cases if tag_filter in c.tags]

    _log.info("Starting eval run: %d cases  tag=%s  api=%s", len(cases), tag_filter, api_base)

    detector = HallucinationDetector()
    results: list[dict] = []

    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases, 1):
            _log.info("[%d/%d] %s", i, len(cases), case.question[:80])

            contexts = await _search(client, api_base, case.question)
            answer   = await _chat(client, api_base, case.question)

            if not answer:
                _log.warning("  → no answer; skipping case")
                continue

            groundedness, reasoning = detector.score(case.question, contexts, answer)
            _log.info("  groundedness=%.2f  %s", groundedness, reasoning)

            results.append({
                "question":     case.question,
                "answer":       answer,
                "contexts":     contexts,
                "reference":    case.reference,
                "groundedness": groundedness,
            })

    if not results:
        _log.warning("No results collected — is the API running at %s?", api_base)
        return

    # ── RAGAS ─────────────────────────────────────────────────────────────
    from eval.ragas_eval import run_ragas
    ragas_scores = run_ragas(
        results,
        litellm_base_url=settings.litellm_base_url,
        litellm_api_key=settings.litellm_api_key,
        model=settings.primary_model,
        embed_model=settings.embedding_model,
    )

    # ── Hallucination rate: fraction of cases with groundedness < 0.6 ─────
    hallucination_rate = sum(
        1 for r in results if r["groundedness"] < 0.6
    ) / len(results)

    # ── Publish scores ────────────────────────────────────────────────────
    from eval.reporter import report_scores
    report_scores(ragas_scores, hallucination_rate)


def main() -> None:
    parser = argparse.ArgumentParser(description="FinAgent eval runner")
    parser.add_argument("--tag", default=None, help="Filter cases by tag (e.g. 'sanctions')")
    parser.add_argument(
        "--api",
        default=os.environ.get("FINAGENT_API_BASE", "http://localhost:8000"),
        help="FinAgent API base URL (default: $FINAGENT_API_BASE or http://localhost:8000)",
    )
    args = parser.parse_args()
    asyncio.run(run_eval(tag_filter=args.tag, api_base=args.api))


if __name__ == "__main__":
    main()
