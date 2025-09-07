#!/usr/bin/env python3
"""
ampy-config schema validator

Usage:
  python tools/validate.py examples/dev.yaml
  python tools/validate.py --schema schema/ampy-config.schema.json examples/*.yaml
"""
import argparse, json, sys, re, pathlib
from typing import Any, Dict

try:
    import yaml  # pyyaml
except ImportError:
    print("Please `pip install pyyaml jsonschema`", file=sys.stderr); sys.exit(2)
try:
    import jsonschema
except ImportError:
    print("Please `pip install jsonschema`", file=sys.stderr); sys.exit(2)

DURATION_RE = re.compile(r'^[0-9]+(ms|s|m|h|d)$')
SIZE_RE = re.compile(r'^[0-9]+(B|KiB|MiB|GiB|TiB)$')

def load_yaml(p: pathlib.Path) -> Dict[str, Any]:
    with p.open() as f:
        return yaml.safe_load(f)

def load_schema(p: pathlib.Path) -> Dict[str, Any]:
    with p.open() as f:
        return json.load(f)

SIZE_UNITS = {"TiB": 1024**4, "GiB": 1024**3, "MiB": 1024**2, "KiB": 1024, "B": 1}
DUR_UNITS  = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}

def size_to_bytes(s: str) -> int:
    m = re.fullmatch(r'(\d+)(TiB|GiB|MiB|KiB|B)', s)
    if not m:
        raise ValueError(f"bad size: {s!r}")
    n, unit = m.groups()
    return int(n) * SIZE_UNITS[unit]

def duration_to_ms(s: str) -> int:
    m = re.fullmatch(r'(\d+)(ms|s|m|h|d)', s)
    if not m:
        raise ValueError(f"bad duration: {s!r}")
    n, unit = m.groups()
    return int(n) * DUR_UNITS[unit]


def semantic_checks(cfg: Dict[str, Any]) -> None:
    # Existing checks
    comp = size_to_bytes(cfg["bus"]["compression_threshold"])
    maxp = size_to_bytes(cfg["bus"]["max_payload_size"])
    assert comp < maxp, "bus.compression_threshold must be < bus.max_payload_size"

    dd = cfg["oms"]["risk"]["max_drawdown_halt_bp"]
    assert 50 <= dd <= 1000, "oms.risk.max_drawdown_halt_bp must be in [50,1000]"

    if cfg["bus"]["env"] == "prod":
        delay = duration_to_ms(cfg["oms"]["throt"]["min_inter_order_delay"])
        assert delay >= 5, "prod: oms.throt.min_inter_order_delay must be >= 5ms"

    # NEW: ensemble sanity
    ens = cfg["ml"]["ensemble"]
    assert ens["min_models"] <= ens["max_models"], "ml.ensemble.min_models must be <= max_models"

    # NEW: feature_flags type/value coherence
    for name, flag in (cfg.get("feature_flags") or {}).items():
        t = flag.get("type")
        v = flag.get("value")
        if t == "bool":
            assert isinstance(v, bool), f"feature_flags.{name}.value must be boolean"
        elif t == "int":
            assert isinstance(v, int), f"feature_flags.{name}.value must be integer"
        elif t == "enum":
            allowed = flag.get("allowed") or []
            assert allowed, f"feature_flags.{name}.allowed must be set for enum"
            assert v in allowed, f"feature_flags.{name}.value must be one of {allowed}"

    # NEW: broker/alpaca required fields when enabled
    alp = cfg["broker"]["alpaca"]
    if alp.get("enabled"):
        for req in ("base_url", "key_id", "secret_key"):
            assert alp.get(req), f"broker.alpaca.{req} required when alpaca.enabled=true"
        # Optional: sandbox/URL coherence
        if alp.get("sandbox"):
            assert "paper" in alp["base_url"], "alpaca.sandbox=true expects paper API base_url"
        else:
            assert "paper" not in alp["base_url"], "alpaca.sandbox=false expects live API base_url"

    # NEW: FX providers unique priorities
    prios = [p["priority"] for p in cfg["fx"]["providers"]]
    assert len(prios) == len(set(prios)), "fx.providers priorities must be unique"

    # NEW: databento enabled implies non-empty streams
    db = cfg["ingest"]["databento"]
    if db.get("enabled"):
        assert db.get("streams"), "ingest.databento.streams must be non-empty when enabled"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default="schema/ampy-config.schema.json")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    schema_path = pathlib.Path(args.schema)
    schema = load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)

    ok = True
    for fname in args.files:
        p = pathlib.Path(fname)
        try:
            data = load_yaml(p)
            errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
            if errors:
                ok = False
                print(f"[FAIL] {p}:")
                for e in errors:
                    loc = "/".join(map(str, e.path))
                    print(f"  - {loc}: {e.message}")
                continue
            try:
                semantic_checks(data)
            except AssertionError as ae:
                ok = False
                print(f"[FAIL] {p}: semantic check failed: {ae}")
                continue
            print(f"[OK]   {p}")
        except Exception as ex:
            ok = False
            print(f"[ERROR] {p}: {ex}")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
