from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_host: str = "redis-stack"
    redis_port: int = 6379

    opensearch_host: str = "opensearch"
    opensearch_port: int = 9200
    opensearch_index: str = "fintech-docs"

    litellm_base_url: str = "http://litellm:4000/v1"
    litellm_api_key: str = "sk-placeholder"

    primary_model: str = "qwen3-8b"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768       # nomic-embed-text=768, text-embedding-3-small=1536

    opensanctions_url: str = (
        "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
    )
    batch_size: int = 500

    # Ingestion source settings
    sec_user_agent: str = "FinAgent/1.0 contact@finagent.local"
    courtlistener_token: str = ""          # optional, raises rate limit
    icij_data_dir: str = "/tmp/icij"

    # Observability (OTel → otel-lgtm collector)
    otel_endpoint: str = "http://otel-lgtm:4317"      # gRPC OTLP endpoint
    otel_service_name: str = "finagent"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
