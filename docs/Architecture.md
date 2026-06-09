# FinAgent — Architecture

**Navigation:** [README](../README.md) · [Setup](Setup.md) · [Agent Workflow](AgentWorkflowExplaination.md) · [Ingestion Architectures](IngestionFlow.md) · [Links](Links.md) · [Demo](Demo.md)

---

FinAgent is a containerized AML/PEP/sanctions compliance research platform. It ingests
documents from five public data sources, builds a knowledge graph of entities and
relationships, indexes document chunks into a vector store, and exposes a conversational
agent that answers compliance questions using hybrid semantic + graph retrieval.

---

## System Diagram

See the interactive diagram in [AgentWorkflowExplaination.md](AgentWorkflowExplaination.md) (Mermaid, renders on GitHub) or the static export:

![Service & Agent Workflow](workflow_td.png)

---

## Services

| Service | Image / Build | Ports | Purpose | Lifecycle |
| --- | --- | --- | --- | --- |
| `redis-stack` | `falkordb/falkordb:latest` | 6379, 3000 | Knowledge graph (FalkorDB) + browser UI | Always up |
| `opensearch` | `opensearchproject/opensearch:2.13.0` | 9200 | Vector store (BM25+KNN hybrid index) | Always up |
| `opensearch-dashboards` | `opensearchproject/opensearch-dashboards:2.13.0` | 5601 | Index/query visualization | Always up |
| `postgres` | `postgres:16-alpine` | 5432 | LiteLLM request metadata DB | Always up |
| `ollama` | `ollama/ollama:latest` | 11434 | Local LLM runtime | Always up |
| `ollama-init` | `ollama/ollama:latest` | — | Pull `qwen3:4b` + `nomic-embed-text` | One-shot |
| `litellm` | `ghcr.io/berriai/litellm:main-latest` | 4000 | LLM gateway (local + cloud) | Always up |
| `api` | `Dockerfile.api` | 8000 | FastAPI compliance API + slowapi rate limiter | Always up |
| `open-webui` | `ghcr.io/open-webui/open-webui:main` | 3001 | Chat frontend | Always up |
| `otel-lgtm` | `grafana/otel-lgtm:latest` | 3100, 4317, 4318 | Grafana + Prometheus + Loki + Tempo | Always up |
| `sanctions-ingestor` | `Dockerfile.worker` | — | Load OpenSanctions into FalkorDB | One-shot |
| `doc-ingestor` | `Dockerfile.worker` | — | Fetch 5 sources → chunk → embed → index | One-shot / refresh |
| `eval-runner` | `Dockerfile.eval` | — | RAGAS + hallucination evals → Grafana | On-demand |

---

## Data Stores

### FalkorDB — Knowledge Graph (`entities` graph)

| Element | Detail |
| --- | --- |
| Node label | `Entity` |
| Node properties | `id`, `name`, `schema` (Person/Organization/…), `datasets` |
| Relationship types | `OWNS`, `DIRECTOR_OF`, `ASSOCIATED_WITH`, `PARENT_OF`, `SUBSIDIARY_OF`, `FAMILY_OF`, `MEMBER_OF`, `EMPLOYEE_OF`, `OPERATES` |
| Primary use | Multi-hop expansion, PEP/sanctions path queries, entity enrichment |
| Port | 6379 (Redis protocol) |
| Browser UI | <http://localhost:3000> |

Sample Cypher queries:

```cypher
GRAPH.QUERY entities "MATCH (n) RETURN count(n) AS nodes"
GRAPH.QUERY entities "MATCH ()-[r]->() RETURN count(r) AS edges"
GRAPH.QUERY entities "MATCH (n:Entity) RETURN n.schema, count(n) ORDER BY count(n) DESC"
GRAPH.QUERY entities "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS 'abramovich' OPTIONAL MATCH (n)-[e]-(m) RETURN n,e,m LIMIT 100"
```

> **Note:** FalkorDB replaced `redis/redis-stack` which dropped RedisGraph in v7.2.
> All `GRAPH.QUERY` commands are drop-in compatible.

### OpenSearch — Vector Index (`fintech-docs`)

