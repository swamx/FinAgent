from __future__ import annotations

import time

from redis import Redis

from core.models import Entity
from observability.metrics import graph_query_duration
from observability.tracing import get_tracer


class RedisGraphRepository:
    _GRAPH = "entities"

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def expand_entity(self, entity_id: str, hops: int = 2) -> list[Entity]:
        query = (
            f"MATCH (e {{id: '{entity_id}'}})-[*1..{hops}]-(n) "
            "RETURN DISTINCT n.id, n.name, n.schema"
        )
        result = self._query(query)
        entities: list[Entity] = []
        if len(result) > 1:
            for row in result[1]:
                entities.append(
                    Entity(
                        id=row[0] or "",
                        name=row[1] or "",
                        schema_type=row[2] if len(row) > 2 else None,
                    )
                )
        return entities

    def get_entity_profile(self, entity_id: str) -> dict:
        query = f"MATCH (e {{id: '{entity_id}'}}) RETURN e LIMIT 1"
        result = self._query(query)
        data = result[1][0] if len(result) > 1 and result[1] else None
        return {"entity_id": entity_id, "data": data}

    def get_relationships(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH (e {{id: '{entity_id}'}})-[r]-(n) "
            "RETURN type(r), n.id, n.name"
        )
        result = self._query(query)
        rels: list[dict] = []
        if len(result) > 1:
            for row in result[1]:
                rels.append({"rel_type": row[0], "target_id": row[1], "target_name": row[2]})
        return rels

    def get_pep_paths(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH p=(e {{id: '{entity_id}'}})-[*1..4]-(n {{schema: 'Position'}}) "
            "RETURN p"
        )
        result = self._query(query)
        return [{"path": row} for row in result[1]] if len(result) > 1 else []

    def get_sanction_paths(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH p=(e {{id: '{entity_id}'}})-[*1..4]-(n) "
            "WHERE n.datasets CONTAINS 'sanctions' "
            "RETURN p"
        )
        result = self._query(query)
        return [{"path": row} for row in result[1]] if len(result) > 1 else []

    def _query(self, cypher: str) -> list:
        tracer = get_tracer()
        t0 = time.time()
        with tracer.start_as_current_span("graph.query") as span:
            span.set_attribute("db.system", "falkordb")
            span.set_attribute("db.statement", cypher[:200])
            try:
                result = self.redis.execute_command("GRAPH.QUERY", self._GRAPH, cypher)
                graph_query_duration.record(time.time() - t0)
                return result
            except Exception as exc:
                span.record_exception(exc)
                raise
