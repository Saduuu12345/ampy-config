import json, os, tempfile
from ampy_config.secrets.registry import SecretsManager

def test_local_secret_resolution():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, ".secrets.local.json")
        data = {"secret://vault/tiingo#token": "DEV_TOKEN"}
        with open(p, "w") as f: json.dump(data, f)

        sm = SecretsManager(ttl_ms=10_000, enable_local_fallback=True, local_path=p)
        assert sm.resolve("secret://vault/tiingo#token") == "DEV_TOKEN"

        # cache invalidate should force a re-read
        sm.invalidate("secret://vault/tiingo#token")
        assert sm.resolve("secret://vault/tiingo#token") == "DEV_TOKEN"
