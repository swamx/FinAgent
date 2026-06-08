import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))

from tqdm import tqdm

from config import REDIS_HOST, REDIS_PORT, BATCH_SIZE, DATASET_URL, SANCTIONS_GRAPH
from sanctionsParser import parse_entity, stream_entities
from redisWriter import RedisWriter

redis_writer = RedisWriter(REDIS_HOST, REDIS_PORT, graph=SANCTIONS_GRAPH)

entity_batch: list[dict] = []
relationship_batch: list[dict] = []

data_file = sys.argv[1] if len(sys.argv) > 1 else "entities.ftm.json"

print(f"Ingesting {data_file} → RedisGraph graph '{SANCTIONS_GRAPH}'")

for entity in tqdm(stream_entities(data_file)):
    node, rels = parse_entity(entity)
    entity_batch.append(node)
    relationship_batch.extend(rels)

    if len(entity_batch) >= BATCH_SIZE:
        redis_writer.write_entities(entity_batch)
        redis_writer.write_relationships(relationship_batch)
        entity_batch.clear()
        relationship_batch.clear()

# flush remainder
if entity_batch:
    redis_writer.write_entities(entity_batch)
    redis_writer.write_relationships(relationship_batch)

print("Done")
