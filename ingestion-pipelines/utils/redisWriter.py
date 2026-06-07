import json
from redis import Redis


class RedisWriter:
    """Writes entities and relationships into RedisGraph using GRAPH.QUERY.

    Uses UNWIND-based batch Cypher so the graph module receives actual nodes
    and edges rather than flat Redis hashes.
    """

    _GRAPH = "entities"

    def __init__(self, host: str, port: int):
        self.redis = Redis(host=host, port=port, decode_responses=True)

    # ------------------------------------------------------------------
    # Public API (same signatures as before)
    # ------------------------------------------------------------------

    def write_entities(self, entities: list[dict]) -> None:
        if not entities:
            return
        # UNWIND lets us send a whole batch in one GRAPH.QUERY call.
        # We serialise the list as a JSON literal so Cypher can parse it.
        payload = json.dumps(
            [
                {
                    "id": e.get("id", ""),
                    "name": self._esc(str(e.get("name", ""))),
                    "schema": self._esc(str(e.get("schema", ""))),
                    "datasets": self._esc(str(e.get("datasets", ""))),
                }
                for e in entities
            ]
        )
        query = (
            f"WITH {payload} AS rows "
            "UNWIND rows AS row "
            "MERGE (e:Entity {id: row.id}) "
            "SET e.name = row.name, e.schema = row.schema, e.datasets = row.datasets"
        )
        try:
            self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
        except Exception as exc:
            # Individual-row fallback so one bad record doesn't lose the batch.
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
        name = self._esc(str(e.get("name", "")))
        schema = self._esc(str(e.get("schema", "")))
        datasets = self._esc(str(e.get("datasets", "")))
        query = (
            f"MERGE (e:Entity {{id: '{eid}'}}) "
            f"SET e.name = '{name}', e.schema = '{schema}', e.datasets = '{datasets}'"
        )
        try:
            self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
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
            self.redis.execute_command("GRAPH.QUERY", self._GRAPH, query)
        except Exception:
            pass

    @staticmethod
    def _esc(value: str) -> str:
        """Escape single quotes for Cypher string literals."""
        return value.replace("'", "\\'")
