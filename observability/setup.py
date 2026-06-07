"""OTel SDK bootstrap. Call setup_telemetry() once at process startup."""
from __future__ import annotations

import logging
import os


def setup_telemetry(service_name: str | None = None) -> None:
    """Initialise OTel traces, metrics, and log bridge for the current process.

    Safe to call multiple times — global providers are overwritten each call
    so prefer calling only once at startup.  Reads otel_endpoint and
    otel_service_name from Settings; both have Docker-network defaults.
    """
    from opentelemetry import metrics as otel_metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    from core.config import settings

    endpoint = settings.otel_endpoint
    svc = service_name or settings.otel_service_name

    resource = Resource.create({
        "service.name": svc,
        "service.version": "1.0.0",
        "deployment.environment": os.getenv("ENVIRONMENT", "local"),
    })

    # ── Traces ────────────────────────────────────────────────────────────
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(tp)

    # ── Metrics ───────────────────────────────────────────────────────────
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint),
        export_interval_millis=15_000,
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    otel_metrics.set_meter_provider(mp)

    # ── Log bridge (Python logging → OTLP → Loki) ────────────────────────
    _setup_log_bridge(resource, endpoint)

    # ── Library auto-instrumentation ──────────────────────────────────────
    _auto_instrument()

    logging.getLogger(__name__).info(
        "OTel telemetry initialised  service=%s  endpoint=%s", svc, endpoint
    )


def _setup_log_bridge(resource, endpoint: str) -> None:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        lp = LoggerProvider(resource=resource)
        lp.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
        )
        set_logger_provider(lp)
        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "OTel log bridge unavailable (non-fatal): %s", exc
        )


def _auto_instrument() -> None:
    """Best-effort auto-instrumentation — silently skips unavailable packages."""
    _try("FastAPI",  _inst_fastapi)
    _try("Redis",    _inst_redis)
    _try("aiohttp",  _inst_aiohttp)
    _try("requests", _inst_requests)


def _try(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        logging.getLogger(__name__).debug("Auto-instrument %s skipped: %s", name, exc)


def _inst_fastapi():
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor().instrument()


def _inst_redis():
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RedisInstrumentor().instrument()


def _inst_aiohttp():
    from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
    AioHttpClientInstrumentor().instrument()


def _inst_requests():
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    RequestsInstrumentor().instrument()
