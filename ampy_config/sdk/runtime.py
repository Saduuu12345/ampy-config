# ampy_config/sdk/runtime.py
from __future__ import annotations
import os, threading, asyncio, yaml, pathlib, datetime, copy
from typing import Any, Dict, Callable, List, Optional, Tuple

from ..layering import build_effective_config
from ..control.events import subjects, ConfigApplied

def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat() + "Z"

def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def _get_by_path(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur

class ConfigRuntime:
    """
    In-process config agent for AmpyFin services.

    - Loads effective config at startup (typed & validated)
    - Subscribes to control-plane events (preview/apply/secret_rotated)
    - Validates applies, atomically swaps effective config on success
    - Publishes ConfigApplied (ok/rejected)
    - Fires registered callbacks on every successful change
    """

    def __init__(
        self,
        profile: str,
        schema_path: str = "schema/ampy-config.schema.json",
        defaults_path: str = "config/defaults.yaml",
        overlays: Optional[List[str]] = None,
        service_overrides: Optional[List[str]] = None,
        env_allowlist: str = "env_allowlist.txt",
        env_file: Optional[str] = None,
        bus_url: Optional[str] = None,
    ):
        self.profile = profile
        self.schema_path = schema_path
        self.defaults_path = defaults_path
        self.overlays = overlays or []
        self.service_overrides = service_overrides or []
        self.env_allowlist = env_allowlist
        self.env_file = env_file
        self.bus_url = bus_url or os.environ.get("NATS_URL")

        self._cfg: Dict[str, Any] = {}
        self._prov: Dict[str, str] = {}
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.RLock()

        self._thread: Optional[threading.Thread] = None
        self._stop_ev = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -------- public API

    def load(self) -> Dict[str, Any]:
        """Load and return the current effective config (no bus)."""
        cfg, prov = build_effective_config(
            schema_path=self.schema_path,
            defaults_path=self.defaults_path,
            profile_yaml=f"examples/{self.profile}.yaml",
            overlays=self.overlays,
            service_overrides=self.service_overrides,
            env_allowlist_path=self.env_allowlist,
            env_file=self.env_file,
            runtime_overrides_path=None,  # in-proc SDK applies are bus-driven
        )
        with self._lock:
            self._cfg, self._prov = cfg, prov
        return copy.deepcopy(cfg)

    def get(self, path: str, default: Any = None, cast: Optional[Callable[[Any], Any]] = None) -> Any:
        """Typed key lookup with optional cast."""
        with self._lock:
            val = _get_by_path(self._cfg, path, default)
        if cast is not None and val is not None:
            try:
                return cast(val)
            except Exception:
                return default
        return val

    def on_change(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback invoked with the new config after each successful apply."""
        with self._lock:
            self._callbacks.append(cb)

    def start_background(self) -> None:
        """Spawn a background thread that runs the bus loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_ev.clear()
        self._thread = threading.Thread(target=self._thread_main, name="ampy-config-sdk", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_ev.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=timeout)

    # -------- internals

    def _thread_main(self):
        asyncio.run(self._async_main())

    async def _async_main(self):
        self._loop = asyncio.get_running_loop()
        # initial load
        self.load()
        topic_prefix = self._cfg["bus"]["topic_prefix"]
        subs = subjects(topic_prefix)

        # Lazy import to avoid requiring ampybus when not using bus functionality
        from ..bus.ampy_bus import AmpyBus as Bus
        bus = Bus(self.bus_url)
        await bus.connect()

        async def on_preview(subject: str, data: Dict[str, Any]) -> None:
            # Validate candidate only; no state change
            candidate = data.get("candidate") or {}
            tmp_file = ".ampy-config.sdk.preview.tmp.yaml"
            pathlib.Path(tmp_file).write_text(yaml.safe_dump(candidate))
            try:
                build_effective_config(
                    schema_path=self.schema_path,
                    defaults_path=self.defaults_path,
                    profile_yaml=f"examples/{self.profile}.yaml",
                    overlays=self.overlays,
                    service_overrides=self.service_overrides,
                    env_allowlist_path=self.env_allowlist,
                    env_file=self.env_file,
                    runtime_overrides_path=tmp_file,
                )
            finally:
                try: pathlib.Path(tmp_file).unlink()
                except: pass

        async def on_apply(subject: str, data: Dict[str, Any]) -> None:
            change_id = data.get("change_id", "chg_" + _utc_now().replace(":", "").replace("-", ""))
            overlay = data.get("overlay") or {}

            tmp_file = ".ampy-config.sdk.apply.tmp.yaml"
            pathlib.Path(tmp_file).write_text(yaml.safe_dump(overlay))
            status = "ok"; errors: List[str] = []
            try:
                cfg, prov = build_effective_config(
                    schema_path=self.schema_path,
                    defaults_path=self.defaults_path,
                    profile_yaml=f"examples/{self.profile}.yaml",
                    overlays=self.overlays,
                    service_overrides=self.service_overrides,
                    env_allowlist_path=self.env_allowlist,
                    env_file=self.env_file,
                    runtime_overrides_path=tmp_file,
                )
            except AssertionError as ae:
                status = "rejected"; errors.append(str(ae))
            except Exception as ex:
                status = "rejected"; errors.append(str(ex))
            finally:
                try: pathlib.Path(tmp_file).unlink()
                except: pass

            if status == "ok":
                with self._lock:
                    self._cfg, self._prov = cfg, prov
                    callbacks = list(self._callbacks)
                for cb in callbacks:
                    try: cb(copy.deepcopy(cfg))
                    except Exception: pass

            # publish ConfigApplied regardless
            evt = ConfigApplied(
                change_id=change_id, status=status, effective_at=_utc_now(),
                errors=errors or None, service=os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config-sdk"),
                run_id=data.get("run_id"),
            )
            await bus.publish_json(subs["applied"], evt.to_dict(), kind="ConfigApplied")

        async def on_secret_rotated(subject: str, data: Dict[str, Any]) -> None:
            # If you add secret caching here later, invalidate it on this event.
            return

        await bus.subscribe_json(subs["preview"], on_preview)
        await bus.subscribe_json(subs["apply"], on_apply)
        await bus.subscribe_json(subs["secret_rotated"], on_secret_rotated)

        while not self._stop_ev.is_set():
            await asyncio.sleep(0.2)
