#!/usr/bin/env bash
# Shared utilities — sourced by all other scripts. Not run directly.

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${GREEN}[finagent]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}    $*"; }
error() { echo -e "${RED}[error]${NC}   $*"; exit 1; }
step()  { echo -e "\n${CYAN}══ $* ${NC}"; }

# Resolve repo root relative to this script
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

check_deps() {
    command -v docker >/dev/null 2>&1   || error "Docker not found. Install Docker Desktop."
    docker compose version >/dev/null 2>&1 || error "'docker compose' plugin not found."
}

# Wait until a service shows (healthy) in docker compose ps output.
# Usage: wait_healthy <service> [max_retries=30] [delay_seconds=10]
wait_healthy() {
    local svc=$1 retries=${2:-30} delay=${3:-10} i=0
    info "Waiting for $svc to become healthy..."
    while [ $i -lt "$retries" ]; do
        if docker compose -f "$REPO_ROOT/docker-compose.yml" ps "$svc" 2>/dev/null \
                | grep -q "(healthy)"; then
            info "$svc is healthy."
            return 0
        fi
        i=$((i + 1))
        printf "  [%d/%d] not ready yet, waiting %ds...\n" "$i" "$retries" "$delay"
        sleep "$delay"
    done
    error "$svc did not become healthy after $((retries * delay))s."
}

# Print the service URL summary banner
print_urls() {
    echo ""
    echo -e "${GREEN}┌──────────────────────────────────────────────────────┐${NC}"
    echo -e "${GREEN}│  Service URLs                                        │${NC}"
    echo -e "${GREEN}├──────────────────────────────────────────────────────┤${NC}"
    for line in "$@"; do
        printf "${GREEN}│${NC}  %-50s ${GREEN}│${NC}\n" "$line"
    done
    echo -e "${GREEN}└──────────────────────────────────────────────────────┘${NC}"
    echo ""
}

cd "$REPO_ROOT"
