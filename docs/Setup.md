# FinAgent — Setup Guide

**Navigation:** [README](../README.md) · [Architecture](Architecture.md) · [Links](Links.md) · [Demo](Demo.md)

---

## Prerequisites

| Requirement | Minimum | Notes |
| --- | --- | --- |
| Docker Desktop | 4.x | Enable WSL 2 backend on Windows |
| Docker Compose | v2 (`docker compose`) | Included with Docker Desktop |
| RAM | 16 GB | 24 GB recommended |
| Disk | 20 GB free | Models ~5 GB + data volumes ~5 GB |
| GPU | Optional | Ollama uses CPU if no CUDA GPU is detected |

---

## Environment Setup (one-time)

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
LITELLM_MASTER_KEY=sk-finagent-local       # any string — used as bearer token for LiteLLM
WEBUI_ADMIN_PASSWORD=change-me-now         # Open WebUI admin login password
SEC_USER_AGENT=FinAgent/1.0 you@email.com  # SEC EDGAR requires a real contact email
```

Optional keys that unlock more data:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # enables Claude models in addition to local Ollama models
COURTLISTENER_TOKEN=...          # raises CourtListener API rate limit from 100 to 5000 req/day
```

---

## Step 1 — Initialize All Databases and Services

Start the full infrastructure layer: FalkorDB (knowledge graph), OpenSearch (vector store), PostgreSQL (LiteLLM metadata), and Ollama (local LLM runtime).

```bash
docker compose up -d redis-stack opensearch postgres ollama otel-lgtm
```

Wait for all health checks to pass (takes ~60 seconds on first run):

```bash
docker compose ps
# All services should show "healthy"
```

Verify each store is reachable:

```bash
# FalkorDB / Redis
docker exec finagent-redis redis-cli ping
# → PONG

# OpenSearch
curl -s http://localhost:9200/_cluster/health | grep status
# → "status":"yellow" or "green"

# PostgreSQL
docker exec finagent-postgres pg_isready -U litellm
# → localhost:5432 - accepting connections
```

---

## Step 2 — Ingest Data and Download Models

This step is **one-time** (data persists in Docker volumes across restarts).

### 2a — Pull Ollama models

```bash
docker compose run --rm ollama-init
```

Downloads into the `ollama_data` volume:

| Model | Size | Purpose |
| --- | --- | --- |
| `qwen3:4b` | ~3 GB | Primary chat model |
| `nomic-embed-text` | ~270 MB | 768-dim local embeddings |

> Models survive container restarts. Only re-run this if you wipe the `ollama_data` volume.

### 2b — Start LiteLLM (required before ingestion)

```bash
docker compose up -d litellm
docker compose ps litellm   # wait for "healthy"
```

### 2c — Ingest OpenSanctions into FalkorDB (graph)

Downloads the OpenSanctions FTM dataset and loads entities + relationships into FalkorDB.

```bash
docker compose run --rm sanctions-ingestor
```

- Downloads `entities.ftm.json` (~2 GB, cached in `sanctions_data` volume on re-runs)
- Loads millions of entity nodes and typed relationship edges
- Takes 20–60 minutes depending on disk speed
- **Self-destructs** after completion (container is removed automatically)

### 2d — Ingest document corpus into OpenSearch (vector store)

Fetches from 5 public sources, chunks, embeds, and indexes into OpenSearch.

```bash
docker compose run --rm doc-ingestor
```

| Source | Content | Docs |
| --- | --- | --- |
| SEC EDGAR | 10-K / 10-Q / 8-K filings, AML search terms | ~300 |
| CourtListener | Court opinions and case records | ~200 |
| ICIJ Offshore Leaks | Panama + Paradise + Pandora Papers | ~3,000 |
| USASpending.gov | Government contracts, compliance keywords | ~500 |
| GDELT News | AML/sanctions news articles | ~500 |

- Each document is chunked (1,200 chars, 200 overlap), entity-extracted (spaCy + GLiNER), and embedded (nomic-embed-text via LiteLLM)
- Ingestion is **idempotent** — already-indexed document IDs are tracked in Redis and skipped on re-runs
- Takes 20–40 minutes
- **Self-destructs** after completion

> **Re-ingest only new data:** Re-run `doc-ingestor` anytime. It skips existing documents.  
> **Force full re-ingest:** `docker compose run --rm -e FORCE_REINGEST=1 doc-ingestor`

---

## Step 3 — Bring Up All Services

```bash
docker compose up -d api open-webui opensearch-dashboards
```

All services and their URLs:

