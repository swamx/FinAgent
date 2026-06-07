"""Circuit breaker singletons — one per remote dependency.

Usage as async context manager:
    from observability.circuit_breakers import llm_breaker

    async with llm_breaker:
        result = await client.chat.completions.create(...)

Usage via call_async (preferred for inline calls):
    result = await llm_breaker.call_async(some_async_fn, *args)

Usage as decorator on async functions / top-level fetchers:
    @sec_breaker
    async def fetch_sec_filings(...):
        ...
"""
from __future__ import annotations

import logging
from datetime import timedelta

from aiobreaker import CircuitBreaker, CircuitBreakerListener

from observability.metrics import circuit_breaker_events

_log = logging.getLogger(__name__)


class _OTelListener(CircuitBreakerListener):
    """Records state changes and failures to metrics + logs."""

    def state_change(self, cb: CircuitBreaker, old_state, new_state) -> None:
        svc = getattr(cb, "name", "unknown") or "unknown"
        # State class names: ClosedState / OpenState / HalfOpenState
        new_str = type(new_state).__name__.replace("State", "").lower()
        old_str = type(old_state).__name__.replace("State", "").lower()
        _log.warning(
            "circuit_breaker state_change  service=%s  %s → %s", svc, old_str, new_str
        )
        circuit_breaker_events.add(1, {"service": svc, "new_state": new_str})

    def call_failed(self, cb: CircuitBreaker, exc: Exception) -> None:
        svc = getattr(cb, "name", "unknown") or "unknown"
        _log.warning("circuit_breaker failure  service=%s  error=%s", svc, exc)


_listener = _OTelListener()


def _cb(name: str, fail_max: int = 5, timeout_s: int = 60) -> CircuitBreaker:
    return CircuitBreaker(
        fail_max=fail_max,
        timeout_duration=timedelta(seconds=timeout_s),
        name=name,
        listeners=[_listener],
    )


# ── One breaker per remote service ───────────────────────────────────────
llm_breaker           = _cb("llm",            fail_max=3,  timeout_s=60)
opensearch_breaker    = _cb("opensearch",     fail_max=5,  timeout_s=30)
graph_breaker         = _cb("graph",          fail_max=5,  timeout_s=30)
sec_breaker           = _cb("sec",            fail_max=5,  timeout_s=120)
courtlistener_breaker = _cb("courtlistener",  fail_max=5,  timeout_s=300)
icij_breaker          = _cb("icij",           fail_max=2,  timeout_s=600)
procurement_breaker   = _cb("procurement",    fail_max=5,  timeout_s=300)
news_breaker          = _cb("news",           fail_max=5,  timeout_s=300)
