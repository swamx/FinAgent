"""RAGAS evaluation integration.

Computes Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
over a batch of eval results.  Requires `ragas` and `langchain-openai`
packages; returns an empty dict (with a warning) if unavailable.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)


def run_ragas(
    results: list[dict],
    litellm_base_url: str,
    litellm_api_key: str,
    model: str,
    embed_model: str,
) -> dict[str, float]:
    """Run RAGAS metrics over provided results and return mean scores.

    Each item in *results* should contain:
        question  : str
        answer    : str
        contexts  : list[str]
        reference : str  (optional; enables Precision / Recall)

    Returns metric_name → mean_float, or {} if RAGAS is unavailable.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate, RunConfig
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as exc:
        _log.warning("RAGAS not available — skipping evaluation (%s)", exc)
        return {}

    # ── Point RAGAS at the LiteLLM proxy ─────────────────────────────────
    os.environ.setdefault("OPENAI_API_BASE", litellm_base_url)
    os.environ.setdefault("OPENAI_API_KEY", litellm_api_key)

    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper

        ragas_llm = LangchainLLMWrapper(ChatOpenAI(
            openai_api_base=litellm_base_url,
            openai_api_key=litellm_api_key,
            model_name=model,
            temperature=0,
        ))
        ragas_emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
            openai_api_base=litellm_base_url,
            openai_api_key=litellm_api_key,
            model=embed_model,
        ))
        for metric in (faithfulness, answer_relevancy, context_precision, context_recall):
            if hasattr(metric, "llm"):
                metric.llm = ragas_llm
            if hasattr(metric, "embeddings"):
                metric.embeddings = ragas_emb
    except ImportError:
        _log.info("langchain_openai unavailable — RAGAS will use OPENAI_* env vars")

    # ── Build HuggingFace Dataset ─────────────────────────────────────────
    has_reference = any(r.get("reference") for r in results)
    data: dict[str, list] = {
        "question": [r["question"] for r in results],
        "answer":   [r["answer"]   for r in results],
        "contexts": [r["contexts"] for r in results],
    }
    if has_reference:
        data["ground_truth"] = [r.get("reference", "") for r in results]

    dataset = Dataset.from_dict(data)
    metrics = [faithfulness, answer_relevancy]
    if has_reference:
        metrics += [context_precision, context_recall]

    try:
        run_cfg = RunConfig(max_workers=4, timeout=120, max_retries=10)
        result = evaluate(dataset, metrics=metrics, run_config=run_cfg)
        scores = {k: float(v) for k, v in result.items() if isinstance(v, (int, float))}
        _log.info("RAGAS scores: %s", scores)
        return scores
    except Exception as exc:
        _log.error("RAGAS evaluate() failed: %s", exc, exc_info=True)
        return {}