| Service | URL | Notes |
| --- | --- | --- |
| **FinAgent API** | <http://localhost:8000> | Compliance chat + search API |
| **API Docs (Swagger)** | <http://localhost:8000/docs> | Interactive API reference |
| **Open WebUI** | <http://localhost:3001> | Chat UI — login: `admin@local.host` / `WEBUI_ADMIN_PASSWORD` |
| **LiteLLM Proxy** | <http://localhost:4000> | LLM gateway — Bearer `LITELLM_MASTER_KEY` |
| **Grafana** | <http://localhost:3100> | Observability dashboards — no login required |
| **FalkorDB Browser** | <http://localhost:3000> | Graph query UI — no login required |
| **OpenSearch Dashboards** | <http://localhost:5601> | Vector index explorer — no login required |
| **Ollama** | <http://localhost:11434> | Local model runtime |

Confirm the API is up:

```bash
curl -s http://localhost:8000/docs | grep -o "FinAgent"
# → FinAgent
```

---

## Step 4 — Sample Tests with curl

### Hybrid search (bypasses the agent)

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "OFAC sanctions violation 2024", "limit": 5}' | jq .
```

Expected response shape:

```json
{
  "query": "OFAC sanctions violation 2024",
  "entities": [
    { "id": "person:xyz", "name": "...", "schema_type": "Person" }
  ],
  "documents": [
    {
      "id": "sec_edgar:...",
      "text": "...",
      "source": "sec_edgar",
      "title": "Acme Corp 10-K 2024",
      "author": "Acme Corp",
      "jurisdiction": "US",
      "date": "2024-03-15",
      "score": 0.91
    }
  ]
}
```

### Chat (full agent — graph + vector + LLM)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Is Roman Abramovich subject to any international sanctions?"}' | jq .answer
```

> Note: First response takes 1–3 minutes with the local model (Qwen3:4b via Ollama).

### Entity profile lookup

```bash
# Replace with an entity ID returned by /search
curl -s http://localhost:8000/entity/person:roman_abramovich | jq .
```

### Exposure / risk chain

```bash
curl -s http://localhost:8000/entity/person:roman_abramovich/exposure | jq .
```

Expected:

```json
{
  "entity_id": "person:roman_abramovich",
  "related_entities": [...],
  "pep_exposure": [...],
  "sanction_exposure": [...],
  "risk_level": "HIGH"
}
```

