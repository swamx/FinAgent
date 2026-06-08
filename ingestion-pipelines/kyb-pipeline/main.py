"""KYB ingestion pipeline.

Streams the OpenSanctions KYB collection (company registries + beneficial
ownership, ~102.9 M entities) into a dedicated RedisGraph graph so it
stays isolated from the sanctions/PEP graph.

Usage:
    python main.py [path/to/kyb_entities.ftm.json]

The file defaults to /data/kyb_entities.ftm.json (written by downloader.py).
Run downloader.py first if the file is not present.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))

from tqdm import tqdm

from config import REDIS_HOST, REDIS_PORT, BATCH_SIZE, KYB_GRAPH
from redisWriter import RedisWriter

# Reuse the shared FTM parser — KYB uses the same entity schema.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sanctions-pipeline"))
from sanctionsParser import parse_entity, stream_entities

# KYB entity types that carry meaningful compliance data.
# Pure address/identifier helper entities are skipped to keep graph size
# manageable; the owning Company/Person nodes carry those values inline.
_SKIP_SCHEMAS = {"Address", "Identification", "Note"}

redis_writer = RedisWriter(REDIS_HOST, REDIS_PORT, graph=KYB_GRAPH)

entity_batch: list[dict] = []
relationship_batch: list[dict] = []

data_file = sys.argv[1] if len(sys.argv) > 1 else "/data/kyb_entities.ftm.json"

print(f"Ingesting {data_file} → RedisGraph graph '{KYB_GRAPH}'")

for entity in tqdm(stream_entities(data_file)):
    if entity.get("schema") in _SKIP_SCHEMAS:
        continue

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
