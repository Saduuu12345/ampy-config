# ampy_config/obs/logging.py
from __future__ import annotations
import logging, json, sys, fnmatch
from typing import Any, Dict, List

class JsonRedactingFormatter(logging.Formatter):
    def __init__(self, redact_patterns: List[str] | None = None):
        super().__init__()
        self.redact = redact_patterns or []

    def _apply_redact(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: ("***" if self._match(k) else self._apply_redact(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._apply_redact(v) for v in obj]
        return obj

    def _match(self, key: str) -> bool:
        for pat in self.redact:
            if fnmatch.fnmatch(key, pat):
                return True
        return False

    def format(self, record: logging.LogRecord) -> str:
        base = {
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            base["extra"] = self._apply_redact(record.extra)
        return json.dumps(base, separators=(",", ":"))

def setup_logging(level: str = "info", json_mode: bool = True, redact_patterns: List[str] | None = None) -> None:
    logging.captureWarnings(True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler(sys.stdout)
    if json_mode:
        h.setFormatter(JsonRedactingFormatter(redact_patterns=redact_patterns or []))
    else:
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(h)

def log_json(level: str, msg: str, **extra):
    lg = logging.getLogger("ampy-config")
    rec = {"extra": extra} if extra else {}
    getattr(lg, level, lg.info)(msg, extra=rec)
