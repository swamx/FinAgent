# FinAgent — Compliance Intelligence Platform

AML / PEP / sanctions investigation platform combining a knowledge graph
(FalkorDB), a hybrid vector store (OpenSearch BM25+kNN), and a local LLM
(Ollama) into a single chat-driven research tool with full OTel observability.

---

## What it does

- **Entity graph** — OpenSanctions data (PEPs, sanctions, aliases, relationships)
  loaded into FalkorDB as a traversable knowledge graph.
- **Document corpus** — Five external sources (SEC filings, court opinions, ICIJ
  Offshore Leaks, government procurement, news) chunked and embedded into
  OpenSearch with rich metadata (source, title, author, jurisdiction, date,
  doc_length, url) and entity span offsets for UI highlighting.
- **Hybrid retrieval** — queries go graph-first (entity extraction → 2-hop graph
  expansion → BM25+kNN hybrid search with title/author boost), not vector-first.
- **Local LLM** — Qwen3-4B via Ollama, routed through LiteLLM. No cloud API
  required. Optionally swap to Claude with one env var.
- **Rate limiting** — `POST /chat` capped at 10 req/min, `POST /search` at 60
  req/min per IP. Returns `HTTP 429` with `Retry-After` on breach.
- **Observability** — Full OTel tracing (Tempo), metrics (Prometheus), and
  structured logs (Loki) via `grafana/otel-lgtm` with four pre-built dashboards.
- **Evals** — RAGAS faithfulness/relevancy/precision/recall + LLM-as-judge
  hallucination scoring, exported to Grafana.
- **Chat UI** — Open WebUI connected to LiteLLM so any pulled Ollama model is
  immediately available.

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                          Browser / Client                        │
└───────────────────────────────┬──────────────────────────────────┘
                                │ HTTP
                ┌───────────────▼───────────────┐
                │          Open WebUI :3001     │  chat frontend
                └───────────────┬───────────────┘
                                │ OpenAI-compatible API
                ┌───────────────▼───────────────┐
                │           LiteLLM :4000       │  model router / proxy
                │  qwen3:4b      (primary)      │
                │  nomic-embed-text (embeddings)│
                └──────────┬────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   FinAgent API :8000    │  FastAPI + slowapi rate limiter
              │   POST /chat  10/min   │
              │   POST /search 60/min  │
              │   GET  /entity/{id}    │
              └──────┬──────────┬───────┘
                     │          │
        ┌────────────▼──┐  ┌────▼──────────────┐
        │ PydanticAI    │  │  RetrievalService  │
        │ ComplianceAgent│  │                   │
        │ 8 req max     │  │ 1. extract entities│
        │               │  │ 2. graph expand    │
        │  tools:       │  │ 3. BM25+kNN hybrid │
        │  search_docs  │  └──────┬─────────────┘
        │  get_entity   │         │
        │  get_exposure │    ┌────┴──────────────────────┐
        │  expand_entity│    │                           │
        └───────────────┘    │                           │
                             │                           │
              ┌──────────────▼───┐         ┌────────────▼──────────┐
              │   FalkorDB :6379 │         │   OpenSearch :9200    │
              │  Entity nodes    │         │  (BM25 + kNN hybrid)  │
              │  Relationships   │         │  source chunks        │
              │  PEP paths       │         │  entity profiles      │
              │  Sanction paths  │         │  exposure profiles    │
              └──────────────────┘         └───────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Chat UI | Open WebUI | Browser-based chat, connects to LiteLLM |
