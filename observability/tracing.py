"""Tracing helpers: get_tracer() and @traced decorator."""
from __future__ import annotations

import functools
from typing import Callable

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

_TRACER_NAME = "finagent"


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def traced(span_name: str, **attrs):
    """Wrap a sync or async callable in an OTel span.

    Usage:
        @traced("graph.query", db_system="falkordb")
        def _query(self, cypher: str) -> list: ...

        @traced("embed.create")
        async def embed(text: str) -> list[float]: ...
    """
    def decorator(fn: Callable) -> Callable:
        import asyncio

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def _async(*args, **kwargs):
                with get_tracer().start_as_current_span(span_name) as span:
                    for k, v in attrs.items():
                        span.set_attribute(k, v)
                    try:
                        return await fn(*args, **kwargs)
                    except Exception as exc:
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        span.record_exception(exc)
                        raise
            return _async
        else:
            @functools.wraps(fn)
            def _sync(*args, **kwargs):
                with get_tracer().start_as_current_span(span_name) as span:
                    for k, v in attrs.items():
                        span.set_attribute(k, v)
                    try:
                        return fn(*args, **kwargs)
                    except Exception as exc:
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        span.record_exception(exc)
                        raise
            return _sync

    return decorator
