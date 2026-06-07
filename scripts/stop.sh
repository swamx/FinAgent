#!/usr/bin/env bash
# FinAgent — stop services
#
# Usage:
#   bash scripts/stop.sh              # stop all containers, keep volumes (data safe)
#   bash scripts/stop.sh --reset      # stop AND delete all volumes (full wipe)
#   bash scripts/stop.sh --chat       # stop chat-related services only
#   bash scripts/stop.sh --api        # stop API + backend only
set -euo pipefail
source "$(dirname "$0")/common.sh"

MODE="all"
for arg in "$@"; do
    case "$arg" in
        --reset) MODE="reset" ;;
        --chat)  MODE="chat"  ;;
        --api)   MODE="api"   ;;
    esac
done

case "$MODE" in
    reset)
        warn "This will DELETE all data volumes (graph, vector index, models, etc.)."
        warn "Type 'yes' to confirm, or Ctrl-C to abort:"
        read -r confirm
        [[ "$confirm" == "yes" ]] || { info "Aborted."; exit 0; }
        step "Full reset — stopping and removing all volumes"
        docker compose down -v
        info "All containers stopped and volumes deleted."
        ;;
    chat)
        step "Stopping chat services"
        docker compose stop open-webui litellm ollama
        info "Chat services stopped. Infrastructure (redis, opensearch) left running."
        ;;
    api)
        step "Stopping API and backend"
        docker compose stop api litellm opensearch opensearch-dashboards
        info "API and backend stopped. FalkorDB and Ollama left running."
        ;;
    all)
        step "Stopping all services (data volumes preserved)"
        docker compose down
        info "All services stopped. Run 'bash scripts/start.sh' to restart."
        ;;
esac
