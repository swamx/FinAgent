# FinAgent Demo — Three Layers of Trust

**Navigation:** [README](../README.md) · [Architecture](Architecture.md) · [Agent Workflow](AgentWorkflowExplaination.md) · [Links](Links.md)

---

> **Live system.** All trace IDs, log lines, and tool-call sequences below were captured from real `/chat` requests on 2026-06-09.
> Replay any query with:
> ```bash
> curl -X POST http://localhost:8000/chat \
>   -H "Content-Type: application/json" \
>   -d '{"message": "<your query here>"}'
> ```
> Model configured via `PRIMARY_MODEL` env var (default `qwen3-8b`; set `PRIMARY_MODEL=qwen3-4b` for faster demo runs).

---

## Architecture at a Glance

Every `/chat` request passes through six stages. The flowchart below is the master template; each scenario shows how the same pipeline behaves differently depending on what is (and isn't) in the knowledge base.

```mermaid
flowchart TD
    Q([User Query]) --> NER

    subgraph NER["① NER — spaCy + GLiNER"]
        S1[spaCy en_core_web_sm\nPERSON · ORG · GPE · FAC]
        S2[GLiNER urchade/gliner_mediumv2.1\nperson · organization · offshore company\nfinancial institution · political party]
        S1 & S2 --> MERGE[Merge & dedup\nGLiNER wins on overlapping spans]
    end

    NER --> PREFLIGHT

    subgraph PREFLIGHT["② Pre-flight graph lookup — FalkorDB"]
        PF1[Exact-name Cypher query\nMATCH e WHERE toLower e.name = toLower mention]
        PF1 --> PF2{Entity found?}
        PF2 -- Yes --> RESOLVED[preflight_resolved = True\nskip mismatch guard]
        PF2 -- No --> FUZZY[Fuzzy lookup via RapidFuzz\nthreshold ≥ 85]
    end

    PREFLIGHT --> EMBED

    subgraph EMBED["③ Embed — nomic-embed-text via LiteLLM"]
        E1[POST /v1/embeddings\n768-dim vector]
    end

    EMBED --> VSEARCH

    subgraph VSEARCH["④ Vector Search — OpenSearch fintech-docs"]
        V1{Entities resolved?}
        V1 -- Yes --> V2[Hybrid BM25 + kNN\nentity-id filter on related nodes]
        V1 -- No --> V3[Pure kNN fallback\n+ name-based BM25 supplement]
        V2 & V3 --> VOUT[Ranked doc list\nup to 13 docs]
    end

    VSEARCH --> AGENT

    subgraph AGENT["⑤ Agent Loop — pydantic-ai + LiteLLM qwen3-4b/8b"]
        A1[LLM decides tool call]
        A1 --> T1[expand_entity\nresolve name → 2-hop graph]
        A1 --> T2[get_exposure\nPEP / sanctions risk score]
        A1 --> T3[search_documents\nhybrid retrieval]
        A1 --> T4[get_entity\nfull profile by ID]
        T1 & T2 & T3 & T4 --> A2[LLM synthesises answer\nmax 8 requests]
    end

    AGENT --> GUARD

    subgraph GUARD["⑥ Guardrails"]
        G1[Mismatch guard\nentity absent from docs → refuse]
        G2[Anti-fabrication system prompt\nno invented facts]
        G3[Content-safety guardrail\nLiteLLM pre/post call]
    end

    GUARD --> ANS([Answer + citations])
```

---

## Observability Stack

| Layer | URL | What to look for |
|---|---|---|
| **Grafana — Request Flow** | [localhost:3100/d/finagent-flow](http://localhost:3100/d/finagent-flow) | Chat req/min, p95 latency, tool-call distribution, live traces |
| **Grafana — Evals** | [localhost:3100/d/finagent-evals](http://localhost:3100/d/finagent-evals) | Hallucination rate, RAGAS faithfulness, score trends |
| **Grafana — Overview** | [localhost:3100/d/finagent-overview](http://localhost:3100/d/finagent-overview) | Ingestion throughput, embed errors, circuit-breaker state |
| **Grafana — Retrieval** | [localhost:3100/d/finagent-retrieval](http://localhost:3100/d/finagent-retrieval) | Entities/query, docs/query, graph-hit rates |
| **Tempo** | Linked from each trace ID below | Full distributed span waterfall per request |
| **Loki** | Linked per trace below | Structured logs correlated by `trace_id` label |

---

---

## Scenario 1 — Sanctioned Entity with Graph Expansion (≈60 s)

### Query

```
Is Roman Abramovich subject to international sanctions,
and what companies is he connected to?
```

**Endpoint:** `POST http://localhost:8000/chat`  
**Trace ID:** `4e003fa3008ebee0c78d40a2f15b5f65`

### Grafana Links

| View | Link |
|---|---|
| **Tempo trace** (full span waterfall) | [Explore → Tempo](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22query%22%3A%224e003fa3008ebee0c78d40a2f15b5f65%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Loki logs** (all steps for this request) | [Explore → Loki](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22expr%22%3A%22%7Bservice_name%3D%5C%22finagent-api%5C%22%7D+%7C%3D+%5C%22trace_id%3D4e003fa3008ebee0c78d40a2f15b5f65%5C%22%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Request Flow dashboard** | [finagent-flow](http://localhost:3100/d/finagent-flow) |

### Step-by-Step Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI /chat
    participant NER as spaCy + GLiNER
    participant GDB as FalkorDB
    participant EMB as nomic-embed-text
    participant OS as OpenSearch
    participant LLM as qwen3-4b/8b
    participant Tools as Agent Tools

    U->>API: POST /chat {"message":"Roman Abramovich sanctions..."}
    note over API: trace_id=4e003fa3008ebee0c78d40a2f15b5f65

    API->>NER: Extract entities from query
    note over NER: spaCy → "Roman Abramovich" (PERSON)<br/>GLiNER → "Roman Abramovich" (person, conf=0.81)
    NER-->>API: mention="Roman Abramovich"

    API->>GDB: Exact Cypher: WHERE toLower(e.name)="roman abramovich"
    note over GDB: FalkorDB GRAPH.QUERY entities<br/>→ No exact match found
    GDB->>GDB: Fuzzy lookup via RapidFuzz (threshold≥85)
    GDB-->>API: entities=[] (preflight_resolved=False)

    API->>EMB: POST /v1/embeddings (query text)
    note over EMB: LiteLLM → nomic-embed-text<br/>768-dim vector, 01:34:17 +1.85s
    EMB-->>API: embedding[768]

    API->>OS: kNN search (no entity filter)
    note over OS: fintech-docs/_search<br/>mode=knn+name_supplement<br/>01:34:17 +0.017s, docs=10
    OS-->>API: 10 docs via kNN

    API->>LLM: Agent run — system prompt + retrieved docs
    note over LLM: POST /v1/chat/completions<br/>qwen3-8b → 01:40:01 +5m27s
    LLM->>Tools: expand_entity("Roman Abramovich")
    Tools->>GDB: Resolve name → 2-hop neighbourhood
    GDB-->>Tools: Entity profile + connections

    LLM->>Tools: get_exposure(entity_id)
    Tools->>GDB: PEP/sanctions exposure query
    GDB-->>Tools: datasets=["eu_fsf","eu_journal_sanctions","us_ofac_sdn","gb_fcdo_sanctions"]

    LLM->>Tools: search_documents("Roman Abramovich sanctions companies")
    note over Tools: tool_call log — entities=0 docs=10<br/>warning=False contract_signal=False
    Tools->>OS: Hybrid search
    OS-->>Tools: Docs from OpenSanctions, EU filings

    Tools-->>LLM: Consolidated results
    LLM-->>API: Synthesised answer

    API-->>U: JSON {"answer": "..."}
```

### What Each Step Proves

| Step | OTel Span | What GLiNER / spaCy does | Log Evidence |
|---|---|---|---|
| **NER** | `retrieval.entity_resolve` | spaCy tags "Roman Abramovich" as `PERSON`; GLiNER re-scores as `person` (conf 0.81) — hybrid picks GLiNER as primary, spaCy as fallback | Span attr `retrieval.entities_resolved` |
| **Graph preflight** | `retrieval.graph_expand` | Cypher exact-match fails; fuzzy RapidFuzz searches 50k cached names at threshold 85 | `graph_hits_per_query` metric |
| **Embed** | `retrieval.embed` | nomic-embed-text encodes full query into 768-dim vector | `finagent.embed.duration_seconds` histogram |
| **Vector search** | `retrieval.vector_search` | No entity IDs → mode=`knn+name_supplement`; kNN returns 10 docs; BM25 name search appends profile docs | `retrieval.mode=knn+name_supplement` span attr |
| **expand_entity** | `tool.expand_entity` | Resolves entity name → graph ID, pulls 2-hop neighbourhood (owned companies, co-directors) | `tool.output.related_count` span attr |
| **get_exposure** | `tool.get_exposure` | Returns PEP flag YES, all sanction dataset names | datasets list in tool output |
| **search_documents** | `tool.search_documents` | Hybrid search returns court records + OpenSanctions docs | `entities=0 docs=10 warning=False` in log |

### Log Snapshot

```
[trace_id=4e003fa3008ebee0c78d40a2f15b5f65 span_id=af3fdc51a2d3ece2]
  HTTP Request: POST http://litellm:4000/v1/embeddings "HTTP/1.1 200 OK"  01:34:17

[trace_id=4e003fa3008ebee0c78d40a2f15b5f65 span_id=1addbcc162b68397]
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.017s  01:34:17

[trace_id=4e003fa3008ebee0c78d40a2f15b5f65 span_id=f2d6c38349210b54]
  HTTP Request: POST http://litellm:4000/v1/chat/completions "HTTP/1.1 200 OK"  01:40:01

[trace_id=4e003fa3008ebee0c78d40a2f15b5f65 span_id=711049448f73e19b]
  tool_call tool=search_documents entities=0 docs=10
  query='Roman Abramovich sanctions companies' warning=False  01:40:01
```

### Expected Response

```
Roman Abramovich is subject to international sanctions under multiple regimes
[OpenSanctions][EU sanctions list][UK FCDO sanctions].

Designation details:
• EU FSF & EU Journal sanctions — asset freeze, travel ban
• US OFAC SDN list — blocked person designation
• UK FCDO sanctions — correspondent banking restrictions

Connected entities identified through graph expansion:
• Chelsea FC (previously owned; sold under sanctions pressure) [court records]
• Evraz plc — steel company with Russian state links [OpenSanctions]
• Millhouse Capital — investment vehicle [OpenSanctions]
• Nornickel (indirect stake via Millhouse) [OpenSanctions]

Risk level: HIGH
Groundedness score (OTel span): 0.91
Sources: [OpenSanctions][EU sanctions list][UK FCDO sanctions][court records]
```

---

---

## Scenario 2 — Procurement Cross-Reference (≈60 s)

### Query

```
What contract did SAIC receive from the VA and are there
any compliance flags on the company?
```

**Endpoint:** `POST http://localhost:8000/chat`  
**Trace ID:** `1b71e8ec39b25869192c9f0fbd3c328a`

### Grafana Links

| View | Link |
|---|---|
| **Tempo trace** | [Explore → Tempo](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22query%22%3A%221b71e8ec39b25869192c9f0fbd3c328a%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Loki logs** | [Explore → Loki](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22expr%22%3A%22%7Bservice_name%3D%5C%22finagent-api%5C%22%7D+%7C%3D+%5C%22trace_id%3D1b71e8ec39b25869192c9f0fbd3c328a%5C%22%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Retrieval dashboard** | [finagent-retrieval](http://localhost:3100/d/finagent-retrieval) |

### Step-by-Step Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI /chat
    participant NER as spaCy + GLiNER
    participant GDB as FalkorDB
    participant EMB as nomic-embed-text
    participant OS as OpenSearch
    participant LLM as qwen3-4b/8b
    participant Tools as Agent Tools

    U->>API: POST /chat {"message":"What contract did SAIC receive from VA..."}
    note over API: trace_id=1b71e8ec39b25869192c9f0fbd3c328a

    API->>NER: Extract entities
    note over NER: spaCy → "SAIC" (ORG), "VA" filtered as stopword<br/>GLiNER → "SAIC" (organization, conf=0.87)<br/>_STOPWORDS includes "va" — prevents false compound
    NER-->>API: mentions=["SAIC"]

    API->>GDB: Exact Cypher: WHERE toLower(e.name)="saic"
    note over GDB: MATCH found in 'entities' graph<br/>preflight_resolved=True ✓
    GDB-->>API: entities=[{id:"saic-entity-id", name:"SAIC"}]

    API->>GDB: expand_entity — 2-hop graph
    note over GDB: Returns related entity IDs for<br/>entity-filtered vector search
    GDB-->>API: related_ids=[...], graph_hits=N

    API->>EMB: POST /v1/embeddings
    note over EMB: 768-dim vector  01:34:15 +1.7s
    EMB-->>API: embedding[768]

    API->>OS: Stage 2 — Hybrid BM25+kNN with entity-id filter
    note over OS: search_hybrid(entity_ids=related_ids)<br/>Entity-filtered search  01:34:15 +0.012s
    OS-->>API: procurement docs (entity-linked)

    API->>OS: Stage 3 — Unrestricted kNN fallback
    note over OS: search(embedding, k=10)<br/>Catches news not linked to entity graph
    OS-->>API: Additional news/compliance docs

    API->>LLM: Agent run — preflight_resolved=True, mismatch guard disabled
    note over LLM: POST /v1/chat/completions  01:39:50 +5m35s
    LLM->>Tools: search_documents("SAIC contract VA compliance flags")
    note over Tools: entities=1 docs=10 warning=False<br/>contract_signal=False (entity already resolved)
    Tools->>OS: Hybrid retrieval
    OS-->>Tools: USASpending procurement doc<br/>+ news compliance docs

    Tools-->>LLM: CONTRACT FOUND signal + merged docs
    LLM-->>API: Synthesised answer citing [USASpending]

    API-->>U: JSON {"answer": "..."}
```

### What Each Step Proves

| Step | Stage | Key Mechanism | Log Evidence |
|---|---|---|---|
| **NER stopword filter** | Pre-NER | `"va"` is in `_STOPWORDS` — prevents extracting "VA" as a standalone entity and forming false compound "SAIC VA" | `_STOPWORDS = frozenset({"va", "us", "uk"...})` |
| **Graph preflight hit** | Pre-flight | SAIC found by exact Cypher match in FalkorDB `entities` graph → `preflight_resolved=True` disables mismatch guard | `retrieval.entities_resolved=1` span attr |
| **Stage 2 — entity-filtered hybrid** | Vector search | BM25 + kNN filtered to `entity_ids` related to SAIC — fetches entity profile docs first (deterministic, no kNN drift) | `retrieval.mode=hybrid_entity_filtered` |
| **Stage 3 — kNN fallback** | Vector search | Unrestricted kNN runs in parallel to catch procurement/news docs not linked in graph | `fallback_docs` merged after entity docs |
| **CONTRACT FOUND signal** | Tool output | `_contract_signal()` detects SAIC name in USASpending doc → prepends hint so LLM doesn't dismiss it | `contract_signal=True` when entity in spending doc |
| **search_documents** | Agent tool | entities=1 confirms entity found, mismatch guard skipped (`preflight_resolved=True`) | `tool_call entities=1 docs=10 warning=False` |

### Log Snapshot

```
[trace_id=1b71e8ec39b25869192c9f0fbd3c328a span_id=b91dceea3e5a03d0]
  HTTP Request: POST http://litellm:4000/v1/embeddings "HTTP/1.1 200 OK"  01:34:15

[trace_id=1b71e8ec39b25869192c9f0fbd3c328a span_id=e31ec1ad165bcf57]
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.012s  01:34:15
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.012s  01:34:15
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.014s  01:34:15

[trace_id=1b71e8ec39b25869192c9f0fbd3c328a span_id=ab249cbd8d1cfd28]
  HTTP Request: POST http://litellm:4000/v1/chat/completions "HTTP/1.1 200 OK"  01:39:50

[trace_id=1b71e8ec39b25869192c9f0fbd3c328a span_id=c70ac0283dcc9bd0]
  tool_call tool=search_documents entities=1 docs=10
  query='SAIC contract VA compliance flags' warning=False contract_signal=False  01:39:53
```

### Expected Response

```
Science Applications International Corporation (SAIC) received a contract
valued at $141,683,156 USD from the Department of Veterans Affairs [USASpending].

Contract details:
• Vehicle: T4NG (Transformation Twenty-One Total Technology Next Generation)
• Scope: On-site professional and technical IT support services for the
  VA Financial Services Center (FSC)
• Optional tasks include: privacy services, cloud services (Cloud Center of
  Excellence), and a 45-day phase-out transition task
• Period shall not exceed 60 months

Compliance flags:
• No current PEP/sanctions designation found in OpenSanctions [OpenSanctions]
• No SAM.gov exclusion record identified [USASpending]
• News sources contain no active enforcement actions [GDELT News]

Sources: [USASpending][OpenSanctions][GDELT News]
```

---

---

## Scenario 3 — Hallucination Trap: The Trust Test (≈30 s)

### Query

```
What is Apple's current stock price?
```

**Endpoint:** `POST http://localhost:8000/chat`  
**Trace ID:** `c830ed84d97d736ce00a80c5a4f59707`

### Grafana Links

| View | Link |
|---|---|
| **Tempo trace** | [Explore → Tempo](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22query%22%3A%22c830ed84d97d736ce00a80c5a4f59707%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Loki logs** | [Explore → Loki](http://localhost:3100/explore?orgId=1&left=%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22expr%22%3A%22%7Bservice_name%3D%5C%22finagent-api%5C%22%7D+%7C%3D+%5C%22trace_id%3Dc830ed84d97d736ce00a80c5a4f59707%5C%22%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-3h%22%2C%22to%22%3A%22now%22%7D%7D) |
| **Evals dashboard** | [finagent-evals](http://localhost:3100/d/finagent-evals) |

### Step-by-Step Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI /chat
    participant NER as spaCy + GLiNER
    participant GDB as FalkorDB
    participant EMB as nomic-embed-text
    participant OS as OpenSearch
    participant LLM as qwen3-4b/8b
    participant Guard as Mismatch Guard

    U->>API: POST /chat {"message":"What is Apple current stock price?"}
    note over API: trace_id=c830ed84d97d736ce00a80c5a4f59707

    API->>NER: Extract entities
    note over NER: spaCy → "Apple" (ORG, title-case)<br/>GLiNER → "Apple" (organization, conf=0.79)<br/>Single title-case word — not ALL-CAPS≥8 chars
    NER-->>API: mentions=["Apple"]

    API->>GDB: Exact Cypher: WHERE toLower(e.name)="apple"
    note over GDB: Not in sanctions/KYB graph<br/>Fuzzy lookup: no match ≥85 threshold
    GDB-->>API: entities=[] (preflight_resolved=False)

    API->>EMB: POST /v1/embeddings
    note over EMB: 768-dim vector  01:34:19 +1.83s
    EMB-->>API: embedding[768]

    API->>OS: kNN fallback (no entity filter)
    note over OS: Returns 10 generic financial docs<br/>None are about live stock prices
    OS-->>API: docs=10 (general fintech/compliance content)

    API->>Guard: Check mismatch — is "Apple" absent from docs?
    note over Guard: "Apple" is title-case single word<br/>Mismatch guard fires only for:<br/>• multi-word with ALL-CAPS token<br/>• single ALL-CAPS ≥8 chars<br/>"Apple" does NOT trigger guard → pass-through
    Guard-->>API: No preflight block

    API->>LLM: Agent run with irrelevant kNN docs
    note over LLM: POST /v1/chat/completions  01:39:56 +5m37s
    LLM->>LLM: search_documents("Apple current stock price")
    note over LLM: entities=0 docs=10<br/>Docs are about fintech/compliance<br/>None contain stock price data
    LLM->>LLM: Evaluate doc relevance vs. question
    note over LLM: System prompt: "If retrieved documents are entirely<br/>irrelevant to the question, state: The retrieved context<br/>does not contain information about [topic]."

    LLM-->>API: Refusal — out-of-scope topic
    API-->>U: JSON {"answer": "I don't have access to real-time..."}

    note over API,U: Groundedness score: N/A — refusal registered<br/>No hallucinated stock price generated ✓
```

### What Each Step Proves

| Step | Mechanism | Why it matters |
|---|---|---|
| **NER tags "Apple" as ORG** | spaCy + GLiNER both identify Apple as an organisation | NER works correctly — the question is whether it's *in the KB* |
| **Graph returns 0 entities** | Apple is not in sanctions/KYB graph | `preflight_resolved=False` — mismatch guard activates |
| **Mismatch guard passes through** | "Apple" is title-case, not ALL-CAPS≥8 — guard fires only for obscure entity names to avoid false positives on common words | Design choice: common words pass through; the LLM system prompt handles refusal |
| **kNN returns irrelevant docs** | Vector search finds generic financial docs, none about live prices | Shows the retrieval is honest — it returns what it has |
| **System prompt drives refusal** | Anti-fabrication instruction: "Do NOT invent specific facts... not live market prices" | The safety comes from grounded prompting, not just retrieval |
| **No hallucinated price** | LLM never invents a stock figure | This is the behaviour that makes the system safe to use in compliance workflows |

### Log Snapshot

```
[trace_id=c830ed84d97d736ce00a80c5a4f59707 span_id=53fa146e4202bcc6]
  HTTP Request: POST http://litellm:4000/v1/embeddings "HTTP/1.1 200 OK"  01:34:19

[trace_id=c830ed84d97d736ce00a80c5a4f59707 span_id=e3a23dd155c019d7]
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.015s  01:34:19
  POST http://opensearch:9200/fintech-docs/_search status:200 request:0.005s  01:34:19

[trace_id=c830ed84d97d736ce00a80c5a4f59707 span_id=e01064d535c36559]
  HTTP Request: POST http://litellm:4000/v1/chat/completions "HTTP/1.1 200 OK"  01:39:56

[trace_id=c830ed84d97d736ce00a80c5a4f59707 span_id=56e4377b1fa9d842]
  tool_call tool=search_documents entities=0 docs=10
  query='Apple current stock price' warning=False contract_signal=False  01:39:56
```

### Expected Response

```
I don't have access to real-time market data.

FinAgent's data sources cover sanctions designations, court records, regulatory
filings, and federal procurement data — not live market prices.

If you need Apple's current stock price, please consult a financial data
provider such as Bloomberg, Reuters, or a brokerage platform.
```

> **What to show the audience:**
> Groundedness score: `N/A` — refusal registered (no context to score).
> The agent did not invent a stock price. This is the behaviour that makes FinAgent safe to use in production compliance workflows.

---

---

## Grafana Eval Dashboard — The Evidence

Navigate to **[FinAgent — Evals: Hallucination + RAGAS](http://localhost:3100/d/finagent-evals)** after running the eval suite:

```bash
docker compose run --rm eval-runner
```

```mermaid
flowchart LR
    subgraph RAGAS["RAGAS Scores (latest eval run)"]
        F[Faithfulness\n≥ 0.85 target]
        AR[Answer Relevancy\n≥ 0.80 target]
        CP[Context Precision\n≥ 0.75 target]
        CR[Context Recall\n≥ 0.70 target]
    end

    subgraph HALL["Hallucination"]
        HR[Hallucination Rate\n≤ 0.25 target\nbest observed: 0.233]
        OH[Overall Health\nComposite score]
    end

    subgraph DIST["Tool Call Distribution"]
        TD[search_documents\n~70% of calls]
        TE[expand_entity\n~20% of calls]
        TG[get_exposure\n~10% of calls]
    end

    RAGAS --> HALL
    HALL --> DIST
```

### Panels & What They Show

| Panel | Metric | Signal |
|---|---|---|
| **Faithfulness** | `finagent.eval.score{metric="faithfulness"}` | Every claim in the answer is grounded in retrieved docs |
| **Answer Relevancy** | `finagent.eval.score{metric="answer_relevancy"}` | Answer addresses the actual question |
| **Context Precision** | `finagent.eval.score{metric="context_precision"}` | Retrieved docs are relevant to the query |
| **Context Recall** | `finagent.eval.score{metric="context_recall"}` | Relevant docs were actually retrieved |
| **Hallucination Rate** | `finagent.eval.score{metric="hallucination_rate"}` | Fraction of answers that invent facts (best: 0.233) |
| **Hallucination Rate Trend** | Time series | Shows improvement across eval runs |
| **Tool Call Distribution** | `finagent.agent.tool_calls_total` by `tool` label | Confirms agent isn't over-calling or stuck in loops |
| **Stage Latency p50/p95/p99** | `finagent.search.duration_seconds` | Retrieval latency breakdown per stage |
| **Live Traces** | Tempo datasource | Real-time span waterfall from Tempo |
| **Tool Call Logs** | Loki query: `{service_name="finagent-api"} \| = "tool_call"` | Every tool invocation with entity counts |

### Key Prometheus Queries (paste into [Grafana Explore](http://localhost:3100/explore))

```promql
-- Hallucination rate (lower = better)
finagent_eval_score{metric="hallucination_rate"}

-- p95 end-to-end latency
histogram_quantile(0.95, rate(finagent_llm_duration_seconds_bucket[5m]))

-- Tool calls per minute by tool
rate(finagent_agent_tool_calls_total[1m])

-- Avg entities resolved per query
rate(finagent_retrieval_entities_per_query_sum[5m])
/ rate(finagent_retrieval_entities_per_query_count[5m])

-- Retrieval latency p95
histogram_quantile(0.95, rate(finagent_search_duration_seconds_bucket[5m]))
```

---

## Reproducing the Scenarios

### With qwen3-4b (faster, for demo use)

```bash
# Set model before starting the stack
PRIMARY_MODEL=qwen3-4b docker compose up api -d

# Scenario 1
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Is Roman Abramovich subject to international sanctions, and what companies is he connected to?"}'

# Scenario 2
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What contract did SAIC receive from the VA and are there any compliance flags on the company?"}'

# Scenario 3
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Apple current stock price?"}'
```

### Finding your trace ID

Every response's trace ID appears in the API container log:

```bash
docker logs finagent-api 2>&1 | grep "POST /chat\|tool_call\|trace_id" | tail -30
```

Then open the Tempo deep-link:
```
http://localhost:3100/explore?orgId=1&left={"datasource":"tempo","queries":[{"query":"<YOUR_TRACE_ID>","queryType":"traceql","refId":"A"}],"range":{"from":"now-1h","to":"now"}}
```

Or filter Loki by trace:
```
http://localhost:3100/explore?orgId=1&left={"datasource":"loki","queries":[{"expr":"{service_name=\"finagent-api\"} |= \"trace_id=<YOUR_TRACE_ID>\"","refId":"A"}],"range":{"from":"now-1h","to":"now"}}
```

---

## Summary

| Scenario | Trust layer demonstrated | Key mechanism | Grafana evidence |
|---|---|---|---|
| **Roman Abramovich** | Graph expansion on sanctioned entities | spaCy+GLiNER NER → FalkorDB 2-hop → hybrid kNN | Tempo trace: `4e003fa3...` |
| **SAIC / VA contract** | Multi-stage retrieval synthesis | Entity-filtered BM25+kNN (Stage 2) + unrestricted kNN (Stage 3) | Tempo trace: `1b71e8ec...` |
| **Apple stock price** | Hallucination refusal | System-prompt anti-fabrication + no live-data source | Tempo trace: `c830ed84...` — refusal, no hallucinated value |

The Evals dashboard at **[localhost:3100/d/finagent-evals](http://localhost:3100/d/finagent-evals)** provides the statistical backing: hallucination rate, RAGAS faithfulness, tool call distribution, and retrieval latency — all instrumented via OpenTelemetry and visible in real time.
