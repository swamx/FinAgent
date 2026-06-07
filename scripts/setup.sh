#!/usr/bin/env bash
# FinAgent — first-time setup
# Run once on a new machine or after a full `docker compose down -v`.
# Re-running is safe: each step is idempotent.
#
# Usage:
#   bash scripts/setup.sh               # full setup including ingestion
#   bash scripts/setup.sh --skip-ingest # stop after starting services
set -euo pipefail
source "$(dirname "$0")/common.sh"

SKIP_INGEST=false
for arg in "$@"; do [[ "$arg" == "--skip-ingest" ]] && SKIP_INGEST=true; done

# ── Step 0: Prerequisites ────────────────────────────────────────────────────
step "Checking prerequisites"
check_deps
info "Docker and docker compose found."

# ── Step 1: .env ─────────────────────────────────────────────────────────────
step "Environment file"
if [ ! -f "$REPO_ROOT/.env" ]; then
    info "Creating .env from .env.example..."
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    warn "ACTION REQUIRED: edit .env before continuing."
    warn "  Minimum: set SEC_USER_AGENT and WEBUI_ADMIN_PASSWORD"
    warn "  Optional: ANTHROPIC_API_KEY, COURTLISTENER_TOKEN"
    warn ""
    warn "Press Enter when done, or Ctrl-C to abort."
    read -r
else
    info ".env already exists — skipping."
fi

# ── Step 2: Build images ─────────────────────────────────────────────────────
step "Building Docker images"
info "Building api and worker images (first build ~5-10 min)..."
docker compose build
info "Images built."

# ── Step 3: Core infrastructure ──────────────────────────────────────────────
step "Starting infrastructure"
info "Starting: redis-stack, opensearch, postgres, ollama"
docker compose up -d redis-stack opensearch postgres ollama

wait_healthy redis-stack 20 5
wait_healthy postgres    20 5
wait_healthy ollama      20 5
wait_healthy opensearch  40 10

# ── Step 4: Pull LLM models ──────────────────────────────────────────────────
step "Pulling LLM models (~20 GB — this will take a while)"
info "Models: qwen3:30b-a3b (~19 GB), gemma3:12b (~8 GB), nomic-embed-text (~270 MB)"
info "Models are cached in the ollama_data volume and only pulled once."
docker compose run --rm ollama-init
info "All models pulled."

# ── Step 5: LiteLLM ──────────────────────────────────────────────────────────
step "Starting LiteLLM proxy"
docker compose up -d litellm
wait_healthy litellm 30 10

# ── Step 6: Remaining services ───────────────────────────────────────────────
step "Starting API, dashboards, and chat UI"
docker compose up -d opensearch-dashboards api open-webui
info "Services started."

# ── Step 7: Ingestion (optional) ─────────────────────────────────────────────
if [ "$SKIP_INGEST" = false ]; then
    step "Ingesting sanctions graph (OpenSanctions → FalkorDB)"
    warn "This downloads ~2 GB and may take 30-60 minutes."
    docker compose run --rm sanctions-ingestor
    info "Sanctions ingestion complete."

    step "Ingesting document corpus (5 sources → OpenSearch)"
    warn "This fetches from SEC, CourtListener, ICIJ, USASpending, GDELT (~20-40 min)."
    docker compose run --rm doc-ingestor
    info "Document ingestion complete."
else
    warn "Skipping ingestion (--skip-ingest). Run scripts/ingest-all.sh when ready."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
print_urls \
    "Chat UI       →  http://localhost:3001" \
    "Compliance API →  http://localhost:8000/docs" \
    "LiteLLM proxy  →  http://localhost:4000" \
    "FalkorDB UI    →  http://localhost:3000" \
    "OpenSearch     →  http://localhost:5601"
