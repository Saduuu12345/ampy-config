from __future__ import annotations
import argparse, sys, yaml
from typing import List
from .layering import build_effective_config
from .secrets.registry import SecretsManager, looks_like_secret_ref, walk_and_transform

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

    # Optional secret resolution (none|redacted|values)
    if args.resolve_secrets != "none":
        sm = SecretsManager(ttl_ms=args.secret_ttl_ms, enable_local_fallback=not args.no_local, local_path=args.local)
        if args.resolve_secrets == "redacted":
            cfg = walk_and_transform(cfg, looks_like_secret_ref, lambda ref: sm.redact(ref))
        elif args.resolve_secrets == "values":
            # WARNING: prints actual secret values to stdout/file; for demo only.
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
    print(val if args.plain else "***")
    return 0

def cmd_secret_rotate(args) -> int:
    sm = SecretsManager(ttl_ms=args.secret_ttl_ms, enable_local_fallback=not args.no_local, local_path=args.local)
    sm.invalidate(args.ref)
    print(f"[OK] invalidated cache for {args.ref}")
    return 0

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
    r.add_argument("--env-file", default=None, help="Optional .env file (KEY=VALUE lines)")
    r.add_argument("--runtime", default=None, help="Path to runtime overrides YAML")
    r.add_argument("--provenance", action="store_true", help="Also print provenance table")
    r.add_argument("--output", default=None, help="Write effective config YAML to this path")

    r.add_argument("--resolve-secrets", choices=["none","redacted","values"], default="redacted",
                   help="If set, transform secret refs in the rendered config")
    r.add_argument("--secret-ttl-ms", type=int, default=120000)
    r.add_argument("--no-local", action="store_true", help="Disable local dev secrets fallback")
    r.add_argument("--local", default=None, help="Path to .secrets.local.json")

    r.set_defaults(func=cmd_render)

    # secret get
    g = sub.add_parser("secret", help="Secret utilities")
    gsub = g.add_subparsers(dest="subcmd", required=True)

    gget = gsub.add_parser("get", help="Resolve a secret reference")
    gget.add_argument("--plain", action="store_true", help="Print the raw secret (careful!)")
    gget.add_argument("--secret-ttl-ms", type=int, default=120000)
    gget.add_argument("--no-local", action="store_true")
    gget.add_argument("--local", default=None)
    gget.add_argument("ref")
    gget.set_defaults(func=cmd_secret_get)

    grot = gsub.add_parser("rotate", help="Simulate rotation by invalidating cache")
    grot.add_argument("--secret-ttl-ms", type=int, default=120000)
    grot.add_argument("--no-local", action="store_true")
    grot.add_argument("--local", default=None)
    grot.add_argument("ref")
    grot.set_defaults(func=cmd_secret_rotate)

    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())

