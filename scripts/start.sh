#!/usr/bin/env bash
# FinAgent — start the full stack
# Use this for regular day-to-day startup after first-time setup is done.
# One-shot containers (ollama-init, sanctions-ingestor, doc-ingestor) are
# excluded — they only run when explicitly invoked.
set -euo pipefail
source "$(dirname "$0")/common.sh"

step "Starting full FinAgent stack"

docker compose up -d \
    redis-stack \
    opensearch \
    postgres \
    ollama \
    litellm \
    opensearch-dashboards \
    api \
    open-webui

step "Waiting for core services"
wait_healthy redis-stack 20 5
wait_healthy opensearch  40 10
wait_healthy litellm     30 10

info "All services up."
print_urls \
    "Chat UI        →  http://localhost:3001" \
    "Compliance API →  http://localhost:8000/docs" \
    "LiteLLM proxy  →  http://localhost:4000" \
    "FalkorDB UI    →  http://localhost:3000" \
    "OpenSearch     →  http://localhost:5601"
