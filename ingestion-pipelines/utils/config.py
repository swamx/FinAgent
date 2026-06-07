import os

REDIS_HOST = os.getenv("REDIS_HOST", "redis-stack")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

DATASET_URL = (
    "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
)

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
