from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional

# Topics: {prefix}/control/v1/{...}
def subjects(topic_prefix: str) -> Dict[str, str]:
    # ampy-bus/NATS subjects are dot-delimited; normalize any "/" to "."
    pfx = (topic_prefix or "").replace("/", ".")
    base = f"{pfx}.control.v1"
    return {
        "preview": f"{base}.config_preview",
        "apply": f"{base}.config_apply",
        "applied": f"{base}.config_applied",
        "secret_rotated": f"{base}.secret_rotated",
    }


@dataclass
class ConfigPreviewRequested:
    targets: List[str]               # dotted keys to change
    candidate: Dict[str, Any]        # overlay fragment (YAML->dict)
    expires_at: str                  # ISO-8601 Z
    reason: Optional[str] = None
    run_id: Optional[str] = None
    producer: Optional[str] = None

    def to_dict(self): return asdict(self)

@dataclass
class ConfigApply:
    change_id: str
    canary_percent: int = 0          # 0..100
    canary_duration: str = "0s"      # e.g., "10m"
    global_deadline: Optional[str] = None
    overlay: Optional[Dict[str, Any]] = None  # same shape as preview.candidate
    run_id: Optional[str] = None
    producer: Optional[str] = None

    def to_dict(self): return asdict(self)

@dataclass
class ConfigApplied:
    change_id: str
    status: str                      # "ok" | "rejected"
    effective_at: str                # ISO-8601 Z
    errors: Optional[List[str]] = None
    service: Optional[str] = None
    run_id: Optional[str] = None

    def to_dict(self): return asdict(self)

@dataclass
class SecretRotated:
    reference: str                   # secret ref string
    rotated_at: str                  # ISO-8601 Z
    rollout: str = "staged"          # "staged" | "global"
    deadline: Optional[str] = None
    producer: Optional[str] = None

    def to_dict(self): return asdict(self)