| LLM gateway | LiteLLM | Routes to Ollama; swap models without code changes |
| Chat model | Qwen3-4B (Ollama) | Default local model, Apache 2.0 |
| Embedding model | nomic-embed-text (Ollama) | Local 768-dim embeddings, no API key |
| Agent framework | PydanticAI 0.4.2 | Thin tool-calling agent, no LangChain |
| Rate limiting | slowapi 0.1.9 | Per-IP rate limits on `/chat` and `/search` |
| API | FastAPI | Three routers: chat, entity, search |
| Graph DB | FalkorDB | Entity relationships, PEP/sanction paths (RedisGraph fork) |
| Vector DB | OpenSearch 2.13 | BM25+kNN hybrid; title/author boost fields |
| Observability | grafana/otel-lgtm | OTel traces, metrics, logs; four pre-built dashboards |
| Evals | RAGAS + LLM-as-judge | Faithfulness/relevancy/hallucination rate, exported to Grafana |
| Entity extraction | spaCy + GLiNER | Hybrid NER; GLiNER higher precision for financial entities |
| Entity resolution | RapidFuzz | Fuzzy match extracted mentions to graph canonical IDs |

---

## API Reference

### `POST /chat` — 10 req/min per IP

Natural language query. The agent decides which tools to call (max 8 LLM
requests per turn to prevent infinite loops).

```json
// request
{ "message": "Is Roman Abramovich subject to international sanctions?" }

// response
{ "answer": "..." }
```

### `POST /search` — 60 req/min per IP

Direct hybrid retrieval — bypasses the agent, returns ranked documents.

```json
// request
{ "query": "OFAC sanctions violation 2024", "limit": 10 }

// response
{
  "query": "...",
  "entities": [{ "id": "person:xyz", "name": "...", "schema_type": "Person" }],
  "documents": [{
    "id": "...", "text": "...",
    "source": "sec_edgar",
    "title": "Acme Corp 10-K 2024",
    "author": "Acme Corp",
    "jurisdiction": "US",
    "date": "2024-03-15",
    "score": 0.91
  }]
}
```

### `GET /entity/{entity_id}`

Full graph profile for an entity.

```json
{ "entity_id": "person:roman_abramovich", "data": {} }
```

### `GET /entity/{entity_id}/exposure`

PEP and sanctions exposure chain with risk level.

```json
{
  "entity_id": "person:roman_abramovich",
  "related_entities": [],
  "pep_exposure": [],
  "sanction_exposure": [],
  "risk_level": "HIGH"
}
```

---

## Grafana Dashboards

Open Grafana at <http://localhost:3100> — anonymous access, no login required.
Four dashboards are pre-provisioned from `resources/grafana/dashboards/`.

| Dashboard | URL | What it covers |
| --- | --- | --- |
| Overview | <http://localhost:3100/d/finagent-overview> | KPIs: request rate, latency, error rate, tool calls |
| Request Flow | <http://localhost:3100/d/finagent-flow> | Per-stage latency, Tempo traces, Loki logs, tool distribution |
| Retrieval Quality | <http://localhost:3100/d/finagent-retrieval> | Entity resolution rate, graph hits, circuit breakers |
| Evals | <http://localhost:3100/d/finagent-evals> | RAGAS scores + hallucination rate trend |

---

## Service URLs

| Service | URL |
| --- | --- |
| Chat UI (Open WebUI) | <http://localhost:3001> |
| FinAgent API | <http://localhost:8000> |
| API docs (Swagger) | <http://localhost:8000/docs> |
| LiteLLM proxy | <http://localhost:4000> |
| Grafana | <http://localhost:3100> |
| FalkorDB browser | <http://localhost:3000> |
| OpenSearch Dashboards | <http://localhost:5601> |
| Ollama | <http://localhost:11434> |

---

## Directory Structure

