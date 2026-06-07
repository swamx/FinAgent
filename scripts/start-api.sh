#!/usr/bin/env bash
# FinAgent — start backend API + all infrastructure (no chat UI)
# Use this when you want the compliance API available for programmatic access
# but don't need the Open WebUI frontend.
#
# Services started: redis-stack, opensearch, postgres, ollama, litellm,
#                   opensearch-dashboards, api
set -euo pipefail
source "$(dirname "$0")/common.sh"

step "Starting backend API stack"
docker compose up -d \
    redis-stack \
    opensearch \
    postgres \
    ollama \
    litellm \
    opensearch-dashboards \
    api

step "Waiting for core services"
wait_healthy redis-stack 20 5
wait_healthy opensearch  40 10
wait_healthy litellm     30 10

info "API stack is up."
print_urls \
    "Compliance API →  http://localhost:8000/docs" \
    "LiteLLM proxy  →  http://localhost:4000" \
    "FalkorDB UI    →  http://localhost:3000" \
    "OpenSearch     →  http://localhost:5601"
