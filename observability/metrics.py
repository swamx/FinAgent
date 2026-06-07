"""FinAgent OTel metric instruments.

All instruments are module-level singletons initialised against the global
MeterProvider (set by setup_telemetry).  Import and call .add() / .record()
directly; no further setup needed.

Eval scores use an observable gauge (Prometheus-pull model).  Update via:
    from observability.metrics import set_eval_score
    set_eval_score("faithfulness", 0.87)
"""
from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import Observation

_meter = metrics.get_meter("finagent", version="1.0.0")

# ── Ingestion ─────────────────────────────────────────────────────────────
docs_ingested = _meter.create_counter(
    "finagent.ingest.docs_total",
    description="Documents fetched and queued per source",
    unit="docs",
)
chunks_indexed = _meter.create_counter(
    "finagent.ingest.chunks_total",
    description="Chunks written to OpenSearch per source",
    unit="chunks",
)
ingest_duration = _meter.create_histogram(
    "finagent.ingest.duration_seconds",
    description="Wall-clock ingestion time per source",
    unit="s",
)

# ── Embedding ─────────────────────────────────────────────────────────────
embed_duration = _meter.create_histogram(
    "finagent.embed.duration_seconds",
    description="LiteLLM embedding batch latency",
    unit="s",
)
embed_errors = _meter.create_counter(
    "finagent.embed.errors_total",
    description="Embedding call errors (HTTP failures or circuit-breaker open)",
)

# ── LLM ──────────────────────────────────────────────────────────────────
llm_duration = _meter.create_histogram(
    "finagent.llm.duration_seconds",
    description="LiteLLM chat-completion latency",
    unit="s",
)
llm_errors = _meter.create_counter(
    "finagent.llm.errors_total",
    description="LLM completion errors",
)

# ── Graph ─────────────────────────────────────────────────────────────────
graph_query_duration = _meter.create_histogram(
    "finagent.graph.query_duration_seconds",
    description="FalkorDB GRAPH.QUERY round-trip latency",
    unit="s",
)

# ── Search / Retrieval ────────────────────────────────────────────────────
search_duration = _meter.create_histogram(
    "finagent.search.duration_seconds",
    description="Hybrid search latency (entity resolution + graph expansion + KNN)",
    unit="s",
)
entities_per_query = _meter.create_histogram(
    "finagent.retrieval.entities_per_query",
    description="Entities resolved per search query",
    unit="entities",
)
docs_per_query = _meter.create_histogram(
    "finagent.retrieval.docs_per_query",
    description="Documents returned per search query",
    unit="docs",
)
graph_hits_per_query = _meter.create_histogram(
    "finagent.retrieval.graph_hits_per_query",
    description="Entity IDs pulled from graph expansion per query",
    unit="ids",
)

# ── Agent tool calls ──────────────────────────────────────────────────────
tool_calls_total = _meter.create_counter(
    "finagent.agent.tool_calls_total",
    description="Tool invocations by tool name",
)

# ── Circuit breakers ──────────────────────────────────────────────────────
circuit_breaker_events = _meter.create_counter(
    "finagent.circuit_breaker.events_total",
    description="Circuit breaker state-change events",
)

# ── Eval scores ───────────────────────────────────────────────────────────
# Observable gauge: Prometheus reads the latest stored value on each scrape.
_eval_scores: dict[str, float] = {}


def set_eval_score(metric: str, value: float) -> None:
    """Store the latest value for a named eval metric (e.g. 'faithfulness')."""
    _eval_scores[metric] = float(value)


def _observe_eval(options):
    for metric, value in _eval_scores.items():
        yield Observation(value, {"metric": metric})


_meter.create_observable_gauge(
    "finagent.eval.score",
    callbacks=[_observe_eval],
    description="Latest RAGAS / LLM-judge eval scores (1 = best, 0 = worst)",
    unit="1",
)