```text
FinAgent/
│
├── apps/
│   ├── api/
│   │   ├── main.py             App factory — registers routers, rate limiter, middleware
│   │   ├── limiter.py          slowapi Limiter singleton (keyed by remote IP)
│   │   ├── dependencies.py     lru_cache'd service factories for DI
│   │   └── routers/
│   │       ├── chat.py         POST /chat  (10/min per IP)
│   │       ├── entity.py       GET  /entity/{id}, /entity/{id}/exposure
│   │       └── search.py       POST /search (60/min per IP)
│   └── worker/
│       ├── ingestion_worker.py Runs all 5 sources, then profile builder
│       └── profile_builder.py  Generates entity/exposure profile documents
│
├── core/
│   ├── config.py               Pydantic-settings — all config from env
│   └── models.py               Shared Pydantic models (Entity, Document, …)
│
├── graph/
│   ├── redis_graph_repository.py  expand_entity, get_pep_paths, …
│   ├── entity_resolver.py         spaCy extract → exact graph lookup (apostrophe-safe) → fuzzy
│   └── exposure_service.py        aggregates PEP/sanction paths + risk level
│
├── vector/
│   ├── embeddings.py              embed() via LiteLLM proxy
│   ├── opensearch_repository.py   index_chunk, search, search_hybrid (BM25+kNN)
│   ├── retriever.py               RetrievalService with OTel sub-spans
│   └── index_setup.py             creates/migrates kNN + BM25 field mappings
│
├── llm/
│   ├── litellm_client.py          Thin OpenAI-compatible client
│   └── agent.py                   PydanticAI Agent + 4 tools + loop guard (request_limit=8)
│
├── observability/
│   ├── setup.py                   OTel SDK init (Tempo + Prometheus + Loki)
│   ├── metrics.py                 Histograms/counters: latency, tool_calls, evals
│   ├── tracing.py                 get_tracer() helper
│   └── circuit_breakers.py        aiobreaker breakers for graph/vector/LLM
│
├── eval/
│   └── runner.py                  RAGAS + LLM-judge eval suite; reads FINAGENT_API_BASE env var
│
├── ingestion/
│   ├── chunking.py
│   ├── entity_extraction.py       spaCy + GLiNER hybrid
│   ├── enrichment.py
│   ├── pipeline.py
│   └── sources/                   sec, courtlistener, icij, procurement, news
│
├── ingestion-pipelines/
│   └── sanctions-pipeline/        OpenSanctions → FalkorDB (standalone one-shot)
│
├── resources/
│   ├── litellm-config.yaml
│   └── grafana/
│       ├── dashboards/
│       │   ├── finagent-overview.json    KPI overview (hardcoded datasource UIDs)
│       │   ├── finagent-flow.json        Request flow + Tempo traces
│       │   ├── finagent-retrieval.json   Retrieval quality (HRT)
│       │   └── finagent-evals.json       RAGAS + hallucination scores
│       └── provisioning/dashboards/finagent.yaml
│
├── docker-compose.yml
├── requirements.txt               includes slowapi==0.1.9
├── requirements-eval.txt
├── Setup.md                       Step-by-step setup guide
├── Architecture.md                System design and decisions
└── Links.md                       All URLs — services, dashboards, data sources
```

---

## Data Pipeline

### 1 — OpenSanctions → FalkorDB

```text
OpenSanctions FTM JSON (~2 GB)
        │
        ▼
sanctionsParser.py     parses entity schema, caption, datasets, properties
        │
        ▼
redisWriter.py         UNWIND-batch GRAPH.QUERY (500 entities per call)
        │
        ▼
FalkorDB "entities"    Entity nodes + typed relationship edges
```

Relationship types: `OWNS`, `DIRECTOR_OF`, `ASSOCIATED_WITH`, `PARENT_OF`,
`SUBSIDIARY_OF`, `FAMILY_OF`, `MEMBER_OF`, `EMPLOYEE_OF`, `OPERATES`.

### 2 — 5 Sources → OpenSearch

```text
raw document text
        │
chunking.py            sentence-boundary split, 1200 chars, 200 overlap
        │
entity_extraction.py   spaCy NER merged with GLiNER (financial labels)
        │
enrichment.py          exact graph lookup → fuzzy (RapidFuzz 80%) → create
                       adds entity_ids list + mentions [{start,end,id}]
embed()                nomic-embed-text via LiteLLM → 768-dim vector
        │
OpenSearch bulk index  chunk + embedding + entity_ids + metadata stored
```

Checkpointing: each `document_id` is recorded in Redis per source. Re-running
the worker skips already-indexed documents.

