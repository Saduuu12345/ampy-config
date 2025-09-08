# ampy_config/obs/metrics.py
from __future__ import annotations
import os, time, threading
from typing import Optional, Dict

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    _PROM_OK = True
except Exception:
    _PROM_OK = False

_started = False
_lock = threading.Lock()

# Prom metrics (no-op if prometheus_client missing)
_CONFIG_LABELS = ("service",)

config_load_success_total = None
config_load_failure_total = None  # labels: service, reason
config_reload_total = None        # labels: service
config_apply_total = None         # labels: status
bus_messages_total = None         # labels: direction, subject
secret_resolve_latency_ms = None  # labels: backend
redactions_total = None           # labels: field

def _mk_histogram(name, desc, buckets):
    # Prometheus buckets are in seconds; we accept ms and convert.
    return Histogram(name, desc, buckets=[b/1000.0 for b in buckets])

def init_metrics(exporter: str = "prom", port: int = 9464, addr: str = "0.0.0.0", service: str = "ampy-config") -> None:
    """
    exporter: "prom" | "none"
    """
    global _started, config_load_success_total, config_load_failure_total
    global config_reload_total, config_apply_total, bus_messages_total
    global secret_resolve_latency_ms, redactions_total

    with _lock:
        if _started:
            return

        if exporter == "none":
            _started = True
            return

        if exporter == "prom":
            if not _PROM_OK:
                print("[obs] prometheus-client not installed; metrics disabled", flush=True)
                _started = True
                return

            start_http_server(port, addr=addr)
            # Counters / histograms
            config_load_success_total = Counter("config_load_success_total", "Successful effective config loads", _CONFIG_LABELS)
            config_load_failure_total = Counter("config_load_failure_total", "Failed config loads", _CONFIG_LABELS + ("reason",))
            config_reload_total = Counter("config_reload_total", "Runtime reload attempts", _CONFIG_LABELS)
            config_apply_total = Counter("config_apply_total", "Config apply outcomes", ("status",))
            bus_messages_total = Counter("bus_messages_total", "Bus messages in/out", ("direction","subject"))
            secret_resolve_latency_ms = _mk_histogram("secret_resolve_latency_ms", "Secret resolve latency (ms)", buckets=[5,10,20,50,100,200,500,1000,2000])
            redactions_total = Counter("redactions_total", "Values redacted", ("field",))
            print(f"[obs] Prometheus metrics on http://{addr}:{port}/metrics (service={service})", flush=True)
            _started = True
            return

        # future: add "otlp" exporter here
        print(f"[obs] unknown exporter={exporter}; metrics disabled", flush=True)
        _started = True

def observe_secret_latency_ms(backend: str, ms: float) -> None:
    if secret_resolve_latency_ms is not None:
        secret_resolve_latency_ms.labels(backend=backend).observe(ms/1.0)  # we kept ms units in buckets

def inc_bus(direction: str, subject: str) -> None:
    if bus_messages_total is not None:
        bus_messages_total.labels(direction=direction, subject=subject).inc()

def inc_apply(status: str) -> None:
    if config_apply_total is not None:
        config_apply_total.labels(status=status).inc()

def inc_load_success(service: str) -> None:
    if config_load_success_total is not None:
        config_load_success_total.labels(service=service).inc()

def inc_load_failure(service: str, reason: str) -> None:
    if config_load_failure_total is not None:
        config_load_failure_total.labels(service=service, reason=reason).inc()

def inc_reload(service: str) -> None:
    if config_reload_total is not None:
        config_reload_total.labels(service=service).inc()

def inc_redaction(field: str) -> None:
    if redactions_total is not None:
        redactions_total.labels(field=field).inc()
