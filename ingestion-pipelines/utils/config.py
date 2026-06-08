import os

REDIS_HOST = os.getenv("REDIS_HOST", "redis-stack")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

DATASET_URL = (
    "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
)

KYB_DATASET_URL = (
    "https://data.opensanctions.org/datasets/latest/kyb/entities.ftm.json"
)

# RedisGraph graph names
SANCTIONS_GRAPH = os.getenv("SANCTIONS_GRAPH", "entities")
KYB_GRAPH = os.getenv("KYB_GRAPH", "kyb")

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
