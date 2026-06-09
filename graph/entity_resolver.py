from __future__ import annotations

import spacy
from rapidfuzz import fuzz, process
from redis import Redis

from core.config import settings
from core.models import Entity


class EntityResolver:
    # NER labels we care about for compliance
    _LABELS = {"PERSON", "ORG", "GPE", "FAC"}

    def __init__(self, redis_client: Redis, graphs: list[str] | None = None):
        self.redis = redis_client
        self._graphs = graphs or [settings.sanctions_graph, settings.kyb_graph]
        self._nlp = spacy.load("en_core_web_sm")
        # name → entity_id; populated lazily from all graphs
        self._name_index: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_mentions(self, text: str) -> list[str]:
        doc = self._nlp(text)
        return [ent.text for ent in doc.ents if ent.label_ in self._LABELS]

    def resolve(self, mention: str) -> Entity | None:
        entity = self._exact_lookup(mention)
        if entity:
            return entity
        return self._fuzzy_lookup(mention)

    def extract_and_resolve(self, text: str) -> list[Entity]:
        resolved: list[Entity] = []
        seen: set[str] = set()
        for mention in self.extract_mentions(text):
            entity = self.resolve(mention)
            if entity and entity.id not in seen:
                resolved.append(entity)
                seen.add(entity.id)
        return resolved

    def warm_cache(self, sample_size: int = 50_000) -> None:
        """Pre-populate the fuzzy name index from all graphs."""
        query = f"MATCH (e:Entity) RETURN e.id, e.name LIMIT {sample_size}"
        for graph in self._graphs:
            try:
                result = self.redis.execute_command("GRAPH.QUERY", graph, query)
                if len(result) > 1:
                    for row in result[1]:
                        if row[0] and row[1]:
                            self._name_index[row[1].lower()] = row[0]
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exact_lookup(self, mention: str) -> Entity | None:
        safe = mention.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"MATCH (e) WHERE toLower(e.name) = toLower('{safe}') "
            "RETURN e.id, e.name LIMIT 1"
        )
        for graph in self._graphs:
            try:
                result = self.redis.execute_command("GRAPH.QUERY", graph, query)
                if len(result) > 1 and result[1]:
                    row = result[1][0]
                    return Entity(id=row[0], name=row[1])
            except Exception:
                pass
        return None

    def _fuzzy_lookup(self, mention: str, threshold: int = 85) -> Entity | None:
        if not self._name_index:
            return None
        match = process.extractOne(
            mention, self._name_index.keys(), scorer=fuzz.token_sort_ratio
        )
        if match and match[1] >= threshold:
            name = match[0]
            return Entity(id=self._name_index[name], name=name)
        return None
