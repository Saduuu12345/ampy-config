from __future__ import annotations
import asyncio, json, os
from typing import Awaitable, Callable, Any
from nats.aio.client import Client as NATS

class NatsBus:
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
        self.nc = NATS()

    async def connect(self):
        await self.nc.connect(servers=[self.url])

    async def publish_json(self, subject: str, payload: dict) -> None:
        await self.nc.publish(subject, json.dumps(payload).encode("utf-8"))

    async def subscribe_json(self, subject: str, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        async def cb(msg):
            try:
                data = json.loads(msg.data.decode("utf-8"))
            except Exception:
                data = {"_raw": msg.data.decode("utf-8", "ignore")}
            await handler(msg.subject, data)
        await self.nc.subscribe(subject, cb=cb)

    async def flush(self, timeout: float = 1.0): await self.nc.flush(timeout=timeout)
    async def drain(self): await self.nc.drain()
