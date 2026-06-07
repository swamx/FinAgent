#!/usr/bin/env bash
# FinAgent — run the document ingestion pipeline
# Fetches from 5 public sources in parallel, chunks and embeds documents,
# and indexes them into the OpenSearch vector store.
#
# Sources: SEC EDGAR, CourtListener, ICIJ Offshore Leaks, USASpending, GDELT
#
# Modes:
#   (default / --small)  ~4 500 docs   20-40 min   ~80-100 MB index
#   --full               ~50 000 docs  2-4 h        ~1-2 GB index
#
# Usage:
#   bash scripts/ingest-docs.sh           # small mode
#   bash scripts/ingest-docs.sh --full    # full mode
#
# Ingestion is idempotent — already-indexed document IDs are skipped via
# Redis checkpoints. Safe to re-run to pick up new documents.
#
# When to run:
#   - Once after first-time setup (after sanctions ingest)
#   - Weekly/monthly to pick up new SEC filings and news
#
# Prerequisites: redis-stack, opensearch, and litellm must be healthy
set -euo pipefail
source "$(dirname "$0")/common.sh"

INGEST_MODE="${INGEST_MODE:-small}"

for arg in "$@"; do
    case "$arg" in
        --full)  INGEST_MODE=full  ;;
        --small) INGEST_MODE=small ;;
    esac
done

export INGEST_MODE

step "Checking required services"

for svc in redis-stack opensearch litellm; do
    if ! docker compose ps "$svc" 2>/dev/null | grep -q "(healthy)"; then
        warn "$svc is not healthy. Starting backend stack..."
        bash "$(dirname "$0")/start-api.sh"
        break
    fi
done

step "Running document ingestor (mode: ${INGEST_MODE})"
if [ "$INGEST_MODE" = "full" ]; then
    warn "FULL mode — fetching ~50 000 docs. Estimated time: 2-4 hours."
else
    warn "SMALL mode — fetching ~4 500 docs. Estimated time: 20-40 minutes."
fi
docker compose run --rm -e INGEST_MODE="${INGEST_MODE}" doc-ingestor

step "Verifying index"
info "Document count in fintech-docs:"
curl -sf "http://localhost:9200/fintech-docs/_count" | python3 -c \
    "import sys, json; d=json.load(sys.stdin); print(f'  Total chunks: {d[\"count\"]}')" \
    2>/dev/null || info "  (curl not available locally — check http://localhost:5601)"

info "Document ingestion complete."
