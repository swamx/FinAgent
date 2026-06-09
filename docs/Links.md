# FinAgent — Links Reference

**Navigation:** [README](../README.md) · [Architecture](Architecture.md) · [Setup](Setup.md) · [Agent Workflow](AgentWorkflowExplaination.md) · [Ingestion](IngestionFlow.md) · [Demo](Demo.md)

---

## Local Services

| Service | URL | Credentials |
| --- | --- | --- |
| FinAgent API | <http://localhost:8000> | — |
| API Docs (Swagger UI) | <http://localhost:8000/docs> | — |
| API Docs (ReDoc) | <http://localhost:8000/redoc> | — |
| Open WebUI (Chat) | <http://localhost:3001> | `admin@local.host` / `WEBUI_ADMIN_PASSWORD` |
| LiteLLM Proxy | <http://localhost:4000> | Bearer `LITELLM_MASTER_KEY` |
| LiteLLM UI | <http://localhost:4000/ui> | Bearer `LITELLM_MASTER_KEY` |
| Grafana | <http://localhost:3100> | Anonymous — no login |
| FalkorDB Browser | <http://localhost:3000> | — |
| OpenSearch Dashboards | <http://localhost:5601> | — |
| OpenSearch API | <http://localhost:9200> | — |
| Ollama API | <http://localhost:11434> | — |
| PostgreSQL | `localhost:5432` | user: `litellm` / db: `litellm_db` |

---

## FinAgent API Endpoints

| Method | Path | Description | Rate Limit |
| --- | --- | --- | --- |
| `POST` | `/chat` | Full agent — graph + vector + LLM | 10 / min / IP |
| `POST` | `/search` | Hybrid retrieval only (no LLM) | 60 / min / IP |
| `GET` | `/entity/{id}` | Entity profile from FalkorDB | — |
| `GET` | `/entity/{id}/exposure` | PEP / sanctions risk chain | — |
| `GET` | `/docs` | Swagger UI | — |
| `GET` | `/redoc` | ReDoc UI | — |

---

## Grafana Dashboards

All dashboards require Grafana running at <http://localhost:3100>. Anonymous access — no login needed.

| Dashboard | URL | Description |
| --- | --- | --- |
| FinAgent — Overview | <http://localhost:3100/d/finagent-overview> | High-level KPIs: request rates, latency, tool calls, error rate |
| FinAgent — Request Flow | <http://localhost:3100/d/finagent-flow> | Per-stage latency, tool distribution, Tempo traces, Loki logs |
| FinAgent — Retrieval Quality | <http://localhost:3100/d/finagent-retrieval> | Entity resolution rate, graph expansion, circuit breakers |
| FinAgent — Evals | <http://localhost:3100/d/finagent-evals> | RAGAS scores, hallucination rate, eval trends |

### OTel Ingest Endpoints (exposed on host)

These are the ports your services write telemetry to — not browser URLs.

| Endpoint | Port | Protocol | Purpose |
| --- | --- | --- | --- |
| OTLP gRPC | `localhost:4317` | gRPC | Traces, metrics, logs from all Python services |
| OTLP HTTP | `localhost:4318` | HTTP | Alternative OTLP endpoint |

> Prometheus, Loki, and Tempo run **inside** the `otel-lgtm` container and are
> not directly accessible from the host. Query them through the Grafana UI at
> <http://localhost:3100> or via Grafana's data source proxy API.

---

## OpenSearch

| Resource | URL |
| --- | --- |
| Cluster health | <http://localhost:9200/_cluster/health> |
| Index list | <http://localhost:9200/_cat/indices?v> |
| Document count | <http://localhost:9200/fintech-docs/_count> |
| Index mapping | <http://localhost:9200/fintech-docs/_mapping> |
| OpenSearch Dashboards | <http://localhost:5601> |

---

## FalkorDB / Graph

Two graphs are maintained — `entities` (sanctions/PEP/crime) and `kyb` (company registries).

