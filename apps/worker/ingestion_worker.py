"""Ingestion worker — run once (or on a schedule) to populate OpenSearch.

Runs all 5 sources in parallel then hands off to the profile builder.

Mode is controlled by the INGEST_MODE environment variable:
  INGEST_MODE=small  (default) — ~4 500 docs,  20-40 min
  INGEST_MODE=full             — ~50 000 docs,  2-4 h

Usage:
    python -m apps.worker.ingestion_worker
    INGEST_MODE=full python -m apps.worker.ingestion_worker
"""
from __future__ import annotations

import asyncio
import os
import time

from opensearchpy import OpenSearch
from redis import Redis

from core.config import settings
from ingestion.modes import MODES, IngestMode
from observability.setup import setup_telemetry
from observability.metrics import docs_ingested, chunks_indexed, ingest_duration
from observability.tracing import get_tracer
from ingestion.entity_extraction import HybridEntityExtractor
from ingestion.enrichment import EntityEnricher
from ingestion.pipeline import IngestionPipeline
from ingestion.sources.sec import fetch_sec_filings
from ingestion.sources.courtlistener import fetch_opinions
from ingestion.sources.icij import fetch_icij_documents
from ingestion.sources.procurement import fetch_contracts
from ingestion.sources.news import fetch_news_articles


def _resolve_mode() -> IngestMode:
    key = os.environ.get("INGEST_MODE", "small").strip().lower()
    mode = MODES.get(key)
    if mode is None:
        print(f"Unknown INGEST_MODE={key!r}, defaulting to 'small'. Valid: {list(MODES)}")
        mode = MODES["small"]
    print(f"Ingest mode: {key.upper()} "
          f"(SEC={mode.sec_max_docs}, Court={mode.court_max_docs}, "
          f"ICIJ={mode.icij_max_docs}, Procurement={mode.procurement_max_docs}, "
          f"News={mode.news_max_docs})")
    return mode


def _build_pipeline(mode: IngestMode) -> IngestionPipeline:
    redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
    )
    os_client = OpenSearch(
        [{"host": settings.opensearch_host, "port": settings.opensearch_port}],
        maxsize=10,
    )
    extractor = HybridEntityExtractor(use_gliner=True)
    enricher  = EntityEnricher(redis, extractor)

    print("Warming entity name cache from graph…")
    enricher.warm_cache()

    return IngestionPipeline(
        redis, os_client, enricher,
        embed_batch_size=mode.embed_batch_size,
        max_concurrent=mode.max_concurrent,
    )


async def run() -> None:
    setup_telemetry("finagent-worker")
    tracer = get_tracer()
    mode   = _resolve_mode()

    pipeline = _build_pipeline(mode)
    t0       = time.time()

    with tracer.start_as_current_span("ingestion.fetch_all"):
        print("Fetching from all 5 sources in parallel…")
        sec_docs, court_docs, icij_docs, procurement_docs, news_docs = await asyncio.gather(
            fetch_sec_filings(
                days_back=mode.sec_days_back,
                max_docs=mode.sec_max_docs,
            ),
            fetch_opinions(
                max_docs=mode.court_max_docs,
            ),
            fetch_icij_documents(
                max_docs=mode.icij_max_docs,
            ),
            fetch_contracts(
                max_docs=mode.procurement_max_docs,
            ),
            fetch_news_articles(
                max_docs=mode.news_max_docs,
                fetch_full_text=mode.news_full_text,
            ),
        )

    sources = [
        ("sec",           sec_docs),
        ("courtlistener", court_docs),
        ("icij",          icij_docs),
        ("procurement",   procurement_docs),
        ("news",          news_docs),
    ]

    total = 0
    for source_name, docs in sources:
        print(f"[{source_name}] Ingesting {len(docs)} documents…")
        docs_ingested.add(len(docs), {"source": source_name})
        t_src = time.time()
        with tracer.start_as_current_span(
            "ingestion.run_source", attributes={"source": source_name}
        ):
            n = await pipeline.run_source(source_name, docs)
        chunks_indexed.add(n, {"source": source_name})
        ingest_duration.record(time.time() - t_src, {"source": source_name})
        print(f"[{source_name}] Indexed {n} chunks.")
        total += n

    elapsed = time.time() - t0
    print(f"\nIngestion complete: {total} chunks in {elapsed / 60:.1f} minutes.")

    from apps.worker.profile_builder import ProfileBuilder
    builder = ProfileBuilder(
        Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True, max_connections=20),
        OpenSearch([{"host": settings.opensearch_host, "port": settings.opensearch_port}], maxsize=10),
    )
    print("Building entity and exposure profiles…")
    await builder.run()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run())
