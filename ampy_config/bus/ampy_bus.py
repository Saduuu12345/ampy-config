from __future__ import annotations
import os, json, uuid, asyncio, re, traceback
from typing import Awaitable, Callable, Any

from ampybus import nats_bus  # AmpyBus wrapper over python-nats
from nats.js.api import (
    StreamConfig, ConsumerConfig,
    RetentionPolicy, StorageType,
    DeliverPolicy, AckPolicy, ReplayPolicy,
)

# ---------------- utils ----------------

def _producer_id() -> str:
    return os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config@cli")

def _schema(kind: str) -> str:
    return f"ampy.control.v1.{kind}"

_slug_re = re.compile(r"[^a-zA-Z0-9]+")

def _slug(s: str) -> str:
    return _slug_re.sub("-", s).strip("-").lower()

def _durable_for(service: str, subject: str) -> str:
    return f"{_slug(service)}-{_slug(subject)}"

def _stream_name() -> str:
    return "ampy-control"

# ---------------- bus wrapper ----------------

class AmpyBus:
    """
    JSON convenience wrapper over ampy-bus NATSBus with robust auto-provision.
    Strategy:
      - JetStream first: Create one stream, per-subject durable pull consumers
      - If AMPY_CONFIG_JS_FALLBACK=1 or JS operations fail → direct NATS subscribe
    """
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
        self._bus = nats_bus.NATSBus(self.url)
        self._direct_nc = None  # set if we fallback

    async def connect(self):
        try:
            await asyncio.wait_for(self._bus.connect(), timeout=10.0)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to NATS at {self.url}: {e}") from e

    # -------- publish --------

    async def publish_json(self, subject: str, payload: dict, kind: str = "Generic") -> None:
        from ampybus.headers import Headers
        headers = Headers(
            message_id=str(uuid.uuid4()),
            schema_fqdn=_schema(kind),
            producer=_producer_id(),
            source="ampy-config",
            partition_key="control",
            content_type="application/json",
            run_id=os.environ.get("AMPY_CONFIG_RUN_ID", f"run-{uuid.uuid4().hex[:8]}")
        )
        await self._bus.publish_envelope(subject, headers, json.dumps(payload).encode("utf-8"))

    # -------- subscribe (JS first, optional fallback) --------

    async def subscribe_json(
        self,
        subject: str,
        handler: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        service = os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config")
        durable = _durable_for(service, subject)

        # If user explicitly wants fallback, skip JS entirely
        if os.environ.get("AMPY_CONFIG_JS_FALLBACK") == "1":
            print(f"[bus] JS fallback forced via AMPY_CONFIG_JS_FALLBACK=1 for {subject}")
            await self._subscribe_direct_nats(subject, handler)
            return

        try:
            stream_name = await self._ensure_stream(subject)
            await self._ensure_consumer(stream_name, subject, durable)

            async def _cb(subject_: str, headers: Any, payload: bytes) -> None:
                try:
                    body = json.loads(payload.decode("utf-8"))
                except Exception:
                    body = {"_raw": payload.decode("utf-8", "ignore")}
                await handler(subject=subject_, data=body)

            print(f"[bus] subscribing JS (pull) subject={subject} durable={durable} stream={stream_name}")
            # Uses ampy-bus' JetStream pull wrapper (non-blocking listener internally)
            await self._bus.subscribe_pull(subject=subject, durable=durable, cb=_cb)
            print(f"[bus] subscribed JS subject={subject}")
        except Exception as e:
            print(f"[bus] JetStream subscribe failed for {subject}: {e}")
            print("[bus] Falling back to direct NATS (no persistence)…")
            await self._subscribe_direct_nats(subject, handler)

    # -------- internals --------

    async def _ensure_stream(self, subject: str) -> str:
        js = self._bus._js
        jsm = js._jsm
        name = _stream_name()

        # Fast path: exists?
        try:
            info = await asyncio.wait_for(jsm.stream_info(name), timeout=2.0)
            return info.config.name
        except Exception:
            pass

        # Try discover
        try:
            found = await asyncio.wait_for(jsm.find_stream_name_by_subject(subject), timeout=2.0)
            if found:
                return found
        except Exception:
            pass

        # Create
        cfg = StreamConfig(
            name=name,
            subjects=["ampy.*.control.v1.*"],
            retention=RetentionPolicy.LIMITS,
            max_age=24 * 60 * 60,          # seconds
            max_msgs=10_000,
            max_bytes=100 * 1024 * 1024,   # 100 MB
            storage=StorageType.FILE,
        )
        try:
            await asyncio.wait_for(jsm.add_stream(cfg), timeout=4.0)
            print(f"[bus] created stream {name} (subjects=ampy.*.control.v1.*)")
        except Exception as e:
            # benign if created by another client; verify
            try:
                await asyncio.wait_for(jsm.stream_info(name), timeout=2.0)
            except Exception:
                print(f"[bus] ERROR: failed to create stream {name}: {e}")
                traceback.print_exc()
                raise
        return name

    async def _ensure_consumer(self, stream: str, subject: str, durable: str) -> None:
        js = self._bus._js
        jsm = js._jsm

        # Exists & matches filter?
        try:
            info = await asyncio.wait_for(jsm.consumer_info(stream, durable), timeout=2.0)
            cfg = getattr(info, "config", None)
            fsub = getattr(cfg, "filter_subject", None) if cfg else None
            if fsub and fsub != subject:
                print(f"[bus] WARNING: durable={durable} has filter={fsub} expected={subject}; replacing")
                try:
                    await asyncio.wait_for(jsm.delete_consumer(stream, durable), timeout=2.0)
                except Exception as e:
                    print(f"[bus] ERROR: failed to delete mismatched consumer {durable}: {e}")
                    traceback.print_exc()
                    raise
            else:
                return  # good to go
        except Exception:
            pass

        cfg = ConsumerConfig(
            durable_name=durable,
            filter_subject=subject,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            replay_policy=ReplayPolicy.INSTANT,
            ack_wait=60,          # seconds
            max_ack_pending=512,
        )
        try:
            await asyncio.wait_for(jsm.add_consumer(stream, cfg), timeout=4.0)
            print(f"[bus] created consumer durable={durable} filter={subject}")
        except Exception as e:
            # benign if race; verify
            try:
                await asyncio.wait_for(jsm.consumer_info(stream, durable), timeout=2.0)
            except Exception:
                print(f"[bus] ERROR: could not create consumer {durable}: {e}")
                traceback.print_exc()
                raise

    async def _subscribe_direct_nats(self, subject: str, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        """Direct NATS fallback (no persistence)."""
        from nats.aio.client import Client as NATS

        if self._direct_nc is None:
            nc = NATS()
            await nc.connect(servers=[self.url])
            self._direct_nc = nc
            print(f"[bus] connected to NATS directly at {self.url}")
        else:
            nc = self._direct_nc

        async def _cb(msg):
            try:
                body = json.loads(msg.data.decode("utf-8"))
            except Exception:
                body = {"_raw": msg.data.decode("utf-8", "ignore")}
            await handler(subject=msg.subject, data=body)

        await nc.subscribe(subject, cb=_cb)
        print(f"[bus] subscribed direct NATS subject={subject}")

    # compatibility
    async def flush(self, timeout: float = 1.0):
        await asyncio.sleep(0)

    async def drain(self):
        # If we created a direct conn, close it gracefully
        try:
            if self._direct_nc is not None and not self._direct_nc.is_closed:
                await self._direct_nc.drain()
        except Exception:
            pass
        await asyncio.sleep(0)
