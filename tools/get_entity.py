from graph.redis_graph_repository import RedisGraphRepository


def get_entity(graph: RedisGraphRepository, entity_id: str) -> str:
    return str(graph.get_entity_profile(entity_id))
