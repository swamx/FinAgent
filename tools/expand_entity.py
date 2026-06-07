from graph.entity_resolver import EntityResolver
from graph.redis_graph_repository import RedisGraphRepository


def expand_entity(
    resolver: EntityResolver,
    graph: RedisGraphRepository,
    entity_name: str,
) -> str:
    entities = resolver.extract_and_resolve(entity_name)
    if not entities:
        return "[]"
    related = graph.expand_entity(entities[0].id)
    return str([e.model_dump() for e in related])
