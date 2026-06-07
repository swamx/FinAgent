from __future__ import annotations

import time

from graph.entity_resolver import EntityResolver
from graph.redis_graph_repository import RedisGraphRepository
from vector.embeddings import embed
from vector.opensearch_repository import OpenSearchRepository
from core.models import SearchResult
from observability.metrics import (
    search_duration,
    entities_per_query,
    docs_per_query,
    graph_hits_per_query,
)
from observability.tracing import get_tracer


class RetrievalService:
    def __init__(
        self,
        graph_repo: RedisGraphRepository,
        vector_repo: OpenSearchRepository,
        entity_resolver: EntityResolver,
    ):
        self.graph = graph_repo
        self.vector = vector_repo
        self.resolver = entity_resolver

    def search(self, query: str, limit: int = 10) -> SearchResult:
        tracer = get_tracer()
        t0 = time.time()
        with tracer.start_as_current_span("retrieval.search") as span:
            span.set_attribute("query.text", query[:200])
            span.set_attribute("query.length", len(query))

            # ── 1. Entity resolution (NER + graph lookup) ────────────────
            with tracer.start_as_current_span("retrieval.entity_resolve"):
                entities = self.resolver.extract_and_resolve(query)

            n_entities = len(entities)
            span.set_attribute("retrieval.entities_resolved", n_entities)
            entities_per_query.record(n_entities)

            # ── 2. Graph expansion (2-hop neighbourhood) ─────────────────
            related_ids: list[str] = []
            with tracer.start_as_current_span("retrieval.graph_expand") as g_span:
                for entity in entities:
                    expanded = self.graph.expand_entity(entity.id)
                    related_ids.extend(e.id for e in expanded)
                if not related_ids:
                    related_ids = [e.id for e in entities]
                g_span.set_attribute("retrieval.graph_ids", len(related_ids))

            graph_hits_per_query.record(len(related_ids))

            # ── 3. Embedding ─────────────────────────────────────────────
            with tracer.start_as_current_span("retrieval.embed"):
                embedding = embed(query)

            # ── 4. Vector search (hybrid BM25+kNN when entities found) ───
            with tracer.start_as_current_span("retrieval.vector_search") as v_span:
                if related_ids:
                    docs = self.vector.search_hybrid(
                        entity_ids=related_ids,
                        embedding=embedding,
                        query_text=query,
                        k=limit,
                    )
                    v_span.set_attribute("retrieval.mode", "hybrid_entity_filtered")
                else:
                    docs = self.vector.search(embedding, k=limit)
                    v_span.set_attribute("retrieval.mode", "knn_fallback")
                v_span.set_attribute("retrieval.docs_returned", len(docs))

            n_docs = len(docs)
            span.set_attribute("retrieval.docs_returned", n_docs)
            docs_per_query.record(n_docs)
            elapsed = time.time() - t0
            search_duration.record(elapsed)
            span.set_attribute("retrieval.duration_s", round(elapsed, 3))

            return SearchResult(query=query, entities=entities, documents=docs)
