from __future__ import annotations
import os, re, json, time, threading, pathlib
from typing import Dict, Tuple, Optional, List, Callable

# -------- parsing

REF_RE = re.compile(r'^(?P<scheme>[a-z0-9\-]+)://(?P<body>.+)$')

def parse_ref(ref: str) -> Tuple[str, str]:
    m = REF_RE.match(ref)
    if not m:
        raise RuntimeError(f"Invalid secret ref: {ref!r}")
    return m.group("scheme"), m.group("body")

# -------- cache

class SecretsCache:
    def __init__(self, ttl_ms: int = 120_000):
        self.ttl_ms = ttl_ms
        self._lock = threading.Lock()
        self._data: Dict[str, Tuple[str, float]] = {}  # ref -> (value, expires_at_ms)

    def get(self, ref: str) -> Optional[str]:
        now = time.time() * 1000
        with self._lock:
            entry = self._data.get(ref)
            if not entry: return None
            val, exp = entry
            if now >= exp:
                del self._data[ref]
                return None
            return val

    def put(self, ref: str, value: str):
        with self._lock:
            self._data[ref] = (value, time.time() * 1000 + self.ttl_ms)

    def invalidate(self, ref: str):
        with self._lock:
            self._data.pop(ref, None)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"items": len(self._data), "ttl_ms": self.ttl_ms}

# -------- dev/local resolver (file-backed)

class LocalFileResolver:
    scheme = "local"  # not used in refs; enabled by flag in manager

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("AMPY_CONFIG_LOCAL_SECRETS", ".secrets.local.json")

    def resolve(self, ref: str) -> str:
        p = pathlib.Path(self.path)
        if not p.exists():
            raise RuntimeError(f"Local secrets file not found: {self.path}")
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            raise RuntimeError(f"Failed to read local secrets {self.path}: {e}")
        if ref not in data:
            raise RuntimeError(f"Secret not found in local secrets file: {ref}")
        return str(data[ref])

# -------- vault resolver (lazy hvac)

class VaultResolver:
    scheme = "secret"  # refs like secret://vault/path#key

    def __init__(self):
        self._client = None
        self._err = None

    def _ensure(self):
        if self._client or self._err:
            return
        try:
            import hvac  # type: ignore
            addr = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
            token = os.environ.get("VAULT_TOKEN")
            if not token:
                self._err = "VAULT_TOKEN not set"
                return
            self._client = hvac.Client(url=addr, token=token)
        except Exception as e:
            self._err = f"hvac not available/init failed: {e}"

    def resolve(self, ref: str) -> str:
        self._ensure()
        if self._client is None:
            raise RuntimeError(self._err or "Vault client unavailable")
        # secret://vault/path#key
        body = ref.split("://", 1)[1]
        if not body.startswith("vault/"):
            raise RuntimeError(f"Vault refs must start with 'vault/': {ref}")
        path_key = body[len("vault/"):]
        if "#" not in path_key:
            raise RuntimeError(f"Vault ref must include '#key': {ref}")
        path, key = path_key.split("#", 1)
        # Try KV v2 first, then raw
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(path=path)
            data = resp["data"]["data"]
            if key not in data:
                raise KeyError(key)
            return str(data[key])
        except Exception:
            resp = self._client.read(path)
            if not resp or "data" not in resp or key not in resp["data"]:
                raise RuntimeError(f"Vault secret not found: path={path} key={key}")
            return str(resp["data"][key])

# -------- aws sm resolver (lazy boto3, fast-fail)

class AwsSMResolver:
    scheme = "aws-sm"  # aws-sm://NAME?versionStage=AWSCURRENT

    def __init__(self):
        self._client = None
        self._err = None

    def _ensure(self):
        if self._client or self._err:
            return
        # Avoid IMDS probe hangs on laptops/CI
        os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
        try:
            import boto3  # type: ignore
            from botocore.config import Config as BotoConfig  # type: ignore
            region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
            cfg = BotoConfig(connect_timeout=2, read_timeout=2, retries={'max_attempts': 2})
            self._client = boto3.client("secretsmanager", region_name=region, config=cfg)
        except Exception as e:
            self._err = f"AWS SM init failed: {e}"

    def resolve(self, ref: str) -> str:
        self._ensure()
        if self._client is None:
            raise RuntimeError(self._err or "AWS SM client unavailable")
        body = ref.split("://", 1)[1]
        name, _, query = body.partition("?")
        stage = "AWSCURRENT"
        if query:
            for kv in query.split("&"):
                k, _, v = kv.partition("=")
                if k == "versionStage" and v:
                    stage = v
        try:
            resp = self._client.get_secret_value(SecretId=name, VersionStage=stage)
            if "SecretString" in resp:
                return resp["SecretString"]
            return resp["SecretBinary"].decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"AWS SM error for {name}: {e}")

