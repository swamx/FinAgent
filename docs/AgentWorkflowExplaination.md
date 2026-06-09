# FinAgent — Service & Agent Workflow

**Navigation:** [README](../README.md) · [Architecture](Architecture.md) · [Ingestion Architectures](IngestionFlow.md) · [Links](Links.md) · [Demo](Demo.md)

---

> **Rendering note**
>
> - **GitHub**: renders Mermaid natively — no setup needed.
> - **VSCode**: install [`bierner.markdown-mermaid`](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) and open preview with `Ctrl+Shift+V`.
> - **PNG export**: `docs/workflow_td.png` — regenerate with `mmdc -i docs/workflow_td.mmd -o docs/workflow_td.png -s 3`.

---

## Service Flow

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "16px",
    "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor":         "#dbeafe",
    "primaryBorderColor":   "#3b82f6",
    "primaryTextColor":     "#1e3a5f",
    "secondaryColor":       "#fef9c3",
    "secondaryBorderColor": "#ca8a04",
    "tertiaryColor":        "#dcfce7",
    "tertiaryBorderColor":  "#15803d",
    "clusterBkg":    "#f8fafc",
    "clusterBorder": "#94a3b8",
    "lineColor":     "#64748b"
  },
  "flowchart": { "nodeSpacing": 40, "rankSpacing": 60, "curve": "basis" }
}}%%
flowchart TD

  Client(["Client"])

  subgraph APIGW["FastAPI  ·  Rate Limiter  ·  OTel Tracing"]
    direction LR
    RC["POST /chat\n10 req/min"]
    RS["POST /search\n60 req/min"]
    RE["GET /entity/{id}"]
    REX["GET /entity/{id}/exposure"]
  end

  Client --> APIGW

  subgraph CHAT["① Chat Flow"]
    direction TB
    CA["ComplianceAgent\npydantic-ai"]
    LLM["LiteLLM\nClaude / GPT"]
    TOOLS["Tool Dispatch\n─────────────────────────────\nsearch_documents  →  ② RetrievalService\nget_entity  →  ③ RedisGraphRepo\nexpand_entity  →  ③ RedisGraphRepo\nget_exposure  →  ③ ExposureService"]
    CA <-->|"multi-turn\ntool calls"| LLM
    CA --> TOOLS
  end

  subgraph SEARCH["② Search / Retrieval"]
    direction TB
    RV["RetrievalService"]
    ER["EntityResolver\nspaCy NER + fuzzy lookup"]
    EMB["Embed Query\n(dense vector)"]
    subgraph OSNODES["OpenSearch"]
      direction LR
      VSH["Hybrid kNN + BM25\n(entity-filtered)"]
      VSF["kNN fallback\n+ name supplement"]
    end
    MERGE["Merge & Deduplicate\n→ SearchResult"]
    RV --> ER & EMB
    ER -->|"entity IDs → 2-hop BFS"| VSH
    EMB --> VSH & VSF
    ER -.->|"no entities"| VSF
    VSH & VSF --> MERGE
  end

  subgraph GRAPH["③ Graph / Entity"]
    direction TB
    GR["RedisGraphRepository\nFalkorDB Cypher\nsanctions + KYB graphs"]
    ES["ExposureService\nPEP + sanction paths\nrisk: HIGH / MEDIUM / LOW"]
    ES --> GR
  end

  CHAT ~~~ SEARCH
  SEARCH ~~~ GRAPH

  RC  --> CA
  RS  --> RV
  RE  --> GR
  REX --> ES

  subgraph DB["Data Stores"]
    direction LR
    REDIS[("Redis / FalkorDB\n─────────────────\nEntity Graph\nName Index\nSanctions Graph\nPEP Graph")]
    OSDB[("OpenSearch\n─────────────────\nkNN Vector Index\nBM25 Text Index\nEntity Profiles\nNews  ·  Filings\nProcurement")]
  end

  REDIS ~~~ OSDB

  ER  -->|"name lookup"| REDIS
  GR  --> REDIS
  VSH --> OSDB
  VSF --> OSDB
```

> **Tool Dispatch** (inside Chat Flow): the agent's tools call into the other lanes at runtime.
> The `①②③` labels in the Tool Dispatch box show which lane each tool routes to.

### Endpoint Summary

| Endpoint | Rate Limit | Entry Point | Purpose |
| --- | --- | --- | --- |
| `POST /chat` | 10 / min | `ComplianceAgent` | Multi-turn LLM agent with tool use |
| `POST /search` | 60 / min | `RetrievalService` | Direct hybrid vector + graph search |
| `GET /entity/{id}` | — | `RedisGraphRepository` | Raw entity node profile |
| `GET /entity/{id}/exposure` | — | `ExposureService` | Risk classification with PEP / sanction paths |

---

## Agent Tool Reference: `get_entity` vs `get_exposure` vs `expand_entity`

| | `get_entity` | `get_exposure` | `expand_entity` |
| --- | --- | --- | --- |
| **Input** | `entity_id` (known graph ID) | `entity_id` (known graph ID) | `entity_name` (free-text string) |
| **First step** | Direct graph lookup | Direct graph lookup | NER + fuzzy/exact name resolution → resolves `entity_id` first |
| **Graph query** | `MATCH (e {id}) RETURN e LIMIT 1` — single node fetch | 3-hop BFS + PEP paths (depth 4) + sanction paths (depth 4) | 2-hop BFS `MATCH (e)-[*1..2]-(n)` |
| **Returns** | Raw node properties (name, schema, datasets, aliases) | Structured risk report: related entities, PEP paths, sanction paths, `risk_level` | Flat list of neighbouring `Entity` objects (id, name, schema_type) |
| **Risk classification** | None | Yes — `HIGH` if any sanction path, `MEDIUM` if any PEP path, `LOW` otherwise | None |
| **Who calls it** | Agent tool + REST `GET /entity/{id}` | Agent tool + REST `GET /entity/{id}/exposure` | Agent tool only (also used internally by `RetrievalService`) |
| **Typical agent use** | "Who is entity X? What are their known aliases?" | "Is entity X sanctioned or a PEP? What's the risk?" | "What other entities are connected to [name]?" — bridges free-text → graph neighbourhood |
| **Graph hops** | 0 (single node) | 3 BFS + 4 PEP/sanction path traversal | 2 BFS |
| **Fans out across graphs** | Yes (sanctions + KYB) | Yes (sanctions + KYB) | Yes (sanctions + KYB) |

### One-line summary

- **`get_entity`** — *"Give me the raw profile of this node."*
- **`get_exposure`** — *"Is this entity dirty, and how?"* — returns a risk verdict with evidence paths.
- **`expand_entity`** — *"I have a name string — who is it and who are their graph neighbours?"* — name resolution first, then traversal.
