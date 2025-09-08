from __future__ import annotations
import os, json, uuid, asyncio
from typing import Awaitable, Callable, Any
from ampybus import nats_bus
from ampybus.headers import Headers

def _producer_id() -> str:
    return os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config@cli")

def _schema(kind: str) -> str:
    return f"ampy.control.v1.{kind}"

def _ns_to_stream_age_ns(days: int) -> int:
    return days * 24 * 60 * 60 * 1_000_000_000  # JetStream expects nanoseconds

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

        # Dev/ops knobs (strings to keep env simple)
        self.auto_provision = os.environ.get("AMPY_CONFIG_AUTO_PROVISION", "false").lower() == "true"
        self.stream_name = os.environ.get("AMPY_CONFIG_STREAM", "ampy-control")
        self.subject_pattern = os.environ.get("AMPY_CONFIG_SUBJECT_PATTERN", "ampy.*.control.v1.*")
        self.durable = os.environ.get("AMPY_CONFIG_DURABLE", "ampy-config-agent")

    async def connect(self):
        try:
            await asyncio.wait_for(self._bus.connect(), timeout=10.0)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Timeout connecting to NATS at {self.url}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to NATS at {self.url}: {e}")
        if self.auto_provision:
            await self._ensure_stream()

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
                max_age=_ns_to_stream_age_ns(1),  # 1 day retention (ns)
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

    async def subscribe_json(self, subject: str, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        """
        Subscribes with a stable durable so restarts resume at last acked message.
        If your ampy-bus exposes explicit ack control, call msg.ack() after success.
        """
        async def _cb(subject_: str, headers: Any, payload: bytes, msg: Any = None) -> None:
            try:
                body = json.loads(payload.decode("utf-8"))
            except Exception:
                body = {"_raw": payload.decode("utf-8", "ignore")}
            await handler(subject=subject_, data=body)
            # If ampy-bus requires manual ack for pull consumers, uncomment:
            # if hasattr(msg, "ack"):
            #     await msg.ack()

        await self._bus.subscribe_pull(subject, self.durable, _cb)

    async def flush(self, timeout: float = 1.0):
        await asyncio.sleep(0)

    async def drain(self):
        await asyncio.sleep(0)
