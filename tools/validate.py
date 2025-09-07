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

def duration_to_ms(s: str) -> int:
    val = int(re.match(r'^([0-9]+)', s).group(1))
    if s.endswith('ms'): return val
    if s.endswith('s'): return val*1000
    if s.endswith('m'): return val*60*1000
    if s.endswith('h'): return val*60*60*1000
    if s.endswith('d'): return val*24*60*60*1000
    raise ValueError("bad duration")

def size_to_bytes(s: str) -> int:
    val = int(re.match(r'^([0-9]+)', s).group(1))
    if s.endswith('TiB'): return val*1024**4
    if s.endswith('GiB'): return val*1024**3
    if s.endswith('MiB'): return val*1024**2
    if s.endswith('KiB'): return val*1024
    if s.endswith('B'): return val
    raise ValueError("bad size")

def semantic_checks(cfg: Dict[str, Any]) -> None:
    # Cross-field constraints
    comp = size_to_bytes(cfg["bus"]["compression_threshold"])
    maxp = size_to_bytes(cfg["bus"]["max_payload_size"])
    assert comp < maxp, "bus.compression_threshold must be < bus.max_payload_size"

    dd = cfg["oms"]["risk"]["max_drawdown_halt_bp"]
    assert 50 <= dd <= 1000, "oms.risk.max_drawdown_halt_bp must be in [50,1000]"

    if cfg["bus"]["env"] == "prod":
        delay = duration_to_ms(cfg["oms"]["throt"]["min_inter_order_delay"])
        assert delay >= 5, "prod: oms.throt.min_inter_order_delay must be >= 5ms"

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
