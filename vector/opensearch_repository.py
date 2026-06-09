from __future__ import annotations

from opensearchpy import OpenSearch

from core.config import settings
from core.models import Document


class OpenSearchRepository:
    def __init__(self, client: OpenSearch):
        self.client = client
        self.index = settings.opensearch_index

    def index_chunk(
        self,
        doc_id: str,
        text: str,
        embedding: list[float],
        entity_ids: list[str],
        *,
        source: str = "",
        title: str = "",
        author: str = "",
        jurisdiction: str = "",
        date: str = "",
        doc_length: int = 0,
        url: str = "",
    ) -> None:
        self.client.index(
            index=self.index,
            id=doc_id,
            body={
                "text": text,
                "embedding": embedding,
                "entity_ids": entity_ids,
                "source": source,
                "title": title,
                "author": author,
                "jurisdiction": jurisdiction,
                "date": date or None,
                "doc_length": doc_length,
                "url": url,
            },
        )

    def search(self, embedding: list[float], k: int = 10) -> list[Document]:
        body = {
            "size": k,
            "query": {"knn": {"embedding": {"vector": embedding, "k": k}}},
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def search_by_entities(
        self,
        entity_ids: list[str],
        embedding: list[float],
        k: int = 20,
    ) -> list[Document]:
        body = {
            "size": k,
            "query": {
                "bool": {
                    "must": {"knn": {"embedding": {"vector": embedding, "k": k}}},
                    "filter": [{"terms": {"entity_ids": entity_ids}}],
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def get_entity_profiles(
        self,
        entity_ids: list[str],
        k: int = 5,
    ) -> list[Document]:
        """Fetch pre-indexed graph_profile documents for resolved entity IDs (no kNN).

        Called by RetrievalService to surface rich entity context (datasets, PEP flag)
        even when the hybrid kNN search misses the profile doc.
        """
        body = {
            "size": k,
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"entity_ids": entity_ids}},
                        {"term": {"source": "graph_profile"}},
                    ]
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def search_by_entity_names(
        self,
        entity_names: list[str],
        k: int = 5,
    ) -> list[Document]:
        """BM25 text search on entity_names field for names GLiNER extracted
        but could not map to a graph ID. Supplements kNN fallback."""
        body = {
            "size": k,
            "query": {
                "bool": {
                    "filter": [{"term": {"source": "graph_profile"}}],
                    "must": [{
                        "multi_match": {
                            "query": " ".join(entity_names),
                            "fields": ["entity_names", "text"],
                            "type": "best_fields",
                        }
                    }],
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def search_hybrid(
        self,
        entity_ids: list[str],
        embedding: list[float],
        query_text: str,
        k: int = 20,
        jurisdiction: str | None = None,
        title_boost: float = 2.0,
        author_boost: float = 0.6,
        jurisdiction_boost: float = 1.5,
    ) -> list[Document]:
        """BM25 + kNN hybrid.

        kNN is the MUST (minimum match requirement), BM25 on title/author/
        jurisdiction are SHOULD clauses that adjust the final score upward
        when the query text appears in those metadata fields.  The entity
        filter is applied as a hard FILTER so it doesn't affect scoring.

        Replacing cosine-only: swap search_by_entities → search_hybrid in
        retriever.py.  To fall back to pure kNN, set title_boost=0.
        """
        should: list[dict] = [
            {"match": {"title":  {"query": query_text, "boost": title_boost}}},
            {"match": {"author": {"query": query_text, "boost": author_boost}}},
        ]
        if jurisdiction:
            should.append(
                {"term": {"jurisdiction": {"value": jurisdiction, "boost": jurisdiction_boost}}}
            )

        body = {
            "size": k,
            "query": {
                "bool": {
                    "must":   {"knn": {"embedding": {"vector": embedding, "k": k}}},
                    "filter": [{"terms": {"entity_ids": entity_ids}}],
                    "should": should,
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def _hits(self, result: dict) -> list[Document]:
        return [
            Document(
                id=hit["_id"],
                text=hit["_source"].get("text", ""),
                source=hit["_source"].get("source") or None,
                title=hit["_source"].get("title") or None,
                author=hit["_source"].get("author") or None,
                jurisdiction=hit["_source"].get("jurisdiction") or None,
                date=hit["_source"].get("date") or None,
                doc_length=hit["_source"].get("doc_length", 0),
                url=hit["_source"].get("url") or None,
                entity_ids=hit["_source"].get("entity_ids", []),
                score=hit["_score"],
            )
            for hit in result["hits"]["hits"]
        ]
