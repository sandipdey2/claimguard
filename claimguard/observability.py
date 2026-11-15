"""OpenTelemetry tracing with env-gated exporters (no exporter = spans stay in the run's in-memory list for the UI).

* APPLICATIONINSIGHTS_CONNECTION_STRING -> Azure Monitor exporter (Application Insights; Foundry tracing reads the same
  resource). Needs the optional ``azure-monitor-opentelemetry-exporter`` package (requirements-azure.txt).
* PHOENIX_COLLECTOR_ENDPOINT or OTEL_EXPORTER_OTLP_ENDPOINT -> OTLP/HTTP (Arize Phoenix or any OTel collector).
* CG_OTEL_CONSOLE=1 -> console exporter (debugging).
"""
from __future__ import annotations

import threading

from .config import secret

_lock = threading.Lock()
_tracer = None
_status: dict = {"configured": False, "exporters": []}


def _init():
    global _tracer
    with _lock:
        if _tracer is not None:
            return _tracer
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
        provider = TracerProvider(resource=Resource.create({"service.name": "claimguard", "service.version": "0.1.0"}))
        conn = secret("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if conn:
            try:
                from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter  # type: ignore[import-not-found]
                provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=conn)))
                _status["exporters"].append("azure_monitor")
            except Exception as exc:
                _status["exporters"].append(f"azure_monitor_unavailable:{type(exc).__name__}")
        otlp = secret("PHOENIX_COLLECTOR_ENDPOINT") or secret("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                url = otlp.rstrip("/")
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url if url.endswith("/v1/traces") else url + "/v1/traces")))
                _status["exporters"].append("otlp_http")
            except Exception as exc:
                _status["exporters"].append(f"otlp_unavailable:{type(exc).__name__}")
        if secret("CG_OTEL_CONSOLE") == "1":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            _status["exporters"].append("console")
        _status["configured"] = bool(_status["exporters"])
        _tracer = provider.get_tracer("claimguard")
        return _tracer


def status() -> dict:
    _init()
    return dict(_status)


def emit_span(name: str, start: float, end: float, attrs: dict) -> None:
    """Emit one finished span with explicit start/end (seconds since epoch)."""
    tr = _init()
    if not _status["configured"]:
        return
    span = tr.start_span(name, start_time=int(start * 1e9), attributes={k: v for k, v in attrs.items() if isinstance(v, (str, int, float, bool))})
    span.end(end_time=int(end * 1e9))
