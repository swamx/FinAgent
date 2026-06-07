#!/usr/bin/env bash
# FinAgent — pull Ollama models
# Downloads all required LLM models into the ollama_data volume.
# Run once after first install, or after clearing the ollama_data volume.
# Models: qwen3:30b-a3b (~19 GB), gemma3:12b (~8 GB), nomic-embed-text (~270 MB)
#
# Usage:
#   bash scripts/pull-models.sh              # pull all three models
#   bash scripts/pull-models.sh --embed-only # pull nomic-embed-text only
set -euo pipefail
source "$(dirname "$0")/common.sh"

EMBED_ONLY=false
for arg in "$@"; do [[ "$arg" == "--embed-only" ]] && EMBED_ONLY=true; done

# Ensure Ollama is running
if ! docker compose ps ollama 2>/dev/null | grep -q "running\|Up"; then
    info "Starting Ollama..."
    docker compose up -d ollama
    wait_healthy ollama 20 5
fi

if [ "$EMBED_ONLY" = true ]; then
    step "Pulling embedding model only"
    docker exec finagent-ollama ollama pull nomic-embed-text
    info "nomic-embed-text pulled."
else
    step "Pulling all models (~27 GB total)"
    warn "This may take 30-60 minutes on a typical connection."
    docker compose run --rm ollama-init
    info "All models pulled."
fi

step "Installed models"
docker exec finagent-ollama ollama list