| Field | Type | Detail |
| --- | --- | --- |
| `text` | text | Chunk content (English analyzer) |
| `embedding` | knn_vector | 768-dim, cosinesimil, HNSW nmslib engine |
| `source` | keyword | `sec_edgar`, `courtlistener`, `icij`, `procurement`, `news` |
| `title` | text + keyword | BM25-boosted (×2.0 in `search_hybrid`) |
| `author` | text + keyword | BM25-boosted (×0.6 in `search_hybrid`) |
| `jurisdiction` | keyword | Country/state code — boost only if passed explicitly |
| `date` | date | ISO-8601 |
| `doc_length` | integer | Characters in original pre-chunked document |
| `url` | keyword | Canonical source URL |
| `entity_ids` | keyword[] | Resolved graph entity IDs (KNN filter) |
| `mentions` | nested | Char offset spans for UI highlighting |

Dashboards UI: <http://localhost:5601>

> **Note:** OpenSearch FAISS engine does not support `cosine`. The index uses `nmslib` with `cosinesimil`.

---

## Ingestion Pipeline

Full pipeline diagrams — current architecture and four alternatives (Kafka+Spark, Kafka+Flink, Kafka+Knative, AWS Lambda+SQS) — are in [IngestionFlow.md](IngestionFlow.md).

### Sanctions Graph (one-shot)

```text
OpenSanctions JSONL (~2 GB)
  └── downloader.py          stream download via requests (cached in volume)
  └── sanctionsParser.py     parse FTM entity + extract typed relationships
  └── redisWriter.py         UNWIND-based batch Cypher MERGE (500/batch)
  └── FalkorDB               MERGE (e:Entity {id}) + relationship edges
```

Container self-destructs after completion.

### Document Ingestion (idempotent, periodic refresh)

```text
Multiple Sources (SEC EDGAR · CourtListener · ICIJ · USASpending · GDELT News)
  ↓  asyncio.gather — parallel fetch
chunk_text()           1200-char sentence-boundary chunks, 200 char overlap
  ↓
HybridEntityExtractor  spaCy (7 labels) + GLiNER (8 financial labels)
                       GLiNER preferred on overlap, 0.45 confidence threshold
  ↓
EntityEnricher         exact-match → fuzzy (RapidFuzz 80%) → create new node
                       annotates chunk with entity_ids + mention char spans
  ↓
embed()                nomic-embed-text via LiteLLM proxy
  ↓
OpenSearch bulk        HNSW KNN + BM25 text fields + all metadata
  ↓
ProfileBuilder         synthetic entity + exposure profile docs
```

Redis checkpointing (`SADD fintech:ingested:{source}`) makes re-runs idempotent.

---

## API Layer

### Rate Limiting

`slowapi 0.1.9` enforces per-IP rate limits via `SlowAPIMiddleware`:

| Endpoint | Limit | Reason |
| --- | --- | --- |
| `POST /chat` | 10 req/min | Each call triggers LLM — expensive |
| `POST /search` | 60 req/min | Vector search only — cheaper |

Exceeded limits return `HTTP 429 Too Many Requests` with a `Retry-After` header.
The `Limiter` singleton lives in `apps/api/limiter.py` — swap to
`storage_uri="redis://redis-stack:6379/1"` for multi-replica deployments.

### Agent Safety

- **Loop guard:** `expand_entity` returns an explicit not-found message instead
  of `"[]"` when an entity is absent from the graph, preventing the LLM from
  retrying indefinitely.
- **Request cap:** `UsageLimits(request_limit=8)` passed to every `agent.run()`
  call; raises `UsageLimitExceeded` if the agent exceeds 8 LLM calls per turn.
- **System prompt:** Instructs the agent not to retry tools with the same input
  after a not-found result.

### Cypher Safety

`entity_resolver.py._exact_lookup()` escapes `\` and `'` in entity names before
interpolating them into Cypher queries, preventing syntax errors on names like
`Oleg Deripaska's`.

---

## Query / Chat Flow

