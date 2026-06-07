"""Publish eval scores to OTel metrics and stdout."""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_RAGAS_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def report_scores(ragas_scores: dict[str, float], hallucination_rate: float) -> None:
    """Write eval scores to OTel observable gauge and log them.

    The observable gauge (finagent.eval.score) is Prometheus-scraped by
    the otel-lgtm collector and surfaced in the FinAgent Evals dashboard.
    """
    try:
        from observability.metrics import set_eval_score

        for key in _RAGAS_KEYS:
            if key in ragas_scores:
                set_eval_score(key, ragas_scores[key])
                _log.info("eval.%s = %.3f", key, ragas_scores[key])

        set_eval_score("hallucination_rate", hallucination_rate)
        _log.info("eval.hallucination_rate = %.3f", hallucination_rate)

    except Exception as exc:
        _log.error("Failed to publish eval scores: %s", exc)

    # Always print a human-readable summary regardless of OTel availability
    print("\n─── Eval Results ─────────────────────────────────────────────")
    for key in _RAGAS_KEYS:
        if key in ragas_scores:
            bar = "█" * int(ragas_scores[key] * 20)
            print(f"  {key:<22} {ragas_scores[key]:.3f}  {bar}")
    print(f"  {'hallucination_rate':<22} {hallucination_rate:.3f}")
    print("──────────────────────────────────────────────────────────────\n")
