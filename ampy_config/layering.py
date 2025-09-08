from __future__ import annotations
import os, re, json, pathlib
from typing import Any, Dict, Tuple, Iterable
import yaml

# ---------- helpers

def load_yaml(path: str | pathlib.Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}

def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any], provenance: Dict[str, str], source: str, path: str = "") -> Dict[str, Any]:
    for k, v in (overlay or {}).items():
        p = f"{path}.{k}" if path else k
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v, provenance, source, p)
        else:
            base[k] = v
            provenance[p] = source
    return base

def dotted_set(d: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

def dotted_get(d: Dict[str, Any], dotted: str) -> Any:
    cur = d
    for p in dotted.split("."):
        cur = cur[p]
    return cur

def parse_env_value(raw: str) -> Any:
    s = raw.strip()
    if s.lower() in ("true","false"):
        return s.lower() == "true"
    if re.fullmatch(r"-?\d+", s):
        try: return int(s)
        except: pass
    if re.fullmatch(r"-?\d+\.\d+", s):
        try: return float(s)
        except: pass
    if s.startswith("[") or s.startswith("{"):
        try: return yaml.safe_load(s)
        except: pass
    return s

def dotted_to_env(dotted: str) -> str:
    return dotted.upper().replace(".", "_")

def load_env_file(env_file: str | None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not env_file: return env
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "=" not in line: continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

# ---------- public API

def build_effective_config(
    schema_path: str,
    defaults_path: str,
    profile_yaml: str,
    overlays: Iterable[str] = (),
    service_overrides: Iterable[str] = (),
    env_allowlist_path: str | None = None,
    env_file: str | None = None,
    runtime_overrides_path: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Returns (effective_config, provenance_map)
    provenance_map: dotted_key -> 'layer:detail' (e.g., 'profile:examples/prod.yaml')
    """
    cfg: Dict[str, Any] = {}
    prov: Dict[str, str] = {}

    # 1) defaults
    deep_merge(cfg, load_yaml(defaults_path), prov, f"defaults:{defaults_path}")

    # 2) profile
    deep_merge(cfg, load_yaml(profile_yaml), prov, f"profile:{profile_yaml}")

    # 3) overlays (region/cluster)
    for o in overlays:
        deep_merge(cfg, load_yaml(o), prov, f"overlay:{o}")

    # 4) service overrides
    for s in service_overrides:
        deep_merge(cfg, load_yaml(s), prov, f"service_override:{s}")

    # 5) ENV (allow-listed)
    if env_allowlist_path:
        allow = [ln.strip() for ln in open(env_allowlist_path, "r") if ln.strip() and not ln.startswith("#")]
        env = dict(os.environ)
        env.update(load_env_file(env_file))
        for dotted in allow:
            env_key = dotted_to_env(dotted)
            # accept either EXACT env name or raw dotted (rare) if present in env file
            if env_key in env:
                val = parse_env_value(env[env_key])
                dotted_set(cfg, dotted, val)
                prov[dotted] = f"env:{env_key}"
            elif dotted in env:
                val = parse_env_value(env[dotted])
                dotted_set(cfg, dotted, val)
                prov[dotted] = f"env:{dotted}"

    # 6) runtime overrides
    if runtime_overrides_path:
        deep_merge(cfg, load_yaml(runtime_overrides_path), prov, f"runtime:{runtime_overrides_path}")

    # 7) validate (schema + semantics)
    validate_config(schema_path, cfg)

    return cfg, prov

# ---- validation (mirror tools/validate.py key checks)

import json, jsonschema

SIZE_UNITS = {"TiB": 1024**4, "GiB": 1024**3, "MiB": 1024**2, "KiB": 1024, "B": 1}
DUR_UNITS  = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}

def size_to_bytes(s: str) -> int:
    m = re.fullmatch(r'(\d+)(TiB|GiB|MiB|KiB|B)', s)
    if not m: raise ValueError(f"bad size: {s!r}")
    n, u = m.groups(); return int(n) * SIZE_UNITS[u]

def duration_to_ms(s: str) -> int:
    m = re.fullmatch(r'(\d+)(ms|s|m|h|d)', s)
    if not m: raise ValueError(f"bad duration: {s!r}")
    n, u = m.groups(); return int(n) * DUR_UNITS[u]

def validate_config(schema_path: str, data: Dict[str, Any]) -> None:
    with open(schema_path, "r") as f:
        schema = json.load(f)
    jsonschema.Draft202012Validator(schema).validate(data)

    # semantic checks (subset of tools/validate.py, kept in-sync)
    comp = size_to_bytes(data["bus"]["compression_threshold"])
    maxp = size_to_bytes(data["bus"]["max_payload_size"])
    assert comp < maxp, f"bus.compression_threshold ({data['bus']['compression_threshold']} = {comp} bytes) must be < bus.max_payload_size ({data['bus']['max_payload_size']} = {maxp} bytes)"

    dd = data["oms"]["risk"]["max_drawdown_halt_bp"]
    assert 50 <= dd <= 1000, f"oms.risk.max_drawdown_halt_bp ({dd}) must be in [50,1000] basis points"

    if data["bus"]["env"] == "prod":
        delay = duration_to_ms(data["oms"]["throt"]["min_inter_order_delay"])
        assert delay >= 5, f"prod: oms.throt.min_inter_order_delay ({data['oms']['throt']['min_inter_order_delay']} = {delay}ms) must be >= 5ms"

    # ensemble sanity
    ens = data["ml"]["ensemble"]
    assert ens["min_models"] <= ens["max_models"], f"ml.ensemble.min_models ({ens['min_models']}) must be <= max_models ({ens['max_models']})"

    # feature_flags type/value coherence
    for name, flag in (data.get("feature_flags") or {}).items():
        t = flag.get("type")
        v = flag.get("value")
        if t == "bool":
            assert isinstance(v, bool), f"feature_flags.{name}.value ({v}) must be boolean, got {type(v).__name__}"
        elif t == "int":
            assert isinstance(v, int), f"feature_flags.{name}.value ({v}) must be integer, got {type(v).__name__}"
        elif t == "enum":
            allowed = flag.get("allowed") or []
            assert allowed, f"feature_flags.{name}.allowed must be set for enum type"
            assert v in allowed, f"feature_flags.{name}.value ({v}) must be one of {allowed}"

    # alpaca enabled requires keys
    alp = data["broker"]["alpaca"]
    if alp.get("enabled"):
        for req in ("base_url","key_id","secret_key"):
            assert alp.get(req), f"broker.alpaca.{req} is required when alpaca.enabled=true"

    # fx priorities unique
    prios = [p["priority"] for p in data["fx"]["providers"]]
    assert len(prios) == len(set(prios)), f"fx.providers priorities must be unique, found duplicates: {[p for p in prios if prios.count(p) > 1]}"
