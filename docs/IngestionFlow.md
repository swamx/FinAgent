# FinAgent — Ingestion Pipeline: Architectures

**Navigation:** [README](../README.md) · [Architecture](Architecture.md) · [Agent Workflow](AgentWorkflowExplaination.md) · [Links](Links.md)

---

> **Rendering:** GitHub renders all `mermaid` blocks natively. VSCode needs `bierner.markdown-mermaid` (`Ctrl+Shift+V`).
> PNG of the current architecture: `docs/ingest_current.png`

---

## Current Architecture — Python Async Worker

A single Python process run on demand or schedule. All sources are fetched in parallel via `asyncio.gather`; each source is then processed sequentially through the pipeline with a semaphore bounding concurrency to 32.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "15px", "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor": "#dbeafe", "primaryBorderColor": "#3b82f6", "primaryTextColor": "#1e3a5f",
    "secondaryColor": "#dcfce7", "secondaryBorderColor": "#15803d",
    "clusterBkg": "#f8fafc", "clusterBorder": "#94a3b8", "lineColor": "#64748b"
  },
  "flowchart": { "nodeSpacing": 35, "rankSpacing": 50, "curve": "basis" }
}}%%
flowchart TD

  SCHED(["Scheduler / CLI\npython -m apps.worker.ingestion_worker"])

  subgraph FETCH["① Parallel Fetch  (asyncio.gather)"]
    SOURCES["Multiple Sources\ne.g. SEC · CourtListener · ICIJ · Procurement · News"]
  end

  subgraph PIPELINE["② IngestionPipeline  (per source, semaphore=32)"]
    direction TB
    CHUNK["Chunk Text\n1 200 chars · 200 overlap"]
    ENRICH["EntityEnricher\nspaCy NER + GLiNER\nfuzzy / exact entity link → ID"]
    EMBED["Batch Embed\n128 chunks / call\nasync run_in_executor"]
    CHECK["Checkpoint\nRedis SADD / SISMEMBER\n(idempotent skip)"]
    BIDX["Bulk Index\nOpenSearch  (circuit-breaker)"]
    CHUNK --> ENRICH --> EMBED --> CHECK --> BIDX
  end

  subgraph PROFILES["③ ProfileBuilder  (post-ingest)"]
    direction TB
    EP["Build Entity Profiles\nname · aliases · relationships"]
    EXP["Build Exposure Profiles\nPEP paths · sanction paths"]
    PEB["Embed + Bulk Index Profiles"]
    EP --> EXP --> PEB
  end

  subgraph STORES["Data Stores"]
    direction LR
    REDIS[("Redis / FalkorDB\n─────────────\nEntity Graph\nCheckpoints\nName Index")]
    OS[("OpenSearch\n─────────────\nChunk Index\n(kNN + BM25)\nProfile Index")]
  end

  SCHED --> FETCH --> PIPELINE --> PROFILES
  ENRICH -->|"entity lookup\n+ create node"| REDIS
  BIDX --> OS
  PEB  --> OS
```

---

## Alternative ①  —  Kafka + Spark

Each source publishes raw documents to a Kafka topic. Spark Structured Streaming consumes in micro-batches, with a separate job per stage writing results back to Kafka before the next stage picks up. Profile building runs as a Spark Batch job triggered on completion.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "15px", "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor": "#dbeafe", "primaryBorderColor": "#3b82f6", "primaryTextColor": "#1e3a5f",
    "secondaryColor": "#fef9c3", "secondaryBorderColor": "#ca8a04",
    "tertiaryColor": "#ede9fe", "tertiaryBorderColor": "#7c3aed",
    "clusterBkg": "#f8fafc", "clusterBorder": "#94a3b8", "lineColor": "#64748b"
  },
  "flowchart": { "nodeSpacing": 35, "rankSpacing": 50, "curve": "basis" }
}}%%
flowchart TD

  SOURCES["Multiple Sources\n(Kafka Producers)\ne.g. SEC · CourtListener · ICIJ · Procurement · News"]

  subgraph KAFKA["Apache Kafka  (durable log)"]
    direction TB
    K1["Topic: raw-documents"]
    K2["Topic: chunked-docs"]
    K3["Topic: enriched-chunks"]
    K4["Topic: embedded-chunks"]
    K1 ~~~ K2 ~~~ K3 ~~~ K4
  end

  subgraph SPARK["Spark Structured Streaming  (micro-batch)"]
    direction TB
    SP1["Spark Job: Chunker\nFlatMap · 1 200 char / 200 overlap"]
    SP2["Spark Job: Enricher\nspaCy + GLiNER  (distributed NLP)\nentity resolve → graph write"]
    SP3["Spark Job: Embedder\nBatch embedding  (GPU executors)"]
    SP4["Spark Job: Indexer\nBulk write sink  (OpenSearch connector)"]
    SP5["Spark Batch: ProfileBuilder\nentity + exposure profiles"]
    SP1 ~~~ SP2 ~~~ SP3 ~~~ SP4 ~~~ SP5
  end

  subgraph STORES["Data Stores"]
    direction LR
    REDIS[("Redis / FalkorDB\nEntity Graph")]
    OS[("OpenSearch\nChunk + Profile Index")]
    HDFS[("HDFS / S3\nSpark Checkpoints + WAL")]
  end

  SOURCES --> K1
  K1 --> SP1 --> K2
  K2 --> SP2 --> K3
  K3 --> SP3 --> K4
  K4 --> SP4 --> OS
  SP4 -->|"completion event"| SP5 --> OS
  SP2 -->|"entity upserts"| REDIS
  SPARK -->|"WAL + offsets"| HDFS
```

