from functools import lru_cache

from opensearchpy import OpenSearch
from redis import Redis

from core.config import settings
from graph.entity_resolver import EntityResolver
from graph.exposure_service import ExposureService
from graph.redis_graph_repository import RedisGraphRepository
from llm.agent import AgentDeps, ComplianceAgent
from vector.opensearch_repository import OpenSearchRepository
from vector.retriever import RetrievalService


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
    )


@lru_cache(maxsize=1)
def get_opensearch() -> OpenSearch:
    return OpenSearch([{"host": settings.opensearch_host, "port": settings.opensearch_port}])


def get_graph_repo() -> RedisGraphRepository:
    return RedisGraphRepository(get_redis())


def get_entity_resolver() -> EntityResolver:
    return EntityResolver(get_redis())


def get_exposure_service() -> ExposureService:
    return ExposureService(get_graph_repo())


def get_vector_repo() -> OpenSearchRepository:
    return OpenSearchRepository(get_opensearch())


def get_retrieval_service() -> RetrievalService:
    return RetrievalService(
        graph_repo=get_graph_repo(),
        vector_repo=get_vector_repo(),
        entity_resolver=get_entity_resolver(),
    )


def get_agent_deps() -> AgentDeps:
    return AgentDeps(
        retrieval=get_retrieval_service(),
        graph=get_graph_repo(),
        exposure=get_exposure_service(),
    )


def get_compliance_agent() -> ComplianceAgent:
    return ComplianceAgent(get_agent_deps())
