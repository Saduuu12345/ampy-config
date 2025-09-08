from __future__ import annotations
import asyncio, yaml, os, pathlib, datetime, json, traceback
from typing import Dict, Any, List, Optional

from ..layering import build_effective_config
from ..bus.ampy_bus import AmpyBus as Bus
from .events import subjects, ConfigApplied
from ..secrets.registry import SecretsManager  # lazily instantiated only when needed

# Shared runtime overrides file (can be overridden via env)
RUNTIME_OVERRIDES = os.environ.get("AMPY_CONFIG_RUNTIME_OVERRIDES", "runtime/overrides.yaml")


# ---------------- small helpers ----------------

def deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """In-place deep merge of src into dst."""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def utc_now() -> str:
    # ISO-8601 Z with seconds precision (matches earlier examples)
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat() + "Z"

def jlog(level: str, msg: str, **extra: Any) -> None:
    """Tiny JSON logger to keep agent output structured and greppable."""
    print(json.dumps({"level": level, "msg": msg, "logger": "ampy-config", "extra": extra}, separators=(",", ":")))


# ---------------- agent ----------------

async def run_agent(
    profile: str,
    schema_path: str = "schema/ampy-config.schema.json",
    defaults_path: str = "config/defaults.yaml",
    overlay_paths: List[str] | None = None,
    service_overrides: List[str] | None = None,
    env_allowlist: str = "env_allowlist.txt",
    env_file: str | None = None,
    bus_url: str | None = None,
) -> None:
    """
    The control-plane agent:
      - builds initial effective config
      - subscribes to preview/apply/secret_rotated
      - validates preview/apply overlays (without and then with persistence)
      - persists accepted overlays to RUNTIME_OVERRIDES
      - publishes ConfigApplied (ok|rejected)
      - invalidates secret cache on SecretRotated (lazy, no backend calls)
    """
    overlay_paths = overlay_paths or []
    service_overrides = service_overrides or []

    # Ensure the runtime overrides file exists so --wait-applied can poll immediately
    ro_path = pathlib.Path(RUNTIME_OVERRIDES)
    ro_path.parent.mkdir(parents=True, exist_ok=True)
    if not ro_path.exists():
        ro_path.write_text("{}\n")

    # Build initial effective config (validates + semantic checks)
    try:
        cfg, _prov = build_effective_config(
            schema_path=schema_path,
            defaults_path=defaults_path,
            profile_yaml=f"examples/{profile}.yaml",
            overlays=overlay_paths,
            service_overrides=service_overrides,
            env_allowlist_path=env_allowlist,
            env_file=env_file,
            runtime_overrides_path=ro_path.as_posix(),
        )
    except Exception as e:
        jlog("error", "initial_build_failed", error=str(e))
        raise

    topic_prefix = cfg["bus"]["topic_prefix"]
    subs = subjects(topic_prefix)

    # Connect bus (our wrapper auto-provisions stream + per-subject durables)
    bus = Bus(bus_url)
    await bus.connect()

    # Lazy secrets manager: only instantiate on first SecretRotated
    sm: Optional[SecretsManager] = None
    def get_sm() -> SecretsManager:
        nonlocal sm
        if sm is None:
            # In dev, you likely want: export AMPY_CONFIG_SECRET_RESOLVERS="local"
            sm = SecretsManager()
        return sm

    # -------- handlers --------

    async def on_preview(subject: str, data: Dict[str, Any]) -> None:
        """Validate candidate overlay WITHOUT persisting; log outcome."""
        candidate = data.get("candidate") or {}
        tmp = pathlib.Path(".ampy-config.preview.tmp.yaml")
        tmp.write_text(yaml.safe_dump(candidate))
        try:
            build_effective_config(
                schema_path=schema_path,
                defaults_path=defaults_path,
                profile_yaml=f"examples/{profile}.yaml",
                overlays=overlay_paths,
                service_overrides=service_overrides,
                env_allowlist_path=env_allowlist,
                env_file=env_file,
                runtime_overrides_path=tmp.as_posix(),
            )
            jlog("info", "preview_valid", subject=subject, keys=list(candidate.keys()))
        except AssertionError as ae:
            jlog("warn", "preview_semantic_invalid", subject=subject, error=str(ae))
        except Exception as ex:
            jlog("warn", "preview_invalid", subject=subject, error=str(ex))
        finally:
            try: tmp.unlink()
            except: pass

    async def on_apply(subject: str, data: Dict[str, Any]) -> None:
        """
        Validate the overlay layered as a temporary runtime fragment.
        If valid -> merge into persistent runtime/overrides.yaml.
        Publish ConfigApplied either way.
        """
        change_id = data.get("change_id", "chg_" + utc_now().replace(":", "").replace("-", ""))
        overlay = data.get("overlay") or {}

        tmp = pathlib.Path(".ampy-config.apply.tmp.yaml")
        tmp.write_text(yaml.safe_dump(overlay))

        status = "ok"
        errors: List[str] = []

        try:
            # Validation pass (no persistence yet)
            build_effective_config(
                schema_path=schema_path,
                defaults_path=defaults_path,
                profile_yaml=f"examples/{profile}.yaml",
                overlays=overlay_paths,
                service_overrides=service_overrides,
                env_allowlist_path=env_allowlist,
                env_file=env_file,
                runtime_overrides_path=tmp.as_posix(),
            )
        except AssertionError as ae:
            status = "rejected"; errors.append(str(ae))
        except Exception as ex:
            status = "rejected"; errors.append(str(ex))
        finally:
            try: tmp.unlink()
            except: pass

        if status == "ok":
            # Persist: merge overlay into runtime overrides
            current = {}
            try:
                current = yaml.safe_load(ro_path.read_text()) or {}
            except Exception:
                current = {}
            merged = deep_merge(current, overlay)
            ro_path.write_text(yaml.safe_dump(merged))

        # Publish outcome
        evt = ConfigApplied(
            change_id=change_id,
            status=status,
            effective_at=utc_now(),
            errors=errors or None,
            service=os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config"),
            run_id=data.get("run_id"),
        ).to_dict()
        try:
            await bus.publish_json(subs["applied"], evt, kind="ConfigApplied")
        except Exception as e:
            jlog("warn", "publish_config_applied_failed", error=str(e))
        jlog("info", "config_apply", change_id=change_id, status=status, errors=errors)

    async def on_secret_rotated(subject: str, data: Dict[str, Any]) -> None:
        ref = data.get("reference")
        if ref:
            try:
                # Cache-only operation; no backend network calls here
                get_sm().invalidate(ref)
                jlog("info", "secret_cache_invalidated", reference=ref)
            except Exception as e:
                jlog("warn", "secret_invalidate_failed", reference=ref, error=str(e))

    # -------- subscriptions (3 subjects) --------
    await bus.subscribe_json(subs["preview"], on_preview)
    await bus.subscribe_json(subs["apply"], on_apply)
    await bus.subscribe_json(subs["secret_rotated"], on_secret_rotated)

    print(f"[agent] listening on:\n  - {subs['preview']}\n  - {subs['apply']}\n  - {subs['secret_rotated']}")

    # -------- keep alive --------
    while True:
        await asyncio.sleep(1)
