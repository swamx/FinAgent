#!/usr/bin/env bash
# FinAgent — start chat UI only
# Starts the minimal set of services needed for LLM chat via Open WebUI.
# Does NOT start OpenSearch or the compliance API — no graph/vector tools available.
# Use this for lightweight LLM interaction without the full compliance stack.
#
# Services started: postgres, ollama, litellm, open-webui
set -euo pipefail
source "$(dirname "$0")/common.sh"

step "Starting chat stack (WebUI + LiteLLM + Ollama)"
docker compose up -d postgres ollama litellm open-webui

wait_healthy ollama  20 5
wait_healthy litellm 30 10

info "Chat stack is up."
print_urls \
    "Chat UI       →  http://localhost:3001" \
    "LiteLLM proxy →  http://localhost:4000"
warn "Compliance tools (entity search, graph queries) are not available in this mode."
warn "Run 'bash scripts/start.sh' for the full stack."