---

## Alternative ②  —  Kafka + Flink

A single continuous Flink DataStream job consumes raw documents from Kafka and processes them through chained operators — including keyed-state deduplication and Async I/O for non-blocking NER and embedding calls. The OpenSearch sink uses two-phase commit for exactly-once delivery. Profile building runs as a Flink Batch / Table API job.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "15px", "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor": "#dbeafe", "primaryBorderColor": "#3b82f6", "primaryTextColor": "#1e3a5f",
    "secondaryColor": "#dcfce7", "secondaryBorderColor": "#15803d",
    "tertiaryColor": "#ede9fe", "tertiaryBorderColor": "#7c3aed",
    "clusterBkg": "#f8fafc", "clusterBorder": "#94a3b8", "lineColor": "#64748b"
  },
  "flowchart": { "nodeSpacing": 35, "rankSpacing": 50, "curve": "basis" }
}}%%
flowchart TD

  SOURCES["Multiple Sources\n(Kafka Producers)\ne.g. SEC · CourtListener · ICIJ · Procurement · News"]

  K_IN["Kafka Topic: raw-documents"]

  subgraph FLINK["Apache Flink  (DataStream API — single continuous job)"]
    direction TB
    F1["FlatMap: Chunk Text\n1 200 chars · 200 overlap"]
    F2["KeyedProcessFunction: Deduplicate\nKeyed State on doc_id\n(exactly-once barrier)"]
    F3["Async I/O: EntityEnricher\nspaCy + GLiNER  (non-blocking)\nentity resolve + graph write"]
    F4["Async I/O: Embedder\nbatch embedding  (non-blocking)"]
    F5["OpenSearch Sink\n2-phase commit  (exactly-once)"]
    F1 --> F2 --> F3 --> F4 --> F5
  end

  FB["Flink Batch / Table API:\nProfileBuilder  (entity + exposure profiles)"]

  subgraph STORES["Data Stores"]
    direction LR
    REDIS[("Redis / FalkorDB\nEntity Graph")]
    OS[("OpenSearch\nChunk + Profile Index")]
    S3[("S3 / HDFS\nFlink State Checkpoints\n(Chandy-Lamport snapshots)")]
  end

  SOURCES --> K_IN --> F1
  F5 --> OS
  F5 -->|"source.complete"| FB --> OS
  F3 -->|"entity upserts"| REDIS
  FLINK -->|"distributed snapshots"| S3
