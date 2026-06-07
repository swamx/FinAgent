"""Profile builder — generates entity and exposure documents for the vector DB.

These synthetic documents are the "bridge" between the graph and semantic
search. They allow the LLM to retrieve Elon Musk's full context even before
any filed document explicitly names all of his connections.

Two document types are produced:
  - entity_profile : "Elon Musk, CEO of Tesla, founder of SpaceX, ..."
  - exposure_profile: "Person X → PEP via role Minister of Finance → ..."
"""
from __future__ import annotations

import asyncio
import uuid

from opensearchpy import OpenSearch
from redis import Redis

from core.config import settings
from vector.embeddings import embed
from vector.index_setup import create_fintech_index

_PROFILE_BATCH = 50


class ProfileBuilder:
    def __init__(self, redis_client: Redis, os_client: OpenSearch):
        self.redis = redis_client
        self.os = os_client
        self._graph = "entities"

    async def run(self) -> None:
        create_fintech_index(self.os)
        await asyncio.gather(
            self._build_entity_profiles(),
            self._build_exposure_profiles(),
        )

    # ------------------------------------------------------------------
    # Entity profiles
    # ------------------------------------------------------------------

    async def _build_entity_profiles(self) -> None:
        entities = self._all_entities()
        print(f"  Building profiles for {len(entities)} entities…")

        batch: list[dict] = []
        for ent in entities:
            text = self._entity_profile_text(ent)
            if not text:
                continue
            batch.append({"entity": ent, "text": text})
            if len(batch) >= _PROFILE_BATCH:
                await self._index_profiles(batch, "entity_profile")
                batch = []

        if batch:
            await self._index_profiles(batch, "entity_profile")

    def _entity_profile_text(self, ent: dict) -> str:
        eid  = ent.get("id", "")
        name = ent.get("name", "")
        schema = ent.get("schema", "")
        datasets = ent.get("datasets", "")

        if not name:
            return ""

        # fetch relationships from graph
        rels = self._entity_relationships(eid)

        related_section = ""
        if rels:
            lines = [f"  - {r['rel_type'].replace('_', ' ').lower()}: {r['target_name']}" for r in rels[:20]]
            related_section = "Relationships:\n" + "\n".join(lines)

        pep_flag = "YES" if "peps" in datasets or "sanctions" in datasets else "NO"

        return (
            f"Entity: {name}\n"
            f"Type: {schema}\n"
            f"Datasets: {datasets}\n"
            f"PEP/Sanctions flag: {pep_flag}\n"
            f"{related_section}"
        ).strip()

    def _entity_relationships(self, entity_id: str) -> list[dict]:
        query = (
            f"MATCH (e {{id: '{entity_id}'}})-[r]-(n) "
            "RETURN type(r), n.id, n.name LIMIT 30"
        )
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self._graph, query)
            if len(result) > 1:
                return [
                    {"rel_type": row[0], "target_id": row[1], "target_name": row[2]}
                    for row in result[1]
                    if row[1] and row[2]
                ]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Exposure profiles
    # ------------------------------------------------------------------

    async def _build_exposure_profiles(self) -> None:
        # Only build exposure profiles for PEP/sanctions entities
        entities = self._pep_entities()
        print(f"  Building exposure profiles for {len(entities)} PEP/sanctions entities…")

        batch: list[dict] = []
        for ent in entities:
            text = self._exposure_text(ent)
            if not text:
                continue
            batch.append({"entity": ent, "text": text})
            if len(batch) >= _PROFILE_BATCH:
                await self._index_profiles(batch, "exposure_profile")
                batch = []

        if batch:
            await self._index_profiles(batch, "exposure_profile")

    def _exposure_text(self, ent: dict) -> str:
        name = ent.get("name", "")
        datasets = ent.get("datasets", "")
        eid = ent.get("id", "")

        # 3-hop traversal for exposure chain
        query = (
            f"MATCH p=(e {{id: '{eid}'}})-[*1..3]-(n) "
            "RETURN n.name, n.schema LIMIT 30"
        )
        connected: list[str] = []
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self._graph, query)
            if len(result) > 1:
                connected = [f"{row[0]} ({row[1]})" for row in result[1] if row[0]]
        except Exception:
            pass

        if not connected:
            return ""

        conn_text = "\n".join(f"  - {c}" for c in connected[:20])
        return (
            f"PEP/Sanctions exposure profile: {name}\n"
            f"Datasets: {datasets}\n"
            f"Connected entities (up to 3 hops):\n{conn_text}"
        ).strip()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _index_profiles(self, batch: list[dict], doc_type: str) -> None:
        texts = [b["text"] for b in batch]
        embeddings = await asyncio.get_event_loop().run_in_executor(
            None, lambda: [embed(t) for t in texts]
        )
        bulk_body: list[dict] = []
        for b, emb in zip(batch, embeddings):
            ent = b["entity"]
            doc_id = str(uuid.uuid4())
            bulk_body.append(
                {"index": {"_index": settings.opensearch_index, "_id": doc_id}}
            )
            bulk_body.append({
                "chunk_id":    doc_id,
                "document_id": ent.get("id", ""),
                "doc_type":    doc_type,
                "source":      "graph_profile",
                "text":        b["text"],
                "entity_ids":  [ent.get("id", "")],
                "entity_names": [ent.get("name", "")],
                "embedding":   emb,
            })
        if bulk_body:
            self.os.bulk(body=bulk_body)

    def _all_entities(self) -> list[dict]:
        query = "MATCH (e:Entity) RETURN e.id, e.name, e.schema, e.datasets LIMIT 100000"
        return self._run_entity_query(query)

    def _pep_entities(self) -> list[dict]:
        query = (
            "MATCH (e:Entity) "
            "WHERE e.datasets CONTAINS 'peps' OR e.datasets CONTAINS 'sanctions' "
            "RETURN e.id, e.name, e.schema, e.datasets LIMIT 50000"
        )
        return self._run_entity_query(query)

    def _run_entity_query(self, query: str) -> list[dict]:
        try:
            result = self.redis.execute_command("GRAPH.QUERY", self._graph, query)
            if len(result) > 1:
                return [
                    {"id": row[0], "name": row[1], "schema": row[2], "datasets": row[3]}
                    for row in result[1]
                    if row[0]
                ]
        except Exception:
            pass
        return []
