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

# -------- vault resolver (optional hvac)

class VaultResolver:
    scheme = "secret"  # refs like secret://vault/path#key

    def __init__(self):
        try:
            import hvac  # type: ignore
        except Exception as e:
            self._err = f"hvac not installed ({e}); pip install hvac"
            self._client = None
            return
        self._err = None
        addr = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        token = os.environ.get("VAULT_TOKEN")
        if not token:
            self._err = "VAULT_TOKEN not set"
            self._client = None
            return
        self._client = hvac.Client(url=addr, token=token)

    def resolve(self, ref: str) -> str:
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
            # fallback raw (kv v1)
            resp = self._client.read(path)
            if not resp or "data" not in resp or key not in resp["data"]:
                raise RuntimeError(f"Vault secret not found: path={path} key={key}")
            return str(resp["data"][key])

# -------- aws sm resolver (optional boto3)

class AwsSMResolver:
    scheme = "aws-sm"  # aws-sm://NAME?versionStage=AWSCURRENT

    def __init__(self):
        try:
            import boto3  # type: ignore
        except Exception as e:
            self._err = f"boto3 not installed ({e}); pip install boto3"
            self._client = None
            return
        try:
            self._client = boto3.client("secretsmanager")
            self._err = None
        except Exception as e:
            self._err = f"AWS credentials not configured ({e}); set AWS_DEFAULT_REGION and credentials"
            self._client = None

    def resolve(self, ref: str) -> str:
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
            # binary fallback
            return resp["SecretBinary"].decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"AWS SM error for {name}: {e}")

# -------- gcp secret manager resolver (optional google-cloud-secret-manager)

class GcpSMResolver:
    scheme = "gcp-sm"  # gcp-sm://projects/ID/secrets/NAME/versions/latest

    def __init__(self):
        try:
            from google.cloud import secretmanager  # type: ignore
        except Exception as e:
            self._err = f"google-cloud-secret-manager not installed ({e}); pip install google-cloud-secret-manager"
            self._client = None
            return
        try:
            from google.cloud import secretmanager
            self._client = secretmanager.SecretManagerServiceClient()
            self._err = None
        except Exception as e:
            self._err = f"GCP credentials not configured ({e}); set GOOGLE_APPLICATION_CREDENTIALS"
            self._client = None

    def resolve(self, ref: str) -> str:
        if self._client is None:
            raise RuntimeError(self._err or "GCP SM client unavailable")
        body = ref.split("://", 1)[1]
        name = body  # already full resource path after scheme
        try:
            resp = self._client.access_secret_version(request={"name": name})
            return resp.payload.data.decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"GCP SM error for {name}: {e}")

# -------- manager

REDACTION = "***"

class SecretsManager:
    def __init__(self, ttl_ms: Optional[int] = None, enable_local_fallback: bool = True, local_path: Optional[str] = None):
        ttl = ttl_ms if ttl_ms is not None else int(os.environ.get("AMPY_CONFIG_SECRET_TTL_MS", "120000"))
        self.cache = SecretsCache(ttl_ms=ttl)
        self.local = LocalFileResolver(local_path) if enable_local_fallback else None
        # Order matters: cache -> cloud providers -> local (dev)
        self._resolvers = [
            VaultResolver(),
            AwsSMResolver(),
            GcpSMResolver(),
        ]

    def resolve(self, ref: str, use_cache: bool = True) -> str:
        if use_cache:
            cached = self.cache.get(ref)
            if cached is not None:
                return cached
        scheme, _ = parse_ref(ref)
        errors: List[str] = []

        # try scheme-matched resolver first
        for r in self._resolvers:
            if getattr(r, "scheme", None) == scheme:
                try:
                    val = r.resolve(ref)
                    self.cache.put(ref, val)
                    return val
                except Exception as e:
                    errors.append(f"{scheme}: {e}")
                    break
        # scheme not matched or failed → try all resolvers as fallback
        for r in self._resolvers:
            try:
                val = r.resolve(ref)
                self.cache.put(ref, val)
                return val
            except Exception as e:
                errors.append(f"{getattr(r,'scheme','?')}: {e}")

        # dev/local fallback
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

    # utilities for config hydration (use with caution)
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
