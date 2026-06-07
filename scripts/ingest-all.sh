#!/usr/bin/env bash
# FinAgent — run both ingestion pipelines in sequence
# Sanctions graph first (FalkorDB), then document corpus (OpenSearch).
# The doc ingestor uses entity data from the graph for enrichment, so
# order matters — always run sanctions before docs.
#
# Usage:
#   bash scripts/ingest-all.sh               # sanctions + docs (small)
#   bash scripts/ingest-all.sh --full        # sanctions + docs (full ~50K)
#   bash scripts/ingest-all.sh --docs-only   # skip sanctions, docs only
#   bash scripts/ingest-all.sh --docs-only --full
#   bash scripts/ingest-all.sh --sanctions-only
set -euo pipefail
source "$(dirname "$0")/common.sh"

RUN_SANCTIONS=true
RUN_DOCS=true
INGEST_MODE="${INGEST_MODE:-small}"

for arg in "$@"; do
    case "$arg" in
        --docs-only)       RUN_SANCTIONS=false ;;
        --sanctions-only)  RUN_DOCS=false ;;
        --full)            INGEST_MODE=full ;;
        --small)           INGEST_MODE=small ;;
    esac
done

export INGEST_MODE

START=$(date +%s)

if [ "$RUN_SANCTIONS" = true ]; then
    bash "$(dirname "$0")/ingest-sanctions.sh"
fi

if [ "$RUN_DOCS" = true ]; then
    bash "$(dirname "$0")/ingest-docs.sh" "--${INGEST_MODE}"
fi

END=$(date +%s)
ELAPSED=$(( (END - START) / 60 ))
info "All ingestion complete in ~${ELAPSED} minutes."
