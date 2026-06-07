#!/usr/bin/env bash
# FinAgent — start infrastructure layer only
# Starts the data stores and Ollama runtime with no application services.
# Useful for running ingestion pipelines, debugging data, or developing
# application services locally outside Docker.
#
# Services started: redis-stack, opensearch, postgres, ollama
set -euo pipefail
source "$(dirname "$0")/common.sh"

step "Starting infrastructure layer"
docker compose up -d redis-stack opensearch postgres ollama

wait_healthy redis-stack 20 5
wait_healthy postgres    20 5
wait_healthy ollama      20 5
wait_healthy opensearch  40 10

info "Infrastructure is up."
print_urls \
    "FalkorDB (Redis protocol)  →  localhost:6379" \
    "FalkorDB Browser UI        →  http://localhost:3000" \
    "OpenSearch                 →  http://localhost:9200" \
    "OpenSearch Dashboards      →  http://localhost:5601 (not started)" \
    "Ollama                     →  http://localhost:11434" \
    "Postgres                   →  localhost:5432"