# -------- gcp secret manager resolver (lazy client)

class GcpSMResolver:
    scheme = "gcp-sm"  # gcp-sm://projects/ID/secrets/NAME/versions/latest

    def __init__(self):
        self._client = None
        self._err = None

    def _ensure(self):
        if self._client or self._err:
            return
        try:
            from google.cloud import secretmanager  # type: ignore
            self._client = secretmanager.SecretManagerServiceClient()
        except Exception as e:
            self._err = f"GCP SM init failed (credentials or lib missing): {e}"

    def resolve(self, ref: str) -> str:
        self._ensure()
        if self._client is None:
            raise RuntimeError(self._err or "GCP SM client unavailable")
        name = ref.split("://", 1)[1]
        try:
            resp = self._client.access_secret_version(request={"name": name})
            return resp.payload.data.decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"GCP SM error for {name}: {e}")

# -------- manager

REDACTION = "***"

class SecretsManager:
    """
    Lazy, opt-in resolvers. Control which backends are enabled with:
      AMPY_CONFIG_SECRET_RESOLVERS="local,secret,aws-sm,gcp-sm"
    For dev, use: AMPY_CONFIG_SECRET_RESOLVERS="local"
    """
    def __init__(
        self,
        ttl_ms: Optional[int] = None,
        enable_local_fallback: bool = True,
        local_path: Optional[str] = None,
        resolvers: Optional[List[str]] = None,
    ):
        ttl = ttl_ms if ttl_ms is not None else int(os.environ.get("AMPY_CONFIG_SECRET_TTL_MS", "120000"))
        self.cache = SecretsCache(ttl_ms=ttl)
        self.local = LocalFileResolver(local_path) if enable_local_fallback else None

        wanted = resolvers or os.environ.get("AMPY_CONFIG_SECRET_RESOLVERS", "local,secret,aws-sm,gcp-sm").split(",")
        wanted = [w.strip() for w in wanted if w.strip()]

        self._factories: Dict[str, Callable[[], object]] = {}
        for name in wanted:
            if name == "secret":   self._factories["secret"] = VaultResolver
            elif name == "aws-sm": self._factories["aws-sm"] = AwsSMResolver
            elif name == "gcp-sm": self._factories["gcp-sm"] = GcpSMResolver
            elif name == "local":  pass  # handled as fallback
        self._instances: Dict[str, object] = {}

    def _get_resolver(self, scheme: str):
        if scheme in self._instances:
            return self._instances[scheme]
        fac = self._factories.get(scheme)
        if not fac:
            return None
        inst = fac()
        self._instances[scheme] = inst
        return inst

    def resolve(self, ref: str, use_cache: bool = True) -> str:
        if use_cache:
            cached = self.cache.get(ref)
            if cached is not None:
                return cached

        scheme, _ = parse_ref(ref)
        errors: List[str] = []

        # Try scheme-matched resolver only
        r = self._get_resolver(scheme)
        if r:
            try:
                val = r.resolve(ref)  # type: ignore[attr-defined]
                self.cache.put(ref, val)
                return val
            except Exception as e:
                errors.append(f"{scheme}: {e}")

        # Dev/local fallback
        if self.local:
            try:
                val = self.local.resolve(ref)
                self.cache.put(ref, val)
                return val
            except Exception as e:
                errors.append(f"local: {e}")

        raise RuntimeError("Failed to resolve secret:\n  " + "\n  ".join(errors))

    def invalidate(self, ref: str):
        self.cache.invalidate(ref)

    def redact(self, value: str) -> str:
        return REDACTION

def walk_and_transform(obj, is_secret: Callable[[str], bool], transform: Callable[[str], str]):
    if isinstance(obj, dict):
        return {k: walk_and_transform(v, is_secret, transform) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [walk_and_transform(x, is_secret, transform) for x in obj]
    elif isinstance(obj, str) and is_secret(obj):
        return transform(obj)
    else:
        return obj

SECRET_PREFIXES = ("secret://", "aws-sm://", "gcp-sm://")

def looks_like_secret_ref(s: str) -> bool:
    return isinstance(s, str) and s.startswith(SECRET_PREFIXES)