| Resource | URL / Command |
| --- | --- |
| Browser UI | <http://localhost:3000> |
| Redis CLI | `docker exec finagent-redis redis-cli` |
| **Sanctions graph (`entities`)** | |
| Node count | `GRAPH.QUERY entities "MATCH (n) RETURN count(n)"` |
| Edge count | `GRAPH.QUERY entities "MATCH ()-[r]->() RETURN count(r)"` |
| Entity schemas | `GRAPH.QUERY entities "MATCH (n:Entity) RETURN n.schema, count(n) ORDER BY count(n) DESC"` |
| Topics breakdown | `GRAPH.QUERY entities "MATCH (n:Entity) WHERE n.topics <> '' RETURN n.topics, count(n) ORDER BY count(n) DESC"` |
| **KYB graph (`kyb`)** | |
| Node count | `GRAPH.QUERY kyb "MATCH (n) RETURN count(n)"` |
| Edge count | `GRAPH.QUERY kyb "MATCH ()-[r]->() RETURN count(r)"` |
| Entity schemas | `GRAPH.QUERY kyb "MATCH (n:Entity) RETURN n.schema, count(n) ORDER BY count(n) DESC"` |
| Find company by name | `GRAPH.QUERY kyb "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS 'acme' RETURN n.id, n.name, n.country LIMIT 10"` |

---

## Ollama

| Resource | URL |
| --- | --- |
| List models | <http://localhost:11434/api/tags> |
| Model info | `http://localhost:11434/api/show` (POST) |
| Ollama docs | <https://ollama.com/library> |

---

## External Data Sources

| Source | URL | Notes |
| --- | --- | --- |
| OpenSanctions | <https://www.opensanctions.org> | PEP + sanctions dataset (FTM format) |
| OpenSanctions dataset | <https://data.opensanctions.org/datasets/latest/all/entities.ftm.json> | ~2 GB JSONL, auto-downloaded by sanctions-ingestor |
| SEC EDGAR full-text search | <https://efts.sec.gov/LATEST/search-index?q=%22AML%22&dateRange=custom&startdt=2024-01-01> | Used by `ingestion/sources/sec.py` |
| CourtListener | <https://www.courtlistener.com/api/rest/v4/search/> | Court opinions API |
| ICIJ Offshore Leaks | <https://offshoreleaks.icij.org/pages/database> | Panama + Paradise + Pandora Papers |
| USASpending.gov | <https://api.usaspending.gov/api/v2/search/spending_by_award/> | Government contracts |
| GDELT Doc 2.0 | <https://api.gdeltproject.org/api/v2/doc/doc> | News article API |

---

## Project Files

| File | Purpose |
| --- | --- |
| [docker-compose.yml](docker-compose.yml) | All service definitions |
| [resources/litellm-config.yaml](resources/litellm-config.yaml) | LLM model routing + OOM fallback chain |
| [resources/grafana/dashboards/](resources/grafana/dashboards/) | Pre-provisioned Grafana dashboard JSON files |
| [resources/grafana/provisioning/](resources/grafana/provisioning/) | Grafana dashboard provisioner config |
| [apps/api/main.py](apps/api/main.py) | FastAPI app factory + rate limiter wiring |
| [apps/api/limiter.py](apps/api/limiter.py) | slowapi rate limiter singleton |
| [apps/api/routers/chat.py](apps/api/routers/chat.py) | `POST /chat` — 10/min rate limit |
| [apps/api/routers/search.py](apps/api/routers/search.py) | `POST /search` — 60/min rate limit |
| [llm/agent.py](llm/agent.py) | PydanticAI compliance agent + 4 tools |
| [graph/entity_resolver.py](graph/entity_resolver.py) | NER + Cypher lookup (apostrophe-safe) |
| [vector/retriever.py](vector/retriever.py) | Hybrid search orchestrator |
| [vector/opensearch_repository.py](vector/opensearch_repository.py) | BM25+kNN hybrid search |
| [eval/runner.py](eval/runner.py) | RAGAS + LLM-judge eval runner |
| [observability/circuit_breakers.py](observability/circuit_breakers.py) | Per-service circuit breakers |
| [Setup.md](Setup.md) | Full setup guide with curl examples |
| [Architecture.md](Architecture.md) | System architecture and design decisions |
| [AgentWorkflowExplaination.md](AgentWorkflowExplaination.md) | Service & agent flow diagram, tool reference table |
| [IngestionFlow.md](IngestionFlow.md) | Ingestion pipeline + 4 alternative architectures with comparison |
| [Demo.md](Demo.md) | 3 live demo scenarios with trace IDs and expected outputs |
