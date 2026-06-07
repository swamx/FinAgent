#!/usr/bin/env bash
# FinAgent — run the sanctions ingestion pipeline
# Downloads the OpenSanctions dataset (~2 GB JSONL) and loads it into
# the FalkorDB graph as Entity nodes with typed relationship edges.
#
# The dataset is cached in the sanctions_data volume — subsequent runs
# skip the download and re-ingest directly from the cached file.
#
# When to run:
#   - Once after first-time setup
#   - When you want a fresh copy of the OpenSanctions dataset
#
# Prerequisites: redis-stack must be healthy (run start-infra.sh first)
set -euo pipefail
source "$(dirname "$0")/common.sh"

step "Checking FalkorDB is running"
if ! docker compose ps redis-stack 2>/dev/null | grep -q "(healthy)"; then
    info "FalkorDB not running — starting infrastructure..."
    bash "$(dirname "$0")/start-infra.sh"
fi

step "Running sanctions ingestor"
warn "Download: ~2 GB   |   Ingestion: 30-60 min depending on hardware"
docker compose run --rm sanctions-ingestor

step "Verifying graph"
info "Node count:"
docker exec finagent-redis redis-cli GRAPH.QUERY entities "MATCH (n) RETURN count(n) AS nodes"
info "Edge count:"
docker exec finagent-redis redis-cli GRAPH.QUERY entities "MATCH ()-[r]->() RETURN count(r) AS edges"

info "Sanctions ingestion complete."
