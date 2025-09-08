from __future__ import annotations
import asyncio, yaml, os, pathlib, datetime
from typing import Dict, Any, List, Tuple
from ..layering import build_effective_config
from ..secrets.registry import SecretsManager
from ..bus.ampy_bus import AmpyBus as Bus
from .events import subjects, ConfigApplied

RUNTIME_OVERRIDES = os.environ.get("AMPY_CONFIG_RUNTIME_OVERRIDES", "runtime/overrides.yaml")

def deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat() + "Z"

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
    overlay_paths = overlay_paths or []
    service_overrides = service_overrides or []

    # Build initial config once (provenance unused here)
    cfg, prov = build_effective_config(
        schema_path=schema_path,
        defaults_path=defaults_path,
        profile_yaml=f"examples/{profile}.yaml",
        overlays=overlay_paths,
        service_overrides=service_overrides,
        env_allowlist_path=env_allowlist,
        env_file=env_file,
        runtime_overrides_path=RUNTIME_OVERRIDES if pathlib.Path(RUNTIME_OVERRIDES).exists() else None,
    )
    topic_prefix = cfg["bus"]["topic_prefix"]
    subs = subjects(topic_prefix)

    bus = Bus(bus_url)
    await bus.connect()

    sm = SecretsManager()  # used for SecretRotated invalidation

    async def on_preview(subject: str, data: Dict[str, Any]) -> None:
        # Validate candidate overlay WITHOUT persisting
        candidate = data.get("candidate") or {}
        tmp_file = ".ampy-config.preview.tmp.yaml"
        pathlib.Path(tmp_file).write_text(yaml.safe_dump(candidate))
        try:
            build_effective_config(
                schema_path=schema_path,
                defaults_path=defaults_path,
                profile_yaml=f"examples/{profile}.yaml",
                overlays=overlay_paths,
                service_overrides=service_overrides,
                env_allowlist_path=env_allowlist,
                env_file=env_file,
                runtime_overrides_path=tmp_file,
            )
            # If we got here, candidate is valid — you could publish an ACK if desired.
        finally:
            try: pathlib.Path(tmp_file).unlink()
            except: pass

    async def on_apply(subject: str, data: Dict[str, Any]) -> None:
        change_id = data.get("change_id", "chg_" + utc_now().replace(":", "").replace("-", ""))
        overlay = data.get("overlay") or {}

        # Validate by layering in a TEMP file first
        tmp_file = ".ampy-config.apply.tmp.yaml"
        pathlib.Path(tmp_file).write_text(yaml.safe_dump(overlay))

        errors: List[str] = []
        status = "ok"
        try:
            build_effective_config(
                schema_path=schema_path,
                defaults_path=defaults_path,
                profile_yaml=f"examples/{profile}.yaml",
                overlays=overlay_paths,
                service_overrides=service_overrides,
                env_allowlist_path=env_allowlist,
                env_file=env_file,
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
            # Persist: merge overlay into runtime/overrides.yaml with atomic write
            p = pathlib.Path(RUNTIME_OVERRIDES)
            current = {}
            if p.exists():
                current = yaml.safe_load(p.read_text()) or {}
            merged = deep_merge(current, overlay)
            p.parent.mkdir(parents=True, exist_ok=True)
            
            # Atomic write to avoid torn files
            tmp = p.with_suffix(".tmp")
            tmp.write_text(yaml.safe_dump(merged))
            tmp.replace(p)  # atomic on most OS/filesystems

        # Publish ConfigApplied (ok or rejected)
        evt = ConfigApplied(
            change_id=change_id,
            status=status,
            effective_at=utc_now(),
            errors=errors or None,
            service=os.environ.get("AMPY_CONFIG_SERVICE", "ampy-config"),
            run_id=data.get("run_id"),
        )
        await bus.publish_json(subs["applied"], evt.to_dict(), kind="ConfigApplied")


    async def on_secret_rotated(subject: str, data: Dict[str, Any]) -> None:
        ref = data.get("reference")
        if ref:
            sm.invalidate(ref)

    # Subscriptions
    await bus.subscribe_json(subs["preview"], on_preview)
    await bus.subscribe_json(subs["apply"], on_apply)
    await bus.subscribe_json(subs["secret_rotated"], on_secret_rotated)

    print(f"[agent] listening on:\n  - {subs['preview']}\n  - {subs['apply']}\n  - {subs['secret_rotated']}")
    while True:
        await asyncio.sleep(1)