```text
POST /chat  →  ComplianceAgent.answer()
    │
    ▼
PydanticAI agent 0.4.2  (system: "compliance analyst for AML/PEP/sanctions…")
    │
    ├── tool: expand_entity(name)          [OTel span: tool.expand_entity]
    │     └── EntityResolver: extract_and_resolve(name)
    │     └── If found: FalkorDB 2-hop expansion
    │     └── If not found: "not found, do not retry" message → agent moves on
    │
    ├── tool: search_documents(query)      [OTel span: tool.search_documents]
    │     └── EntityResolver: NER → exact lookup (apostrophe-safe) → fuzzy
    │     └── FalkorDB: 2-hop graph expansion for matched entities
    │     └── search_hybrid(): kNN must + BM25 should (title×2.0, author×0.6)
    │
    ├── tool: get_entity(entity_id)        [OTel span: tool.get_entity]
    │     └── GRAPH.QUERY → entity node properties
    │
    └── tool: get_exposure(entity_id)      [OTel span: tool.get_exposure]
          └── 3-hop expansion + PEP path + sanctions path
          └── risk_level: HIGH / MEDIUM / LOW
    │
    ▼
LiteLLM :4000  →  qwen3:4b (Ollama) or Claude (if ANTHROPIC_API_KEY)
    │
    ▼
Answer  (all spans → Tempo, metrics → Prometheus, logs → Loki via otel-lgtm)
```

---

## Observability

All services emit OTel telemetry to `grafana/otel-lgtm` on port 4317 (gRPC).

### Grafana Dashboards

All four dashboards are pre-provisioned from `resources/grafana/dashboards/`
with hardcoded datasource UIDs (`prometheus`, `loki`, `tempo`). No login needed.

| Dashboard | UID | Description |
| --- | --- | --- |
| FinAgent — Overview | `finagent-overview` | KPIs: rate, latency, errors, tool calls |
| FinAgent — Request Flow | `finagent-flow` | Stage latency, traces (Tempo), logs (Loki) |
| FinAgent — Retrieval Quality | `finagent-retrieval` | Entity resolution, graph hits, circuit breakers |
| FinAgent — Evals | `finagent-evals` | RAGAS scores + hallucination rate |

### OTel Spans

| Span | Service | What it measures |
| --- | --- | --- |
| `llm.agent_run` | api | Full agent turn duration |
| `tool.search_documents` | api | Hybrid retrieval per tool call |
| `tool.expand_entity` | api | Graph lookup + expansion |
| `tool.get_entity` | api | Entity profile fetch |
| `tool.get_exposure` | api | Exposure chain computation |
| `retrieval.entity_resolve` | api | NER + graph lookup stage |
| `retrieval.graph_expand` | api | 2-hop FalkorDB expansion |
| `retrieval.embed` | api | Embedding call to LiteLLM |
| `retrieval.vector_search` | api | OpenSearch kNN + BM25 query |

### Circuit Breakers

| Breaker | `fail_max` | `timeout_s` | Protects |
| --- | --- | --- | --- |
| `llm` | 3 | 60 | LiteLLM proxy |
| `opensearch` | 5 | 30 | OpenSearch vector search |
| `graph` | 5 | 30 | FalkorDB graph queries |
| `sec` | 5 | 120 | SEC EDGAR API |
| `courtlistener` | 5 | 300 | CourtListener API |
| `icij` | 2 | 600 | ICIJ bulk download |
| `procurement` | 5 | 300 | USASpending API |
| `news` | 5 | 300 | GDELT API |

---

## LLM Gateway

All model calls route through a single LiteLLM proxy. Application code uses the
OpenAI client pointed at `http://litellm:4000/v1`; no vendor SDK is imported.

| Model alias | Backend | Notes |
| --- | --- | --- |
| `qwen3-4b` | `ollama/qwen3:4b` | Default primary (~3 GB) |
| `nomic-embed-text` | `ollama/nomic-embed-text` | Embeddings, 768-dim |
| `claude-haiku` | Anthropic API | Optional — requires `ANTHROPIC_API_KEY` |
| `claude-sonnet` | Anthropic API | Optional — requires `ANTHROPIC_API_KEY` |

Config: `resources/litellm-config.yaml`

> `drop_params: true` must be under `litellm_settings:` (not `general_settings:`).
> This drops `encoding_format: base64` which the OpenAI SDK sends by default but
> Ollama does not support.

---

## Code Layout

