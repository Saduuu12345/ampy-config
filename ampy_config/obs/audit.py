# ampy_config/obs/audit.py
from __future__ import annotations
import os, json, time, pathlib
from typing import Any, Dict, Optional

SECRET_PREFIXES = ("secret://", "aws-sm://", "gcp-sm://")

def _redact_val(v: Any) -> Any:
    if isinstance(v, str) and (v.startswith(SECRET_PREFIXES) or "secret" in v.lower() or "api_key" in v.lower()):
        return "***"
    return v

def _flatten(d: Dict[str, Any], prefix=""):
    out = {}
    for k, v in (d or {}).items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, path))
        else:
            out[path] = v
    return out

def compute_overlay_diff(overlay: Dict[str, Any]) -> Dict[str, Any]:
    # For audit, we log "set" for every provided overlay leaf (secrets redacted)
    flat = _flatten(overlay or {})
    return {k: _redact_val(v) for k, v in flat.items()}

def write_audit(record: Dict[str, Any], file_path: Optional[str] = None) -> None:
    p = pathlib.Path(file_path or os.environ.get("AMPY_CONFIG_AUDIT_FILE", "audit/log.jsonl"))
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
