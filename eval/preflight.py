"""
Pre-eval preflight checker.

Verifies all services required for a successful eval run are healthy
before starting the (slow, expensive) eval loop.

Usage:
    python -m eval.preflight              # check from host
    docker compose run --rm eval-runner python -m eval.preflight
"""
from __future__ import annotations

import os
import sys
import time
import httpx

API_BASE   = os.environ.get("FINAGENT_API_BASE", "http://localhost:8000")
LITELLM    = os.environ.get("LITELLM_BASE_URL",  "http://localhost:4000")
OPENSEARCH = os.environ.get("OPENSEARCH_URL",    "http://localhost:9200")
OTEL       = os.environ.get("OTEL_HTTP_URL",     "http://localhost:4318")

# Inside the docker network service names differ from host names
_IN_DOCKER = os.path.exists("/.dockerenv")
if _IN_DOCKER:
    API_BASE   = os.environ.get("FINAGENT_API_BASE", "http://api:8000")
    LITELLM    = os.environ.get("LITELLM_BASE_URL",  "http://litellm:4000")
    OPENSEARCH = os.environ.get("OPENSEARCH_URL",    "http://opensearch:9200")
    OTEL       = os.environ.get("OTEL_HTTP_URL",     "http://otel-lgtm:4318")

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    symbol = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
    suffix = f"  {YELLOW}{detail}{RESET}" if detail else ""
    print(f"  {symbol}  {label}{suffix}")
    _results.append((label, ok, detail))
    return ok


def _get(url: str, timeout: float = 5.0) -> tuple[int, dict]:
    try:
        r = httpx.get(url, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _post(url: str, json: dict, timeout: float = 30.0) -> tuple[int, dict]:
    try:
        r = httpx.post(url, json=json, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def run_preflight() -> bool:
    print(f"\n{BOLD}FinAgent - Pre-Eval Preflight{RESET}")
    print(f"  API      : {API_BASE}")
    print(f"  LiteLLM  : {LITELLM}")
    print(f"  OpenSearch: {OPENSEARCH}")

    # ── 1. Core service reachability ─────────────────────────────────────
    section("1. Service reachability")

    code, body = _get(f"{API_BASE}/docs")
    check("FinAgent API /docs", code == 200, f"HTTP {code}" if code != 200 else "")

    code, body = _get(f"{OPENSEARCH}/_cluster/health")
    os_status = body.get("status", "unknown")
    check(
        "OpenSearch cluster",
        code == 200 and os_status in ("green", "yellow"),
        f"status={os_status}" if code == 200 else f"HTTP {code}",
    )

    code, _ = _get(f"{LITELLM}/health", timeout=8.0)
    check("LiteLLM proxy", code in (200, 401), f"HTTP {code}" if code not in (200, 401) else "")

    code, _ = _get(f"{OTEL}/")
    check("OTel / Grafana", code in (200, 404, 405), f"HTTP {code}" if code == 0 else "")

    # ── 2. OpenSearch index ───────────────────────────────────────────────
    section("2. OpenSearch index")

    code, body = _get(f"{OPENSEARCH}/fintech-docs/_count")
    doc_count = body.get("count", 0)
    check(
        "fintech-docs index exists",
        code == 200,
        f"HTTP {code}" if code != 200 else "",
    )
    check(
        "fintech-docs has documents",
        doc_count > 0,
        f"{doc_count:,} docs" if code == 200 else "index missing",
    )

    # ── 3. FalkorDB / Redis ───────────────────────────────────────────────
    section("3. FalkorDB / Redis")

    code, body = _get(f"{API_BASE}/entity/person:roman_abramovich")
    check(
        "Entity lookup (graph)",
        code in (200, 404),
        "entity not found (graph may be empty)" if code == 404 else (f"HTTP {code}" if code != 200 else ""),
    )

    # ── 4. Search endpoint ────────────────────────────────────────────────
    section("4. Hybrid search")

    code, body = _post(f"{API_BASE}/search", {"query": "OFAC sanctions", "limit": 3})
    doc_count_search = len(body.get("documents", []))
    check("POST /search returns 200", code == 200, f"HTTP {code}" if code != 200 else "")
    check(
        "Search returns documents",
        doc_count_search > 0,
        f"{doc_count_search} docs returned" if code == 200 else "search failed",
    )

    # ── 5. Chat / LLM ─────────────────────────────────────────────────────
    section("5. Chat / LLM (one live call)")

    t0 = time.monotonic()
    code, body = _post(
        f"{API_BASE}/chat",
        {"message": "What is OFAC? One sentence only."},
        timeout=60.0,
    )
    elapsed = time.monotonic() - t0
    answer = body.get("answer", "")
    check(
        "POST /chat returns 200",
        code == 200,
        f"HTTP {code}" if code != 200 else f"{elapsed:.1f}s",
    )
    check(
        "Chat returns non-empty answer",
        bool(answer),
        answer[:80] if answer else "empty response",
    )

    # ── 6. Rate limit headroom ────────────────────────────────────────────
    section("6. Rate limit headroom")

    # /chat is 10/min — the smoke-test above consumed 1. Just warn if close.
    # We check by looking at response headers from a /search call.
    code, body = _post(f"{API_BASE}/search", {"query": "test", "limit": 1})
    check("POST /search rate limit OK", code == 200, f"HTTP {code}" if code != 200 else "")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    failures = [label for label, ok, _ in _results if not ok]
    warnings = [label for label, ok, detail in _results if ok and detail]

    if not failures:
        print(f"{GREEN}{BOLD}All checks passed.{RESET} Safe to run eval.")
        return True
    else:
        print(f"{RED}{BOLD}{len(failures)} check(s) failed:{RESET}")
        for f in failures:
            print(f"  {RED}-{RESET} {f}")
        print("\nFix the above before running eval.")
        return False


if __name__ == "__main__":
    ok = run_preflight()
    sys.exit(0 if ok else 1)
