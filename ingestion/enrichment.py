"""Enrichment layer: extracted entities → canonical graph IDs.

For each entity mention in a chunk we:
1. Try an exact-match lookup in RedisGraph (fast path).
2. Fall back to RapidFuzz fuzzy match against a cached name index.
3. If no match → create a new Entity node in the graph.

The chunk's metadata is updated with resolved entity_ids and span offsets
for the UI highlighting feature.
"""
from __future__ import annotations

from redis import Redis
from rapidfuzz import fuzz, process

from ingestion.chunking import Chunk
from ingestion.entity_extraction import ExtractedEntity, HybridEntityExtractor


class EntityEnricher:
    _GRAPH = "entities"
    _FUZZY_THRESHOLD = 80

    def __init__(self, redis_client: Redis, extractor: HybridEntityExtractor):
        self.redis = redis_client
        self.extractor = extractor
        # lazily populated on first use
        self._name_index: dict[str, str] = {}  # name_lower → entity_id

    def enrich(self, chunk: Chunk) -> dict:
        """Return an OpenSearch document dict enriched with entity metadata."""
        entities = self.extractor.extract(chunk.text)

        entity_ids: list[str] = []
        entity_names: list[str] = []
        mentions: list[dict] = []

        for ent in entities:
            entity_id = self._resolve(ent)
            if entity_id:
                entity_ids.append(entity_id)
                entity_names.append(ent.text)
                mentions.append(
                    {
                        "start": ent.start,
                        "end": ent.end,
                        "entity_id": entity_id,
                        "entity_name": ent.text,
                    }
                )

        return {
            "text": chunk.text,
            "entity_ids": list(set(entity_ids)),
            "entity_names": list(set(entity_names)),
            "mentions": mentions,
            **chunk.metadata,
        }

    def warm_cache(self, sample_size: int = 50_000) -> None:
        """Pre-populate the fuzzy name index from the graph."""
        query = f"MATCH (e:Entity) RETURN e.id, e.name LIMIT {sample_size}"
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
            if len(result) > 1:
                for row in result[1]:
                    if row[0] and row[1]:
                        self._name_index[row[1].lower()] = row[0]
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, ent: ExtractedEntity) -> str | None:
        entity_id = self._exact_lookup(ent.text)
        if entity_id:
            return entity_id
        entity_id = self._fuzzy_lookup(ent.text)
        if entity_id:
            return entity_id
        return self._create_entity(ent)

    def _exact_lookup(self, name: str) -> str | None:
        name_esc = name.replace("'", "\\'")
        query = (
            f"MATCH (e:Entity) WHERE toLower(e.name) = toLower('{name_esc}') "
            "RETURN e.id LIMIT 1"
        )
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
            if len(result) > 1 and result[1]:
                return result[1][0][0]
        except Exception:
            pass
        return None

    def _fuzzy_lookup(self, name: str) -> str | None:
        if not self._name_index:
            return None
        match = process.extractOne(
            name.lower(), self._name_index.keys(), scorer=fuzz.token_sort_ratio
        )
        if match and match[1] >= self._FUZZY_THRESHOLD:
            return self._name_index[match[0]]
        return None

    def _create_entity(self, ent: ExtractedEntity) -> str:
        """Create a new entity node and return its generated ID."""
        entity_id = f"doc:{ent.label.lower()}:{ent.text.lower().replace(' ', '_')[:40]}"
        name_esc = ent.text.replace("'", "\\'")
        query = (
            f"MERGE (e:Entity {{id: '{entity_id}'}}) "
            f"SET e.name = '{name_esc}', e.schema = '{ent.label}', e.datasets = 'doc_extracted'"
        )
        try:
            self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
            self._name_index[ent.text.lower()] = entity_id
        except Exception:
            pass
        return entity_id
