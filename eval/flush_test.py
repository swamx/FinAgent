"""One-shot: inject last eval scores and flush to OTel."""
from observability.setup import setup_telemetry
setup_telemetry("finagent-eval")

from observability.metrics import set_eval_score
set_eval_score("faithfulness", 0.016)
set_eval_score("answer_relevancy", 0.085)
set_eval_score("context_precision", 0.0)
set_eval_score("context_recall", 0.031)
set_eval_score("hallucination_rate", 0.688)
print("Scores set, flushing to OTel...")

from opentelemetry import metrics as otel_metrics, trace
mp = otel_metrics.get_meter_provider()
if hasattr(mp, "force_flush"):
    ok = mp.force_flush(timeout_millis=10_000)
    print(f"metric flush: {'ok' if ok else 'timeout'}")
tp = trace.get_tracer_provider()
if hasattr(tp, "force_flush"):
    ok = tp.force_flush(timeout_millis=5_000)
    print(f"trace flush: {'ok' if ok else 'timeout'}")
print("Done.")
