import json
from redis import Redis


class RedisWriter:
    """Writes entities and relationships into RedisGraph using GRAPH.QUERY.

    Uses UNWIND-based batch Cypher so the graph module receives actual nodes
    and edges rather than flat Redis hashes.
    """

    # All fields emitted by sanctionsParser.parse_entity (schema-specific ones
    # default to "" when absent so every batch row has a uniform shape).
    _ENTITY_FIELDS = [
        "id", "name", "schema", "datasets",
        "topics", "aliases", "country",
        # Person
        "birthDate", "position", "passportNumber",
        # Company / LegalEntity / Organization
        "incorporationDate", "registrationNumber", "jurisdiction",
        # Vessel (maritime sanctions)
        "imoNumber", "mmsi", "flag", "vesselType", "callSign",
        # Security (sanctioned securities)
        "isin", "cusip", "ticker", "exchange",
        # Sanction record
        "program", "startDate", "endDate", "reason", "authority",
        # Position (PEP)
        "description",
    ]

    def __init__(self, host: str, port: int, graph: str = "entities"):
        self.redis = Redis(host=host, port=port, decode_responses=True)
        self._graph = graph

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_entities(self, entities: list[dict]) -> None:
        if not entities:
            return

        payload = json.dumps(
            [
                {field: self._esc(str(e.get(field, ""))) for field in self._ENTITY_FIELDS}
                for e in entities
            ]
        )

        set_clause = ", ".join(
            f"e.{f} = row.{f}"
            for f in self._ENTITY_FIELDS
            if f != "id"
        )
        query = (
            f"WITH {payload} AS rows "
            "UNWIND rows AS row "
            "MERGE (e:Entity {id: row.id}) "
            f"SET {set_clause}"
        )
        try:
            self.redis.execute_command("GRAPH.QUERY", self._graph, query)
        except Exception:
            for e in entities:
                self._upsert_entity(e)

    def write_relationships(self, relationships: list[dict]) -> None:
        for rel in relationships:
            self._create_rel(
                rel.get("source", ""),
                rel.get("rel_type", "RELATED_TO"),
                rel.get("target", ""),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_entity(self, e: dict) -> None:
        eid = self._esc(str(e.get("id", "")))
        set_parts = ", ".join(
            f"e.{f} = '{self._esc(str(e.get(f, \"\")))}"
            + "'"
            for f in self._ENTITY_FIELDS
            if f != "id"
        )
        query = f"MERGE (e:Entity {{id: '{eid}'}}) SET {set_parts}"
        try:
            self.redis.execute_command("GRAPH.QUERY", self._graph, query)
        except Exception:
            pass

    def _create_rel(self, src: str, rel_type: str, dst: str) -> None:
        src = self._esc(src)
        dst = self._esc(dst)
        query = (
            f"MATCH (a:Entity {{id: '{src}'}}) "
            f"MATCH (b:Entity {{id: '{dst}'}}) "
            f"MERGE (a)-[:{rel_type}]->(b)"
        )
        try:
            self.redis.execute_command("GRAPH.QUERY", self._graph, query)
        except Exception:
            pass

    @staticmethod
    def _esc(value: str) -> str:
        """Escape single quotes for Cypher string literals."""
        return value.replace("'", "\\'")
