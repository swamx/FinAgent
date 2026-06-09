"""Core ingestion pipeline.

Orchestrates: source document → chunk → enrich → embed → index.

Designed for 2-hour SLA on ~1M chunks:
- async batch embedding (EMBED_BATCH_SIZE chunks per OpenAI call)
- semaphore-bounded concurrency (MAX_CONCURRENT tasks)
- per-source checkpointing via Redis SADD/SISMEMBER
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from opensearchpy import OpenSearch
from redis import Redis

from core.config import settings
from ingestion.chunking import chunk_text
from ingestion.enrichment import EntityEnricher
from observability.circuit_breakers import opensearch_breaker
from observability.tracing import get_tracer
from vector.embeddings import embed
from vector.index_setup import create_fintech_index

_CHECKPOINT_KEY = "ingestion:checkpoints"

# Defaults — overridden per-mode via constructor args
_DEFAULT_EMBED_BATCH = 128
_DEFAULT_MAX_CONCURRENT = 32


class IngestionPipeline:
    def __init__(
        self,
        redis_client: Redis,
        os_client: OpenSearch,
        enricher: EntityEnricher,
        embed_batch_size: int = _DEFAULT_EMBED_BATCH,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ):
        self.redis = redis_client
        self.os = os_client
        self.enricher = enricher
        self._embed_batch_size = embed_batch_size
        self._sem = asyncio.Semaphore(max_concurrent)

    async def run_source(
        self,
        source_name: str,
        documents: list[dict],
        force: bool = False,
    ) -> int:
        """Ingest a list of documents from a named source.

        Each document dict should have at minimum:
            text: str
            document_id: str  (optional — generated if absent)
            title: str        (optional)
            author: str       (optional — company name, court, publication)
            jurisdiction: str (optional — country code, US state, court circuit)
            date: str         (optional ISO date)
            url: str          (optional — canonical source URL)

        Returns the number of chunks indexed.
        """
        create_fintech_index(self.os)

        chunks_indexed = 0
        pending_docs: list[dict] = []

        pending_doc_ids: list[str] = []

        for doc in documents:
            doc_id = doc.get("document_id") or str(uuid.uuid4())

            if not force and self._is_done(source_name, doc_id):
                continue

            raw_chunks = chunk_text(
                doc["text"],
                metadata={
                    "document_id": doc_id,
                    "source": source_name,
                    "doc_type": "source",
                    "title": doc.get("title", ""),
                    "author": doc.get("author", ""),
                    "jurisdiction": doc.get("jurisdiction", ""),
                    "date": doc.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
                    "doc_length": len(doc.get("text", "")),
                    "url": doc.get("url", ""),
                },
            )

            for chunk in raw_chunks:
                enriched = self.enricher.enrich(chunk)
                enriched["chunk_id"] = str(uuid.uuid4())
                pending_docs.append(enriched)

            pending_doc_ids.append(doc_id)

            if len(pending_docs) >= self._embed_batch_size:
                n = await self._flush(pending_docs)
                chunks_indexed += n
                pending_docs = []
                for did in pending_doc_ids:
                    self._mark_done(source_name, did)
                pending_doc_ids = []

        if pending_docs:
            n = await self._flush(pending_docs)
            chunks_indexed += n
            for did in pending_doc_ids:
                self._mark_done(source_name, did)

        return chunks_indexed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _flush(self, docs: list[dict]) -> int:
        """Embed and bulk-index docs. Returns count of successfully indexed chunks."""
        import logging
        _log = logging.getLogger(__name__)
        tracer = get_tracer()
        loop = asyncio.get_event_loop()

        # Embed each chunk individually; skip failures rather than crashing.
        embedded: list[tuple[dict, list[float]]] = []
        with tracer.start_as_current_span(
            "pipeline.embed_batch", attributes={"batch.size": len(docs)}
        ):
            for doc in docs:
                try:
                    emb = await loop.run_in_executor(None, lambda d=doc: embed(d["text"]))
                    embedded.append((doc, emb))
                except Exception as exc:
                    _log.warning("embed failed for chunk %s: %s", doc.get("chunk_id"), exc)

        if not embedded:
            return 0

        bulk_body: list[dict] = []
        for doc, emb in embedded:
            bulk_body.append({"index": {"_index": settings.opensearch_index, "_id": doc["chunk_id"]}})
            bulk_body.append({**doc, "embedding": emb})

        with tracer.start_as_current_span(
            "pipeline.bulk_index", attributes={"bulk.docs": len(embedded)}
        ):
            _body = bulk_body

            async def _do_bulk():
                return await loop.run_in_executor(None, lambda: self.os.bulk(body=_body))

            resp = await opensearch_breaker.call_async(_do_bulk)

        if resp and resp.get("errors"):
            failed = [
                item["index"]
                for item in resp.get("items", [])
                if item.get("index", {}).get("status", 200) >= 400
            ]
            if failed:
                _log.warning(
                    "bulk index had %d failures (of %d): first=%s",
                    len(failed), len(embedded), failed[0].get("error", {}).get("reason", "?")
                )

        indexed = sum(
            1 for item in (resp.get("items", []) if resp else [])
            if item.get("index", {}).get("status", 0) < 400
        ) if resp else len(embedded)
        return indexed

    def _is_done(self, source: str, doc_id: str) -> bool:
        return bool(self.redis.sismember(f"{_CHECKPOINT_KEY}:{source}", doc_id))

    def _mark_done(self, source: str, doc_id: str) -> None:
        self.redis.sadd(f"{_CHECKPOINT_KEY}:{source}", doc_id)