### Sanctions-specific search

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Oleg Deripaska offshore entities Panama Papers", "limit": 5}' | jq '.documents[].title'
```

### Rate limit check

The API enforces per-IP rate limits. Exceeding them returns `HTTP 429`:

```bash
# /chat: 10 requests/minute
# /search: 60 requests/minute
# Trigger a 429 by hitting /search 61 times in one minute, or just verify the header:
curl -I -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}' 2>&1 | grep -E "HTTP|X-RateLimit|Retry-After"
```

---

## Step 5 — Run Evals (Optional)

Measures answer quality using RAGAS metrics and an LLM-as-judge hallucination detector. Requires the API and otel-lgtm to be running.

### Run all eval cases

```bash
docker compose run --rm eval-runner python -m eval.runner
```

### Run a specific tag

```bash
docker compose run --rm eval-runner python -m eval.runner --tag sanctions
docker compose run --rm eval-runner python -m eval.runner --tag hallucination_trap
```

The eval runner:

1. Calls `POST /search` and `POST /chat` for each test case
2. Scores responses with RAGAS (faithfulness, answer relevancy, context precision, context recall)
3. Scores hallucination with an LLM-as-judge
4. Exports scores to OTel → Prometheus → **FinAgent — Evals** Grafana dashboard

### Healthy score targets

| Metric | Healthy |
| --- | --- |
| Faithfulness | > 0.80 |
| Answer Relevancy | > 0.80 |
| Context Precision | > 0.70 |
| Context Recall | > 0.70 |
| Hallucination Rate | < 0.10 |

View scores live at: **<http://localhost:3100/d/finagent-evals>**

---

## Grafana Dashboards

All four dashboards are pre-provisioned from `resources/grafana/dashboards/` — no manual import needed. Open Grafana at <http://localhost:3100> (anonymous access, no login).

### FinAgent — Overview

**URL:** <http://localhost:3100/d/finagent-overview>

High-level KPIs across the full stack:

| Panel | What it shows |
| --- | --- |
| Total Docs Ingested | Cumulative OpenSearch chunk count |
| Chat Requests / min | Rolling rate of `/chat` calls |
| Search Requests / min | Rolling rate of `/search` calls |
| LLM Errors | Count of LLM failures from the circuit breaker |
| Request Latency | p50/p95/p99 end-to-end latency timeseries |
| Tool Calls / min | Agent tool invocation rate by tool name |
| Error Rate | HTTP 4xx/5xx rate across all endpoints |

---

### FinAgent — Request Flow

**URL:** <http://localhost:3100/d/finagent-flow>

End-to-end trace view from query to LLM response:

| Panel | What it shows |
| --- | --- |
| Chat Requests / min | Incoming request rate |
| p95 End-to-end Latency | Tail latency for full agent run |
| Tool Calls / min | Rate of tool invocations |
| Avg Entities / Query | Mean entity resolution per request |
| Avg Docs / Query | Mean documents retrieved per request |
| LLM Errors | Circuit breaker failure count |
| Stage Latency p50/p95/p99 | Per-stage breakdown: entity resolve → graph expand → embed → vector search → LLM |
| Avg Stage Latency | Bar gauge for each pipeline stage |
| Tool Calls by Tool | Time series per tool (search_documents, expand_entity, get_entity, get_exposure) |
| Tool Call Share | Pie chart of tool usage distribution |
| Live Traces | Linked Tempo traces for individual requests |
| Structured Logs | Loki log stream from `finagent-api` |

---

### FinAgent — Retrieval Quality (HRT)

**URL:** <http://localhost:3100/d/finagent-retrieval>

Hybrid Retrieval Testing metrics:

| Panel | What it shows |
| --- | --- |
| Search Requests / min | Incoming search rate |
| p95 Search Latency | Tail latency for `/search` endpoint |
| Entity Resolution Rate | Fraction of queries where ≥1 entity was resolved |
| Avg Docs Returned | Mean document count per search call |
| Graph Expansion Depth | Average 2-hop neighbour count |
| Open Circuit Breakers | Count of currently-open circuit breakers |
| Search Latency p50/p95/p99 | Latency percentile trends |
| Entity & Doc Counts per Query | Entity resolution vs. document count over time |
| Zero-Result Rate | Rate of queries that fell back from hybrid to pure kNN |
| Graph Expansion Hit Rate | Fraction of searches with successful graph expansion |
| Circuit Breaker Events | Open/half-open events by service (llm, opensearch, graph) |
| Embed & LLM Errors | Error count for embedding and LLM calls |

---

### FinAgent — Evals: Hallucination + RAGAS

**URL:** <http://localhost:3100/d/finagent-evals>

Eval quality dashboard (populated by `eval-runner`):

| Panel | What it shows |
| --- | --- |
| Faithfulness | Latest RAGAS faithfulness score (0–1) |
| Answer Relevancy | Latest RAGAS answer relevancy score |
| Context Precision | Latest RAGAS context precision score |
| Context Recall | Latest RAGAS context recall score |
| Hallucination Rate | Fraction of responses flagged as hallucinated (< 0.6 groundedness) |
| Overall Health | Composite gauge of all scores |
| RAGAS Score Trends | Time series of all 4 RAGAS metrics |
| Hallucination Rate Trend | Hallucination rate over time |
| All Scores — Latest Run | Bar gauge comparing all scores in one view |
| How to Run Evals | Instructions panel |
| Eval Runner Logs | Loki log stream from eval runs |

---

## Regular Startup (after first-time setup)

```bash
# Full stack
docker compose up -d

# Or selectively
docker compose up -d redis-stack opensearch postgres ollama otel-lgtm litellm api open-webui opensearch-dashboards
```

## Shutdown

```bash
docker compose down              # stop all, keep data volumes
docker compose down -v           # stop all AND delete volumes (full wipe)
```

## Rebuilding after code changes

```bash
docker compose build api
docker compose up -d api
```

---

## Troubleshooting

### `GRAPH.QUERY` unknown command

`redis/redis-stack:latest` dropped RedisGraph in v7.2. Use FalkorDB:

```bash
# docker-compose.yml must have: image: falkordb/falkordb:latest
docker compose rm -f redis-stack && docker compose up -d redis-stack
```

### OpenSearch container unhealthy (Linux / WSL2)

```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

### `404` for embedding model

```bash
docker exec finagent-ollama ollama pull nomic-embed-text
```

### Grafana dashboards show "data source not found"

Dashboard datasource UIDs must be hardcoded (`"prometheus"`, `"loki"`, `"tempo"`), not template variables. All four dashboards in this repo already use hardcoded UIDs and provision automatically.

### Chat response is empty / eval runner skips cases

Each `/chat` request with a local model can take 1–3 minutes. The eval runner uses a 360-second per-request timeout. If you see timeouts with a larger model, switch to `qwen3:4b`:

```bash
# In .env:
PRIMARY_MODEL=qwen3-4b
docker compose restart api
```

### Entity names with apostrophes (e.g. "Deripaska's") cause 500 on /search

Fixed in `graph/entity_resolver.py` — single quotes are escaped before Cypher interpolation. Rebuild if you're on an older image:

```bash
docker compose build api && docker compose up -d api
```