```

---

## Alternative ③  —  Kafka + Knative Eventing

Each pipeline stage is a separate Kubernetes micro-service that scales to zero when idle. Kubernetes CronJobs emit `doc.fetched` CloudEvents to a Knative Broker (backed by a Kafka Channel for durability). Triggers route each event type to the appropriate service, which processes the payload and emits a new event for the next stage.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "15px", "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor": "#dbeafe", "primaryBorderColor": "#3b82f6", "primaryTextColor": "#1e3a5f",
    "secondaryColor": "#fef9c3", "secondaryBorderColor": "#ca8a04",
    "tertiaryColor": "#fce7f3", "tertiaryBorderColor": "#be185d",
    "clusterBkg": "#f8fafc", "clusterBorder": "#94a3b8", "lineColor": "#64748b"
  },
  "flowchart": { "nodeSpacing": 35, "rankSpacing": 50, "curve": "basis" }
}}%%
flowchart TD

  CRON["Kubernetes CronJobs\ne.g. SEC · CourtListener · ICIJ · Procurement · News\n→ emit CloudEvent: doc.fetched"]

  subgraph KNATIVE["Knative Eventing  (Kubernetes)"]
    direction TB
    BROKER["Knative Broker\n(CloudEvents router  ·  Kafka Channel backend)"]

    subgraph SVCS["Micro-services  (scale-to-zero pods)"]
      direction LR
      SVC_CHUNK["ChunkService\ndoc.fetched → doc.chunked"]
      SVC_ENRICH["EnrichService\ndoc.chunked → doc.enriched\nspaCy + GLiNER"]
      SVC_EMBED["EmbedService\ndoc.enriched → doc.embedded"]
      SVC_INDEX["IndexService\ndoc.embedded → source.complete"]
      SVC_PROFILE["ProfileService\nsource.complete → done"]
    end
  end

  KAFKA_CHAN[("Kafka Channel\ndurable CloudEvent log\n(retention + replay)")]

  subgraph STORES["Data Stores"]
    direction LR
    REDIS[("Redis / FalkorDB\nEntity Graph")]
    OS[("OpenSearch\nChunk + Profile Index")]
  end

  CRON -->|"doc.fetched"| BROKER
  BROKER -->|"doc.fetched"| SVC_CHUNK  -->|"doc.chunked"| BROKER
  BROKER -->|"doc.chunked"| SVC_ENRICH -->|"doc.enriched"| BROKER
  BROKER -->|"doc.enriched"| SVC_EMBED  -->|"doc.embedded"| BROKER
  BROKER -->|"doc.embedded"| SVC_INDEX  -->|"source.complete"| BROKER
  BROKER -->|"source.complete"| SVC_PROFILE

  BROKER <-->|"durable event log"| KAFKA_CHAN

  SVC_INDEX   --> OS
  SVC_ENRICH  -->|"entity upserts"| REDIS
  SVC_PROFILE --> OS
```

---

## Alternative ④  —  AWS Lambda + SQS

Fully serverless on AWS. EventBridge Scheduler triggers Step Functions, which fan out to per-source FetchLambdas. Each processing stage is a Lambda triggered by its upstream SQS queue. Every queue has a Dead-Letter Queue for failed messages. DynamoDB handles idempotent deduplication in place of Redis checkpoints.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontSize": "15px", "fontFamily": "Segoe UI, Arial, sans-serif",
    "primaryColor": "#fff7ed", "primaryBorderColor": "#ea580c", "primaryTextColor": "#431407",
    "secondaryColor": "#dbeafe", "secondaryBorderColor": "#3b82f6",
    "tertiaryColor": "#dcfce7", "tertiaryBorderColor": "#15803d",
    "clusterBkg": "#f8fafc", "clusterBorder": "#94a3b8", "lineColor": "#64748b"
  },
  "flowchart": { "nodeSpacing": 35, "rankSpacing": 50, "curve": "basis" }
}}%%
flowchart TD

  subgraph TRIGGER["① Trigger Layer"]
    direction LR
    EB["EventBridge Scheduler\n(cron)"]
    SF["Step Functions\n(orchestration + retry)"]
    EB --> SF
  end

  subgraph LAMBDAS["② AWS Lambda  (auto-scale · pay-per-invocation)"]
    direction TB
    L_FETCH["FetchLambda  ×N sources\ne.g. SEC · CourtListener · ICIJ · Procurement · News\narchives raw doc → S3"]
    L_CHUNK["ChunkLambda\n1 200 chars · 200 overlap"]
    L_ENRICH["EnrichLambda\nspaCy + GLiNER NER\nentity resolve + graph write"]
    L_EMBED["EmbedLambda\nbatch embedding\n(Bedrock Titan / OpenAI)"]
    L_INDEX["IndexLambda\nbulk write to OpenSearch"]
    L_PROFILE["ProfileLambda\nentity + exposure profiles"]
    L_FETCH ~~~ L_CHUNK ~~~ L_ENRICH ~~~ L_EMBED ~~~ L_INDEX ~~~ L_PROFILE
  end

  subgraph QUEUES["③ Amazon SQS  (per-stage + DLQ)"]
    direction TB
    Q1["SQS: raw-documents  + DLQ"]
    Q2["SQS: chunked-docs  + DLQ"]
    Q3["SQS: enriched-chunks  + DLQ"]
    Q4["SQS: embedded-chunks  + DLQ"]
    Q5["SQS: profile-trigger  + DLQ"]
    Q1 ~~~ Q2 ~~~ Q3 ~~~ Q4 ~~~ Q5
  end

  subgraph STORES["④ AWS Data Stores  (managed)"]
    direction LR
    S3[("S3\nRaw Doc Archive")]
    DDB[("DynamoDB\nCheckpoint / dedup")]
    EC[("ElastiCache Redis\nEntity Graph")]
    OSS[("OpenSearch Service\nChunk + Profile Index")]
  end

  SF --> L_FETCH
  L_FETCH  --> Q1 --> L_CHUNK
  L_CHUNK  --> Q2 --> L_ENRICH
  L_ENRICH --> Q3 --> L_EMBED
  L_EMBED  --> Q4 --> L_INDEX
  L_INDEX  --> Q5 --> L_PROFILE

  L_FETCH  -->|"raw archive"| S3
  L_CHUNK  -->|"dedup check"| DDB
  L_ENRICH -->|"entity upserts"| EC
  L_INDEX  --> OSS
  L_PROFILE --> OSS
