from __future__ import annotations

import time

from redis import Redis

from core.config import settings
from core.models import Entity
from observability.metrics import graph_query_duration
from observability.tracing import get_tracer


class RedisGraphRepository:
    """Queries FalkorDB across all configured graphs and merges results.

    By default fans out to both the sanctions graph ('entities') and the
    KYB graph ('kyb') so callers get a unified view of entity data.
    """

    def __init__(self, redis_client: Redis, graphs: list[str] | None = None):
        self.redis = redis_client
        self._graphs = graphs or [settings.sanctions_graph, settings.kyb_graph]

    def expand_entity(self, entity_id: str, hops: int = 2) -> list[Entity]:
        query = (
            f"MATCH (e {{id: '{entity_id}'}})-[*1..{hops}]-(n) "
            "RETURN DISTINCT n.id, n.name, n.schema"
        )
        seen: set[str] = set()
        entities: list[Entity] = []
        for row in self._rows(query):
            eid = row[0] or ""
            if eid and eid not in seen:
                seen.add(eid)
                entities.append(Entity(
                    id=eid,
                    name=row[1] or "",
                    schema_type=row[2] if len(row) > 2 else None,
                ))
        return entities

    def get_entity_profile(self, entity_id: str) -> dict:
        query = f"MATCH (e {{id: '{entity_id}'}}) RETURN e LIMIT 1"
        rows = self._rows(query)
        return {"entity_id": entity_id, "data": rows[0] if rows else None}

    def get_relationships(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH (e {{id: '{entity_id}'}})-[r]-(n) "
            "RETURN type(r), n.id, n.name"
        )
        return [
            {"rel_type": row[0], "target_id": row[1], "target_name": row[2]}
            for row in self._rows(query)
        ]

    def get_pep_paths(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH p=(e {{id: '{entity_id}'}})-[*1..4]-(n {{schema: 'Position'}}) "
            "RETURN p"
        )
        return [{"path": row} for row in self._rows(query)]

    def get_sanction_paths(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH p=(e {{id: '{entity_id}'}})-[*1..4]-(n) "
            "WHERE n.datasets CONTAINS 'sanctions' "
            "RETURN p"
        )
        return [{"path": row} for row in self._rows(query)]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rows(self, cypher: str) -> list:
        """Fan out cypher to all graphs, return merged row list."""
        all_rows: list = []
        for graph in self._graphs:
            try:
                result = self._query(cypher, graph)
                if len(result) > 1:
                    all_rows.extend(result[1])
            except Exception:
                pass
        return all_rows

    def _query(self, cypher: str, graph: str | None = None) -> list:
        target = graph or self._graphs[0]
        tracer = get_tracer()
        t0 = time.time()
        with tracer.start_as_current_span("graph.query") as span:
            span.set_attribute("db.system", "falkordb")
            span.set_attribute("db.graph", target)
            span.set_attribute("db.statement", cypher[:200])
            try:
                result = self.redis.execute_command("GRAPH.QUERY", target, cypher)
                graph_query_duration.record(time.time() - t0)
                return result
            except Exception as exc:
                span.record_exception(exc)
                raise
