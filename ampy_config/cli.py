from __future__ import annotations
import argparse, sys, os, yaml, json, asyncio, datetime, time
from typing import List, Optional, Dict, Any, Tuple
from .layering import build_effective_config
from .secrets.registry import SecretsManager, looks_like_secret_ref, walk_and_transform
from .control.events import subjects, ConfigPreviewRequested, ConfigApply, SecretRotated
from .control.agent import run_agent
from .bus.ampy_bus import AmpyBus as Bus
import asyncio

# ---------- helpers for wait-applied (poll effective config) ----------
def _flatten_overlay(prefix: str, node: Any, out: Dict[str, Any]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _flatten_overlay(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out[prefix] = node

def _get_by_path(cfg: Dict[str, Any], path: str) -> Tuple[bool, Any]:
    cur: Any = cfg
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur

def _effective_matches_overlay(
    effective: Dict[str, Any], overlay: Dict[str, Any]
) -> Tuple[bool, Dict[str, Tuple[Any, Any]]]:
    """
    Returns (ok, diffs). diffs[path] = (expected_from_overlay, actual_in_effective)
    """
    leaves: Dict[str, Any] = {}
    _flatten_overlay("", overlay or {}, leaves)
    diffs: Dict[str, Tuple[Any, Any]] = {}
    ok = True
    for path, exp in leaves.items():
        found, actual = _get_by_path(effective, path)
        if not found or actual != exp:
            ok = False
            diffs[path] = (exp, actual if found else "<missing>")
    return ok, diffs

def _wait_until_effective(
    *,
    profile: str,
    schema_path: str,
    defaults_path: str,
    overlays: List[str],
    service_overrides: List[str],
    env_allowlist_path: str,
    env_file: str | None,
    runtime_overrides_path: str | None,
    expected_overlay: Dict[str, Any],
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.5,
) -> Tuple[bool, Dict[str, Tuple[Any, Any]]]:
    """
    Poll build_effective_config until all overlay leaves match the effective view,
    or timeout. Returns (ok, diffs).
    """
    deadline = time.time() + timeout_s
    last_diffs: Dict[str, Tuple[Any, Any]] = {}
    while time.time() < deadline:
        effective, _ = build_effective_config(
            schema_path=schema_path,
            defaults_path=defaults_path,
            profile_yaml=f"examples/{profile}.yaml",
            overlays=overlays,
            service_overrides=service_overrides,
            env_allowlist_path=env_allowlist_path,
            env_file=env_file,
            runtime_overrides_path=runtime_overrides_path,
        )
        ok, diffs = _effective_matches_overlay(effective, expected_overlay)
        if ok:
            return True, {}
        last_diffs = diffs
        time.sleep(poll_interval_s)
    return False, last_diffs

async def _wait_for_applied(bus, subject: str, change_id: str, timeout: float = 10.0) -> bool:
    """
    Subscribe temporarily to the '...config_applied' subject and wait
    for matching change_id. Returns True if seen before timeout.
    """
    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()

    async def _cb(subject: str, data: dict) -> None:
        if data.get("change_id") == change_id:
            if not fut.done():
                fut.set_result(True)

    await bus.connect()
    # temp durable for this wait
    await bus.subscribe_json(subject, _cb)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return False

# -------- existing render + secret commands (unchanged) --------
def cmd_render(args) -> int:
    profile_yaml = f"examples/{args.profile}.yaml"
    try:
        cfg, prov = build_effective_config(
            schema_path=args.schema,
            defaults_path=args.defaults,
            profile_yaml=profile_yaml,
            overlays=args.overlay,
            service_overrides=args.service_override,
            env_allowlist_path=args.env_allowlist,
            env_file=args.env_file,
            runtime_overrides_path=args.runtime,
        )
    except AssertionError as ae:
        print(f"[FAIL] semantic checks: {ae}", file=sys.stderr); return 2
    except Exception as ex:
        print(f"[ERROR] {ex}", file=sys.stderr); return 2

    if args.resolve_secrets != "none":
        sm = SecretsManager(ttl_ms=args.secret_ttl_ms, enable_local_fallback=not args.no_local, local_path=args.local)
        if args.resolve_secrets == "redacted":
            cfg = walk_and_transform(cfg, looks_like_secret_ref, lambda ref: sm.redact(ref))
        elif args.resolve_secrets == "values":
            cfg = walk_and_transform(cfg, looks_like_secret_ref, lambda ref: sm.resolve(ref))
        else:
            print(f"[ERROR] unknown resolve mode: {args.resolve_secrets}", file=sys.stderr); return 2

    y = yaml.safe_dump(cfg, sort_keys=True)
    if args.output:
        with open(args.output, "w") as f:
            f.write(y)
        print(f"[OK] wrote effective config → {args.output}")
    else:
        print(y)

    if args.provenance:
        print("\n# Provenance (key ← source)")
        for k in sorted(prov.keys()):
            print(f"{k} ← {prov[k]}")
    return 0

def cmd_secret_get(args) -> int:
    sm = SecretsManager(ttl_ms=args.secret_ttl_ms, enable_local_fallback=not args.no_local, local_path=args.local)
    try:
        val = sm.resolve(args.ref)
    except Exception as ex:
        print(f"[ERROR] {ex}", file=sys.stderr); return 2
    print(val if args.plain else "***"); return 0

def cmd_secret_rotate(args) -> int:
    sm = SecretsManager(ttl_ms=args.secret_ttl_ms, enable_local_fallback=not args.no_local, local_path=args.local)
    sm.invalidate(args.ref); print(f"[OK] invalidated cache for {args.ref}"); return 0

# -------- new: OPS commands (publish control events) ----------
async def _publish(bus: Bus, subject: str, payload: dict, kind: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[DRY-RUN] Would publish to {subject}:")
        print(f"  Kind: {kind}")
        print(f"  Payload: {json.dumps(payload, indent=2)}")
        return
    
    try:
        await bus.connect()
        await bus.publish_json(subject, payload, kind=kind)
        await bus.flush()
    except Exception as e:
        print(f"[ERROR] Failed to publish to {subject}: {e}", file=sys.stderr)
        print(f"[HINT] Make sure NATS server is running and control plane agent is consuming events", file=sys.stderr)
        print(f"[HINT] Use --dry-run to test without publishing", file=sys.stderr)
        return 1
    return 0

def cmd_ops_preview(args) -> int:
    # Build to fetch topic_prefix
    cfg, _ = build_effective_config(
        schema_path=args.schema, defaults_path=args.defaults, profile_yaml=f"examples/{args.profile}.yaml",
        overlays=args.overlay, service_overrides=args.service_override,
        env_allowlist_path=args.env_allowlist, env_file=args.env_file,
        runtime_overrides_path=args.runtime)
    subs = subjects(cfg["bus"]["topic_prefix"])
    candidate = yaml.safe_load(open(args.overlay_file).read()) if args.overlay_file else {}
    evt = ConfigPreviewRequested(
        targets=args.targets.split(",") if args.targets else [],
        candidate=candidate, expires_at=args.expires_at, reason=args.reason, run_id=args.run_id, producer="ops-cli@1"
    ).to_dict()
    result = asyncio.run(_publish(Bus(args.bus_url), subs["preview"], evt, kind="ConfigPreviewRequested", dry_run=args.dry_run))
    if result is not None:
        return result
    if not args.dry_run:
        print(f"[OK] preview → {subs['preview']}")
    return 0

def cmd_ops_apply(args) -> int:
    cfg, _ = build_effective_config(
        schema_path=args.schema, defaults_path=args.defaults, profile_yaml=f"examples/{args.profile}.yaml",
        overlays=args.overlay, service_overrides=args.service_override,
        env_allowlist_path=args.env_allowlist, env_file=args.env_file,
        runtime_overrides_path=args.runtime)
    subs = subjects(cfg["bus"]["topic_prefix"])
    overlay = yaml.safe_load(open(args.overlay_file).read()) if args.overlay_file else {}
    evt = ConfigApply(
        change_id=args.change_id or ("chg_" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")),
        canary_percent=args.canary_percent, canary_duration=args.canary_duration,
        global_deadline=args.global_deadline, overlay=overlay, run_id=args.run_id, producer="ops-cli@1"
    ).to_dict()
    pub_rc = asyncio.run(_publish(Bus(args.bus_url), subs["apply"], evt, kind="ConfigApply", dry_run=args.dry_run))
    if pub_rc:
        return pub_rc
    if not args.dry_run:
        print(f"[OK] apply → {subs['apply']} (change_id={evt['change_id']})")

    # Choose a runtime path to poll against:
    #  - explicit --runtime if provided
    #  - else AMPY_CONFIG_RUNTIME_OVERRIDES
    #  - else default "runtime/overrides.yaml"
    runtime_path = args.runtime or os.environ.get("AMPY_CONFIG_RUNTIME_OVERRIDES", "runtime/overrides.yaml")
    if args.wait_applied and not args.dry_run:
        print(f"[INFO] waiting for effective config via runtime='{runtime_path}'")

    # Optional: wait until effective config reflects the overlay (runtime persisted)
    if args.wait_applied and not args.dry_run:
        ok, diffs = _wait_until_effective(
            profile=args.profile,
            schema_path=args.schema,
            defaults_path=args.defaults,
            overlays=args.overlay,
            service_overrides=args.service_override,
            env_allowlist_path=args.env_allowlist,
            env_file=args.env_file,
            runtime_overrides_path=runtime_path,
            expected_overlay=overlay or {},
            timeout_s=args.timeout,
            poll_interval_s=args.poll_interval,
        )
        if ok:
            print(f"[OK] applied confirmed in effective config (change_id={evt['change_id']})")
            return 0
        else:
            print("[ERROR] timed out waiting for overlay to be effective:", file=sys.stderr)
            for path, (exp, got) in diffs.items():
                print(f"  - {path}: expected={exp!r} got={got!r}", file=sys.stderr)
            return 1
    return 0

def cmd_ops_secret_rotated(args) -> int:
    cfg, _ = build_effective_config(
        schema_path=args.schema, defaults_path=args.defaults, profile_yaml=f"examples/{args.profile}.yaml",
        overlays=args.overlay, service_overrides=args.service_override,
        env_allowlist_path=args.env_allowlist, env_file=args.env_file,
        runtime_overrides_path=args.runtime)
    subs = subjects(cfg["bus"]["topic_prefix"])
    evt = SecretRotated(reference=args.reference, rotated_at=args.rotated_at, rollout=args.rollout, deadline=args.deadline, producer="ops-cli@1").to_dict()
    result = asyncio.run(_publish(Bus(args.bus_url), subs["secret_rotated"], evt, kind="SecretRotated", dry_run=args.dry_run))
    if result is not None:
        return result
    if not args.dry_run:
        print(f"[OK] secret_rotated → {subs['secret_rotated']}")
    return 0

def cmd_agent(args) -> int:
    asyncio.run(run_agent(
        profile=args.profile, schema_path=args.schema, defaults_path=args.defaults,
        overlay_paths=args.overlay, service_overrides=args.service_override,
        env_allowlist=args.env_allowlist, env_file=args.env_file, bus_url=args.bus_url))
    return 0

# -------- argparse wiring --------

def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ampy-config")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # render
    r = sub.add_parser("render", help="Render effective config with provenance")
    r.add_argument("--schema", default="schema/ampy-config.schema.json")
    r.add_argument("--defaults", default="config/defaults.yaml")
    r.add_argument("--profile", choices=["dev","paper","prod"], required=True)
    r.add_argument("--overlay", action="append", default=[], help="Path to region/cluster overlay YAML (repeatable)")
    r.add_argument("--service-override", action="append", default=[], help="Path to service override YAML (repeatable)")
    r.add_argument("--env-allowlist", default="env_allowlist.txt")
    r.add_argument("--env-file", default=None)
    r.add_argument("--runtime", default=None)
    r.add_argument("--provenance", action="store_true")
    r.add_argument("--output", default=None)
    r.add_argument("--resolve-secrets", choices=["none","redacted","values"], default="redacted")
    r.add_argument("--secret-ttl-ms", type=int, default=120000)
    r.add_argument("--no-local", action="store_true")
    r.add_argument("--local", default=None)
    r.set_defaults(func=cmd_render)

    # secret utils (same as before)
    g = sub.add_parser("secret", help="Secret utilities")
    gsub = g.add_subparsers(dest="subcmd", required=True)
    gget = gsub.add_parser("get", help="Resolve a secret reference")
    gget.add_argument("--plain", action="store_true")
    gget.add_argument("--secret-ttl-ms", type=int, default=120000)
    gget.add_argument("--no-local", action="store_true")
    gget.add_argument("--local", default=None)
    gget.add_argument("ref"); gget.set_defaults(func=cmd_secret_get)
    grot = gsub.add_parser("rotate", help="Invalidate cache for a secret")
    grot.add_argument("--secret-ttl-ms", type=int, default=120000)
    grot.add_argument("--no-local", action="store_true")
    grot.add_argument("--local", default=None)
    grot.add_argument("ref"); grot.set_defaults(func=cmd_secret_rotate)

    # OPS
    ops = sub.add_parser("ops", help="Publish control-plane events")
    opssub = ops.add_subparsers(dest="subcmd", required=True)

    p = opssub.add_parser("preview")
    for a in ("schema","defaults","profile","env_allowlist","env_file","runtime"):
        p.add_argument(f"--{a}", default={"schema":"schema/ampy-config.schema.json","defaults":"config/defaults.yaml","profile":None,"env_allowlist":"env_allowlist.txt","env_file":None,"runtime":None}[a])
    p.add_argument("--overlay", action="append", default=[])
    p.add_argument("--service-override", action="append", default=[])
    p.add_argument("--overlay-file", required=True, help="YAML fragment with the candidate changes")
    p.add_argument("--targets", default="")
    p.add_argument("--expires-at", required=True, help="ISO-8601 Z")
    p.add_argument("--reason", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--bus-url", default=None)
    p.add_argument("--dry-run", action="store_true", help="Show what would be published without actually publishing")
    p.set_defaults(func=cmd_ops_preview)

    a = opssub.add_parser("apply")
    for a1 in ("schema","defaults","profile","env_allowlist","env_file","runtime"):
        a.add_argument(f"--{a1}", default={"schema":"schema/ampy-config.schema.json","defaults":"config/defaults.yaml","profile":None,"env_allowlist":"env_allowlist.txt","env_file":None,"runtime":None}[a1])
    a.add_argument("--overlay", action="append", default=[])
    a.add_argument("--service-override", action="append", default=[])
    a.add_argument("--overlay-file", required=False, help="YAML fragment to apply (optional if you only tweak env/flags)")
    a.add_argument("--change-id", default=None)
    a.add_argument("--canary-percent", type=int, default=0)
    a.add_argument("--canary-duration", default="0s")
    a.add_argument("--global-deadline", default=None)
    a.add_argument("--run-id", default=None)
    a.add_argument("--bus-url", default=None)
    a.add_argument("--wait-applied", action="store_true", help="Wait until effective config reflects the overlay")
    a.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait with --wait-applied (default: 10)")
    a.add_argument("--poll-interval", type=float, default=0.5, help="Polling interval seconds (default: 0.5)")
    a.add_argument("--dry-run", action="store_true", help="Show what would be published without actually publishing")
    a.set_defaults(func=cmd_ops_apply)

    s = opssub.add_parser("secret-rotated")
    for a2 in ("schema","defaults","profile","env_allowlist","env_file","runtime"):
        s.add_argument(f"--{a2}", default={"schema":"schema/ampy-config.schema.json","defaults":"config/defaults.yaml","profile":None,"env_allowlist":"env_allowlist.txt","env_file":None,"runtime":None}[a2])
    s.add_argument("--overlay", action="append", default=[])
    s.add_argument("--service-override", action="append", default=[])
    s.add_argument("--reference", required=True)
    s.add_argument("--rotated-at", required=True)
    s.add_argument("--rollout", default="staged")
    s.add_argument("--deadline", default=None)
    s.add_argument("--bus-url", default=None)
    s.add_argument("--dry-run", action="store_true", help="Show what would be published without actually publishing")
    s.set_defaults(func=cmd_ops_secret_rotated)

    # agent
    ag = sub.add_parser("agent", help="Run the ampy-config control-plane agent")
    ag.add_argument("--schema", default="schema/ampy-config.schema.json")
    ag.add_argument("--defaults", default="config/defaults.yaml")
    ag.add_argument("--profile", choices=["dev","paper","prod"], required=True)
    ag.add_argument("--overlay", action="append", default=[])
    ag.add_argument("--service-override", action="append", default=[])
    ag.add_argument("--env-allowlist", default="env_allowlist.txt")
    ag.add_argument("--env-file", default=None)
    ag.add_argument("--bus-url", default=None)
    ag.set_defaults(func=cmd_agent)

    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