```

---

## Architecture Comparison

| Dimension | **Current (Python Worker)** | **Kafka + Spark** | **Kafka + Flink** | **Kafka + Knative** | **AWS Lambda + SQS** |
| --- | --- | --- | --- | --- | --- |
| **Throughput** | Medium — async Python, single process | Very high — distributed, partitioned | Very high — true streaming, backpressure | High — auto-scales pods per event rate | Medium — Lambda concurrency limits apply |
| **Latency** | Batch: 20 min – 4 h per run | Micro-batch: 5 – 30 s end-to-end | Sub-second (streaming) | Seconds (pod cold-start on first event) | Seconds (Lambda cold-start on first event) |
| **Exactly-once delivery** | No — Redis dedup (at-least-once) | No — at-least-once (Kafka offsets) | Yes — Flink 2PC + Chandy-Lamport snapshots | No — CloudEvent retry (at-least-once) | No — SQS at-least-once + DLQ |
| **Fault tolerance** | Redis checkpoint; re-run to resume | Kafka offset replay + Spark WAL | Flink distributed snapshots; resume mid-stream | Knative retry + Kafka Channel durability | SQS DLQ + Step Functions retry + S3 archive |
| **Replay / reprocess** | Re-run script, Redis dedup skips seen docs | Seek Kafka offset to any point in time | Restore Flink savepoint; resume from any offset | Re-publish CloudEvents from Kafka Channel | Replay from S3 raw archive |
| **Real-time ingestion** | No — batch only | Near-real-time (micro-batch window) | Yes — continuous sub-second | Yes — event-driven on doc publish | Yes — event-driven on doc publish |
| **Horizontal scale** | No — vertical only (semaphore) | Yes — add Spark executors / partitions | Yes — add Flink task slots | Yes — Kubernetes pod autoscaler (HPA/KEDA) | Yes — Lambda concurrency scales automatically |
| **Operational complexity** | Very low — one Python script, Docker Compose | Very high — Spark cluster + Kafka + Zookeeper | High — Flink cluster + Kafka + state backend | High — Kubernetes + Knative + Kafka + Strimzi | Low — all managed services, no infra to run |
| **Infrastructure cost** | Low — single container | High — always-on Spark + Kafka cluster | High — always-on Flink + Kafka cluster | Medium — K8s base cost + scale-to-zero pods | Pay-per-use — near-zero at idle |
| **Dev / debug complexity** | Low — plain Python, easy to run locally | High — Spark + PySpark + cluster config | High — Flink API + distributed state debugging | Medium — CloudEvents contract + K8s manifests | Medium — SAM / CDK + Lambda limits (15 min, 10 GB) |
| **Vendor lock-in** | None — runs anywhere | None — open source | None — open source | Partial — Kubernetes (EKS / GKE / AKS) | High — AWS-specific (EventBridge, SQS, Lambda, Bedrock) |
| **Best fit** | Current load: small–medium batch, single-tenant, simple ops | Large-scale batch analytics on existing Spark infra | Low-latency, high-volume, exactly-once requirement | Cloud-native K8s shop wanting microservice isolation | AWS-native, minimal ops, spiky / unpredictable load |

### Decision guidance

- **Stay on current** if batch latency is acceptable and ops simplicity matters most.
- **Kafka + Flink** if you need exactly-once guarantees and sub-second latency (e.g. live sanctions feed).
- **Kafka + Spark** if you already run a Spark cluster and care about throughput over latency.
- **Kafka + Knative** if the team is already on Kubernetes and wants per-service independent scaling.
- **Lambda + SQS** if you are AWS-native, traffic is spiky, and you want zero infrastructure management.
