from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.config import settings
from graph.exposure_service import ExposureService
from graph.redis_graph_repository import RedisGraphRepository
from observability.circuit_breakers import llm_breaker
from observability.metrics import llm_duration, llm_errors, tool_calls_total
from observability.tracing import get_tracer
from vector.retriever import RetrievalService

_log = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    retrieval: RetrievalService
    graph: RedisGraphRepository
    exposure: ExposureService


_model = OpenAIModel(
    settings.primary_model,
    provider=OpenAIProvider(
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
    ),
)

agent = Agent(
    _model,
    deps_type=AgentDeps,
    system_prompt=(
        "You are a compliance analyst for AML, PEP, and sanctions investigations. "
        "Use the available tools to retrieve entities, check exposure, and surface "
        "relevant documents. Be concise and cite specific entity IDs where relevant. "
        "After every factual claim, cite the data source in square brackets. "
        "Use the source field from the retrieved documents or tool results. "
        "Known sources: [SEC EDGAR], [CourtListener], [ICIJ Offshore Leaks], "
        "[USASpending], [GDELT News], [OpenSanctions]. "
        "Example: 'Acme Corp received a $2M fine for OFAC violations [SEC EDGAR]. "
        "The company is connected to three sanctioned individuals [OpenSanctions].' "
        "IMPORTANT: If a tool returns 'not found' or an empty result, do NOT call "
        "the same tool again with the same or similar input. Move on and answer "
        "with what you have, or use search_documents to find relevant information."
    ),
)


@agent.tool
def search_documents(ctx: RunContext[AgentDeps], query: str) -> str:
    """Semantic + graph hybrid search over compliance documents."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "search_documents"})
    with tracer.start_as_current_span("tool.search_documents") as span:
        span.set_attribute("tool.name", "search_documents")
        span.set_attribute("tool.input.query", query)
        result = ctx.deps.retrieval.search(query)
        json_result = result.model_dump_json()
        span.set_attribute("tool.output.entities_found", len(result.entities))
        span.set_attribute("tool.output.docs_returned", len(result.documents))
        _log.info(
            "tool_call tool=search_documents entities=%d docs=%d query=%r",
            len(result.entities), len(result.documents), query[:120],
        )
        return json_result


@agent.tool
def get_entity(ctx: RunContext[AgentDeps], entity_id: str) -> str:
    """Fetch the full profile for a known entity ID."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "get_entity"})
    with tracer.start_as_current_span("tool.get_entity") as span:
        span.set_attribute("tool.name", "get_entity")
        span.set_attribute("tool.input.entity_id", entity_id)
        result = ctx.deps.graph.get_entity_profile(entity_id)
        _log.info("tool_call tool=get_entity entity_id=%r", entity_id)
        span.set_attribute("tool.output.found", bool(result.get("data")))
        return str(result)


@agent.tool
def get_exposure(ctx: RunContext[AgentDeps], entity_id: str) -> str:
    """Return PEP/sanctions exposure and related entity graph for an entity."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "get_exposure"})
    with tracer.start_as_current_span("tool.get_exposure") as span:
        span.set_attribute("tool.name", "get_exposure")
        span.set_attribute("tool.input.entity_id", entity_id)
        result = ctx.deps.exposure.get_exposure(entity_id)
        _log.info("tool_call tool=get_exposure entity_id=%r", entity_id)
        return str(result)


@agent.tool
def expand_entity(ctx: RunContext[AgentDeps], entity_name: str) -> str:
    """Resolve a name to an entity and return its 2-hop graph neighbourhood."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "expand_entity"})
    with tracer.start_as_current_span("tool.expand_entity") as span:
        span.set_attribute("tool.name", "expand_entity")
        span.set_attribute("tool.input.entity_name", entity_name)
        entities = ctx.deps.retrieval.resolver.extract_and_resolve(entity_name)
        if not entities:
            span.set_attribute("tool.output.resolved", False)
            _log.info("tool_call tool=expand_entity entity_name=%r resolved=False", entity_name)
            return (
                f"Entity '{entity_name}' not found in the graph. "
                "Do not call this tool again with the same name. "
                "Use search_documents instead to find relevant information."
            )
        related = ctx.deps.graph.expand_entity(entities[0].id)
        span.set_attribute("tool.output.resolved", True)
        span.set_attribute("tool.output.entity_id", entities[0].id)
        span.set_attribute("tool.output.related_count", len(related))
        _log.info(
            "tool_call tool=expand_entity entity_name=%r resolved_id=%r related=%d",
            entity_name, entities[0].id, len(related),
        )
        return str([e.model_dump() for e in related])


class ComplianceAgent:
    def __init__(self, deps: AgentDeps):
        self.deps = deps

    async def answer(self, question: str) -> str:
        import time
        tracer = get_tracer()
        t0 = time.time()
        with tracer.start_as_current_span("llm.agent_run") as span:
            span.set_attribute("question.length", len(question))
            try:
                result = await llm_breaker.call_async(
                    agent.run, question, deps=self.deps,
                    usage_limits=UsageLimits(request_limit=8),
                )
                llm_duration.record(time.time() - t0)
                return result.data
            except UsageLimitExceeded as exc:
                # Agent hit the 8-request cap — return whatever it produced so far
                llm_duration.record(time.time() - t0)
                partial = getattr(exc, "output", None) or getattr(exc, "result", None)
                if partial and isinstance(partial, str):
                    return partial
                return (
                    "I was unable to complete the full analysis within the request limit. "
                    "Please try rephrasing with a more specific question."
                )
            except Exception as exc:
                llm_errors.add(1)
                span.record_exception(exc)
                raise
