from opensearchpy import OpenSearch

from core.config import settings

# Fields added on top of an existing index (safe — OpenSearch allows adding new
# mapped fields to a live index without reindex). knn_vector and settings
# cannot be changed after creation, so those live in the create-only block.
_NEW_PROPERTIES: dict = {
    # BM25 target fields — multi-field so both text-search and keyword ops work:
    #   title         → full-text BM25 match + title.keyword for exact/sort
    #   author        → BM25 + author.keyword for facets
    #   jurisdiction  → keyword only (exact boost, filter, aggregation)
    #   doc_length    → integer for length-normalisation signals
    #   url           → keyword (stored, not analysed)
    "title": {
        "type": "text",
        "analyzer": "english",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
    },
    "author": {
        "type": "text",
        "analyzer": "english",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
    },
    "jurisdiction": {"type": "keyword"},
    "doc_length":   {"type": "integer"},
    "url":          {"type": "keyword"},
}


def create_fintech_index(client: OpenSearch) -> None:
    """Idempotent — safe to call on every startup.

    Creates the index the first time; on subsequent calls adds any new
    field mappings that are missing (e.g. after a schema migration).
    knn_vector and index-level settings are set only at creation time.
    """
    if not client.indices.exists(index=settings.opensearch_index):
        client.indices.create(
            index=settings.opensearch_index,
            body={
                "settings": {
                    "index": {
                        "knn": True,
                        "knn.algo_param.ef_search": 512,
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                    }
                },
                "mappings": {
                    "properties": {
                        "chunk_id":     {"type": "keyword"},
                        "document_id":  {"type": "keyword"},
                        "doc_type":     {"type": "keyword"},
                        "source":       {"type": "keyword"},
                        "date":         {
                            "type": "date",
                            "format": "yyyy-MM-dd||epoch_millis||strict_date_optional_time",
                        },
                        "text":         {"type": "text", "analyzer": "english"},
                        "entity_ids":   {"type": "keyword"},
                        "entity_names": {"type": "keyword"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": settings.embedding_dimensions,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib",
                                "parameters": {"m": 16, "ef_construction": 256},
                            },
                        },
                        "mentions": {
                            "type": "nested",
                            "properties": {
                                "start":       {"type": "integer"},
                                "end":         {"type": "integer"},
                                "entity_id":   {"type": "keyword"},
                                "entity_name": {"type": "keyword"},
                            },
                        },
                        **_NEW_PROPERTIES,
                    }
                },
            },
        )
        print(f"Created OpenSearch index: {settings.opensearch_index}")
    else:
        # Add new fields to an existing index (no-op if already present).
        client.indices.put_mapping(
            index=settings.opensearch_index,
            body={"properties": _NEW_PROPERTIES},
        )
