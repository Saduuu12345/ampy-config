from __future__ import annotations
import os, json, uuid, asyncio, re, traceback
from typing import Awaitable, Callable, Any, Dict, List
from ampybus import nats_bus
from ampybus.headers import Headers
from ..obs.metrics import inc_bus


def _producer_id() -> str:
    return os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config@cli")

def _schema(kind: str) -> str:
    return f"ampy.control.v1.{kind}"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9_\-]")

class AmpyBus:
    """
    JSON wrapper around ampy-bus NATS bus for control-plane messages.
    - Uses ONE stream with wildcard subjects (easier ops).
    - Stable durable name (no consumer leaks).
    - Dev-only auto-provision behind a flag (off by default).
    """
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
        self._bus = nats_bus.NATSBus(self.url)
        self._tasks: List[asyncio.Task] = []

        # Dev/ops knobs
        self.auto_provision = os.environ.get("AMPY_CONFIG_AUTO_PROVISION", "false").lower() == "true"
        self.stream_name = os.environ.get("AMPY_CONFIG_STREAM", "ampy-control")
        self.subject_pattern = os.environ.get("AMPY_CONFIG_SUBJECT_PATTERN", "ampy.*.control.v1.*")
        # Use prefix; real durable names are per-subject
        self.durable_prefix = os.environ.get("AMPY_CONFIG_DURABLE", None) or \
                              os.environ.get("AMPY_CONFIG_DURABLE_PREFIX", "ampy-config")


    async def connect(self):
        try:
            await asyncio.wait_for(self._bus.connect(), timeout=10.0)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Timeout connecting to NATS at {self.url}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to NATS at {self.url}: {e}")
        if self.auto_provision:
            await self._ensure_stream()

    def _durable_for(self, subject: str) -> str:
        base = subject.replace(".", "-").replace("*", "star")
        base = _NON_ALNUM.sub("-", base)
        return f"{self.durable_prefix}-{base}"

    async def _ensure_stream(self) -> None:
        """
        Dev convenience only. In prod, provision streams/consumers via IaC.
        Creates one stream with a wildcard subject if it does not exist.
        """
        try:
            js = self._bus.js  # public handle in ampy-bus (avoid _private attrs)
            # Try to find an existing stream by subject pattern
            exists = await js.find_stream_by_subject(self.subject_pattern)
            if exists:
                return
        except Exception:
            pass

        try:
            # Fallback to nats-py API if needed
            from nats.js.api import StreamConfig, StorageType, RetentionPolicy
            sc = StreamConfig(
                name=self.stream_name,
                subjects=[self.subject_pattern],
                retention=RetentionPolicy.LIMITS,
                max_age=1 * 24 * 60 * 60 * 1_000_000_000,  # 1 day retention (ns)
                max_msgs=10000,
                max_bytes=100 * 1024 * 1024,
                storage=StorageType.FILE,
            )
            await self._bus.create_stream(sc)
            print(f"[INFO] created stream {self.stream_name} for {self.subject_pattern}")
        except Exception as e:
            print(f"[WARN] could not auto-provision stream: {e} (continuing)")

    async def publish_json(self, subject: str, payload: dict, kind: str = "Generic") -> None:
        message_id = str(uuid.uuid4())
        headers = Headers(
            message_id=message_id,
            schema_fqdn=_schema(kind),
            producer=_producer_id(),
            source="ampy-config",
            partition_key="control",
            content_type="application/json",
            run_id=os.environ.get("AMPY_CONFIG_RUN_ID", f"run-{uuid.uuid4().hex[:8]}")
        )
        data = json.dumps(payload).encode("utf-8")
        await self._bus.publish_envelope(subject, headers, data)
        try:
            inc_bus("out", subject)
        except Exception:
            pass

    async def subscribe_json(self, subject: str, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        """
        Bind a JetStream **pull** subscription to the known stream with a **per-subject durable**,
        and run a background fetch loop that acks messages after the handler returns.
        """
        durable = self._durable_for(subject)
        print(f"[bus] subscribing subject={subject} durable={durable} stream={self.stream_name}", flush=True)

        # Access underlying nats.js client directly for robust control.
        js = getattr(self._bus, "_js", None)
        if js is None:
            raise RuntimeError("ampy-bus NATSBus has no ._js handle")

        # Some versions nest the manager; we only need the JS client interface:
        try:
            # Bind to existing durable with filter (must match your pre-created consumer)
            sub = await js.pull_subscribe(subject=subject, durable=durable, stream=self.stream_name)
        except Exception as e:
            print(f"[bus] subscribe FAILED subject={subject}: {e}", flush=True)
            raise

        print(f"[bus] subscribed subject={subject}", flush=True)

        async def _loop():
            while True:
                try:
                    msgs = await sub.fetch(batch=10, timeout=1.0)
                except Exception:
                    await asyncio.sleep(0.2)
                    continue
                for msg in msgs:
                    try:
                        # headers are not required for our control plane; pass None
                        try:
                            body = json.loads(msg.data.decode("utf-8"))
                        except Exception:
                            body = {"_raw": msg.data.decode("utf-8", "ignore")}
                        await handler(subject=msg.subject, data=body)
                        try:
                            inc_bus("in", msg.subject)
                        except Exception:
                            pass
                    except Exception:
                        traceback.print_exc()
                    finally:
                        try:
                            await msg.ack()
                        except Exception:
                            traceback.print_exc()

        task = asyncio.create_task(_loop())
        self._tasks.append(task)

    async def flush(self, timeout: float = 1.0):
        await asyncio.sleep(0)

    async def drain(self):
        # Gracefully stop background loops
        for t in self._tasks:
            t.cancel()
        await asyncio.sleep(0)