### 3 — Entity and Exposure Profiles

After source ingestion, `profile_builder.py` writes two synthetic document
types into OpenSearch:

| `doc_type` | Content | Purpose |
| --- | --- | --- |
| `entity_profile` | Name, type, datasets, all relationships | Answers "Tell me about X" before filings exist |
| `exposure_profile` | 3-hop connected entities, PEP/sanction flag | Pre-built exposure chain for compliance queries |

---

## Query Flow

```text
User question
        │
POST /chat  →  ComplianceAgent.answer()  [max 8 LLM requests / turn]
        │
PydanticAI agent  (system: "compliance analyst for AML/PEP/sanctions…")
        │
        ├── expand_entity(name)    → graph lookup (if not found: explicit stop message)
        ├── search_documents(q)    → hybrid retrieval (entity resolve + graph + kNN)
        ├── get_entity(id)         → entity profile
        └── get_exposure(id)       → PEP/sanctions risk chain
        │
LiteLLM :4000  →  qwen3:4b (Ollama)  or  Claude (if ANTHROPIC_API_KEY set)
        │
Answer text  (all spans exported to Tempo via otel-lgtm :4317)
```

---

## Model Configuration

All model routing goes through LiteLLM (`resources/litellm-config.yaml`).
No code changes are needed to swap models — only config + env.

| Purpose | Model | Notes |
| --- | --- | --- |
| Chat (default) | `qwen3:4b` | ~3 GB, pulled by `ollama-init` |
| Embeddings | `nomic-embed-text` | ~270 MB, 768-dim local |
| Optional cloud | `claude-haiku` / `claude-sonnet` | Requires `ANTHROPIC_API_KEY` |

### To use Claude instead

1. Add `ANTHROPIC_API_KEY=sk-ant-...` to `.env`
2. Uncomment the Claude entries in `resources/litellm-config.yaml`
3. Set `PRIMARY_MODEL=claude-haiku` in `.env`
4. Restart: `docker compose restart litellm api`

---

## Design Decisions

**Graph-first retrieval.** Vector search alone cannot discover that a query
about "Oleg Deripaska" should also return documents about his associated
companies. The 2-hop graph expansion runs before vector search.

**Apostrophe-safe Cypher queries.** Names like "Deripaska's" previously broke
FalkorDB queries. `entity_resolver.py` now escapes single quotes before
string interpolation.

**Agent loop guard.** `expand_entity` returns an explicit "not found, do not
retry" message when an entity isn't in the graph, and the agent is capped at
8 LLM requests per turn via `UsageLimits(request_limit=8)`.

**Per-IP rate limiting via slowapi.** `/chat` (10/min) and `/search` (60/min)
use a shared `Limiter` singleton in `apps/api/limiter.py`. Returns `HTTP 429`
with `Retry-After`. Upgrade to Redis-backed storage for multi-replica deploys.

**Hardcoded Grafana datasource UIDs.** The otel-lgtm container provisions
Prometheus (`uid=prometheus`), Loki (`uid=loki`), and Tempo (`uid=tempo`).
Dashboard JSON files use these UIDs directly — template variable datasources
were removed as they fail to resolve in Grafana 13.

**LiteLLM as the only LLM boundary.** All model calls go through LiteLLM.
Swapping from local Ollama to Claude is a one-line env change.

**PydanticAI instead of LangChain.** The agent is ~60 lines. Tools are plain
Python functions injected via `AgentDeps`. No chains, no memory objects.

**OTel-first observability.** All services emit traces, metrics, and logs to
`grafana/otel-lgtm` via OTel SDK. Four Grafana dashboards cover overview KPIs,
request flow, retrieval quality, and eval scores.

**Eval isolation.** RAGAS and LangChain are kept in `requirements-eval.txt`
and `Dockerfile.eval` so the production API image stays lean. The eval runner
reads `FINAGENT_API_BASE` from the environment (set to `http://api:8000` in
docker-compose) so it works inside the Docker network without `--api` flags.
