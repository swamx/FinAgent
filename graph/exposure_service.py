from __future__ import annotations

from graph.redis_graph_repository import RedisGraphRepository


class ExposureService:
    def __init__(self, graph_repo: RedisGraphRepository):
        self.graph = graph_repo

    def get_exposure(self, entity_id: str) -> dict:
        related = self.graph.expand_entity(entity_id, hops=3)
        pep_paths = self.graph.get_pep_paths(entity_id)
        sanction_paths = self.graph.get_sanction_paths(entity_id)

        return {
            "entity_id": entity_id,
            "related_entities": [e.model_dump() for e in related],
            "pep_exposure": pep_paths,
            "sanction_exposure": sanction_paths,
            "risk_level": _classify_risk(pep_paths, sanction_paths),
        }


def _classify_risk(pep_paths: list, sanction_paths: list) -> str:
    if sanction_paths:
        return "HIGH"
    if pep_paths:
        return "MEDIUM"
    return "LOW"