```text
FinAgent/
├── apps/api/
│   ├── main.py               FastAPI app + SlowAPIMiddleware + 429 handler
│   ├── limiter.py            Limiter(key_func=get_remote_address) singleton
│   ├── dependencies.py       lru_cache service factories
│   └── routers/
│       ├── chat.py           @limiter.limit("10/minute") — POST /chat
│       ├── search.py         @limiter.limit("60/minute") — POST /search
│       └── entity.py         GET /entity/{id} + /entity/{id}/exposure
│
├── graph/
│   ├── entity_resolver.py    _exact_lookup: escapes ' and \ before Cypher interpolation
│   ├── redis_graph_repository.py
│   └── exposure_service.py
│
├── llm/
│   └── agent.py              expand_entity returns "not found" message (not "[]")
│                             agent.run(..., usage_limits=UsageLimits(request_limit=8))
│
├── eval/
│   └── runner.py             reads FINAGENT_API_BASE env var; 360s chat timeout
│
├── observability/
│   ├── circuit_breakers.py   8 breakers: llm, opensearch, graph, sec, court, icij, …
│   └── metrics.py
│
└── resources/grafana/dashboards/
    ├── finagent-overview.json    datasource uid hardcoded to "prometheus"
    ├── finagent-flow.json        datasource uid hardcoded (prometheus/loki/tempo)
    ├── finagent-retrieval.json   datasource uid hardcoded (prometheus/loki)
    └── finagent-evals.json       datasource uid hardcoded (prometheus/loki)
```

---

## Key Design Decisions

**Graph-first retrieval, not vector-first.**
Vector search alone cannot discover that a query about "Elon Musk" should also
return documents about Tesla, SpaceX, and xAI. The graph expansion step runs
before vector search so the filter set is semantically complete.

**Entity profiles as synthetic documents.**
Profile documents (generated from graph data) are stored in OpenSearch alongside
source chunks. This means the LLM can answer "Tell me about X" even before any
filed document explicitly names X's connections.

**Apostrophe-safe Cypher.**
Entity names like "Oleg Deripaska's" used to break `GRAPH.QUERY` with a syntax
error. `_exact_lookup()` now escapes `\` and `'` before interpolation.

**Agent loop prevention.**
`expand_entity` previously returned `"[]"` on a graph miss, causing the LLM to
retry indefinitely. It now returns an explicit stop message. A `request_limit=8`
cap via `UsageLimits` provides a hard safety net.

**Per-IP rate limiting.**
`slowapi` enforces 10 req/min on `/chat` and 60 req/min on `/search`. The shared
`Limiter` singleton in `limiter.py` avoids import cycles between routers.

**Hardcoded Grafana datasource UIDs.**
Grafana 13 fails to resolve datasource template variables that lack `query`,
`refresh`, and `hide` fields. All four dashboards now use hardcoded UIDs
(`prometheus`, `loki`, `tempo`) matching the UIDs provisioned by `otel-lgtm`.

**Eval runner reads `FINAGENT_API_BASE`.**
Inside Docker, `localhost:8000` refers to the eval container itself. The runner
now defaults `--api` to the `FINAGENT_API_BASE` env var (set to
`http://api:8000` by docker-compose), so no `--api` flag is needed.

**LiteLLM as the only LLM boundary.**
All model calls — chat completions and embeddings — go through LiteLLM.
Swapping from local Ollama to Claude or vice versa is a one-line env change.

**PydanticAI instead of LangChain.**
The agent is ~60 lines. Tools are plain Python functions injected via
`AgentDeps`. No chains, no memory objects, no LCEL.

**OTel-first observability.**
All services emit traces, metrics, and structured logs to `grafana/otel-lgtm`
via the OTel SDK. Four pre-provisioned Grafana dashboards cover overview KPIs,
the full request flow, retrieval quality, and eval scores — no manual setup.

**Eval isolation via separate container.**
RAGAS and its LangChain dependency are kept in `requirements-eval.txt` and
`Dockerfile.eval` so the production API image stays lean. The eval runner calls
the live `/chat` and `/search` endpoints over the Docker network, testing the
real stack rather than mocked components.

---

**Navigation:** [README](../README.md) · [Setup](Setup.md) · [Agent Workflow](AgentWorkflowExplaination.md) · [Ingestion Architectures](IngestionFlow.md) · [Links](Links.md) · [Demo](Demo.md)
