import os, yaml
from ampy_config.layering import build_effective_config

SCHEMA = "schema/ampy-config.schema.json"
DEFAULTS = "config/defaults.yaml"
PROFILE_DEV = "examples/dev.yaml"

def test_effective_config_precedence(tmp_path, monkeypatch):
    # Prepare a runtime overlay in temp
    rt = tmp_path / "overrides.yaml"
    rt.write_text(yaml.safe_dump({
        "oms": {"risk": {"max_order_notional_usd": 70000}},
        "feature_flags": {"use_new_ensemble": {"type": "bool", "value": False}},
    }))

    cfg, prov = build_effective_config(
        schema_path=SCHEMA,
        defaults_path=DEFAULTS,
        profile_yaml=PROFILE_DEV,
        overlays=[],
        service_overrides=[],
        env_allowlist_path="env_allowlist.txt",
        env_file=None,
        runtime_overrides_path=str(rt),
    )

    assert cfg["oms"]["risk"]["max_order_notional_usd"] == 70000
    assert prov["oms.risk.max_order_notional_usd"].startswith("runtime:")

def test_semantic_guardrails_fail(tmp_path):
    # contrive a too-large compression threshold vs max payload
    bad_defaults = tmp_path / "defaults.yaml"
    bad_defaults.write_text(yaml.safe_dump({
        "bus": {
            "env": "dev",
            "cluster": "us-east-1/a",
            "transport": "nats",
            "topic_prefix": "ampy/dev",
            "compression_threshold": "2MiB",
            "max_payload_size": "1MiB",
        },
        "oms": {"risk": {"max_drawdown_halt_bp": 300}},
        "ml": {"ensemble": {"min_models": 1, "max_models": 2}},
        "broker": {"alpaca": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}]},
    }))

    # Create a minimal profile that doesn't override bus settings
    minimal_profile = tmp_path / "minimal_profile.yaml"
    minimal_profile.write_text(yaml.safe_dump({
        "ingest": {"yfinance": {"enabled": True}, "tiingo": {"enabled": False}, "databento": {"enabled": False}, "marketbeat": {"enabled": True}},
        "warehouse": {"format": "parquet", "path": "s3://test/", "write_mode": "append", "compression": "zstd"},
        "ml": {"model_server": {"inference_timeout": "300ms", "max_batch": 64, "model_registry": "s3://test/"}, "ensemble": {"strategy": "rank_weighted", "min_models": 1, "max_models": 2}},
        "oms": {"risk": {"max_drawdown_halt_bp": 300}, "fail_policy": "fail_shut"},
        "broker": {"alpaca": {"enabled": False}, "ibkr": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}], "pairs": ["USD/JPY"], "cache_ttl": "2s"},
        "feature_flags": {},
        "metrics": {"exporter": "prom", "port": 9464},
        "logging": {"level": "debug"},
        "tracing": {"enabled": True},
        "security": {"tls_required": False, "pii_policy": "forbid"},
    }))

    try:
        build_effective_config(
            schema_path=SCHEMA,
            defaults_path=str(bad_defaults),
            profile_yaml=str(minimal_profile),
            overlays=[], service_overrides=[],
            env_allowlist_path="env_allowlist.txt",
            env_file=None,
            runtime_overrides_path=None,
        )
        assert False, "Expected semantic assertion to trigger"
    except AssertionError as e:
        assert "compression_threshold" in str(e)

def test_semantic_validation_drawdown_bp(tmp_path):
    """Test semantic validation for max_drawdown_halt_bp range"""
    bad_defaults = tmp_path / "defaults.yaml"
    bad_defaults.write_text(yaml.safe_dump({
        "bus": {"env": "dev", "cluster": "us-east-1/a", "transport": "nats", "topic_prefix": "ampy/dev", "compression_threshold": "128KiB", "max_payload_size": "1MiB"},
        "oms": {"risk": {"max_drawdown_halt_bp": 25}},  # Too low
        "ml": {"ensemble": {"min_models": 1, "max_models": 2}},
        "broker": {"alpaca": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}]},
    }))

    minimal_profile = tmp_path / "minimal_profile.yaml"
    minimal_profile.write_text(yaml.safe_dump({
        "ingest": {"yfinance": {"enabled": True}, "tiingo": {"enabled": False}, "databento": {"enabled": False}, "marketbeat": {"enabled": True}},
        "warehouse": {"format": "parquet", "path": "s3://test/", "write_mode": "append", "compression": "zstd"},
        "ml": {"model_server": {"inference_timeout": "300ms", "max_batch": 64, "model_registry": "s3://test/"}, "ensemble": {"strategy": "rank_weighted", "min_models": 1, "max_models": 2}},
        "oms": {"risk": {"max_drawdown_halt_bp": 25}, "fail_policy": "fail_shut"},
        "broker": {"alpaca": {"enabled": False}, "ibkr": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}], "pairs": ["USD/JPY"], "cache_ttl": "2s"},
        "feature_flags": {},
        "metrics": {"exporter": "prom", "port": 9464},
        "logging": {"level": "debug"},
        "tracing": {"enabled": True},
        "security": {"tls_required": False, "pii_policy": "forbid"},
    }))

    try:
        build_effective_config(
            schema_path=SCHEMA,
            defaults_path=str(bad_defaults),
            profile_yaml=str(minimal_profile),
            overlays=[], service_overrides=[],
            env_allowlist_path="env_allowlist.txt",
            env_file=None,
            runtime_overrides_path=None,
        )
        assert False, "Expected semantic assertion to trigger"
    except AssertionError as e:
        assert "max_drawdown_halt_bp" in str(e)
        assert "50" in str(e) and "1000" in str(e)

def test_semantic_validation_ensemble_models(tmp_path):
    """Test semantic validation for ensemble min_models <= max_models"""
    bad_defaults = tmp_path / "defaults.yaml"
    bad_defaults.write_text(yaml.safe_dump({
        "bus": {"env": "dev", "cluster": "us-east-1/a", "transport": "nats", "topic_prefix": "ampy/dev", "compression_threshold": "128KiB", "max_payload_size": "1MiB"},
        "oms": {"risk": {"max_drawdown_halt_bp": 300}},
        "ml": {"ensemble": {"min_models": 5, "max_models": 2}},  # min > max
        "broker": {"alpaca": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}]},
    }))

    minimal_profile = tmp_path / "minimal_profile.yaml"
    minimal_profile.write_text(yaml.safe_dump({
        "ingest": {"yfinance": {"enabled": True}, "tiingo": {"enabled": False}, "databento": {"enabled": False}, "marketbeat": {"enabled": True}},
        "warehouse": {"format": "parquet", "path": "s3://test/", "write_mode": "append", "compression": "zstd"},
        "ml": {"model_server": {"inference_timeout": "300ms", "max_batch": 64, "model_registry": "s3://test/"}, "ensemble": {"strategy": "rank_weighted", "min_models": 5, "max_models": 2}},
        "oms": {"risk": {"max_drawdown_halt_bp": 300}, "fail_policy": "fail_shut"},
        "broker": {"alpaca": {"enabled": False}, "ibkr": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}], "pairs": ["USD/JPY"], "cache_ttl": "2s"},
        "feature_flags": {},
        "metrics": {"exporter": "prom", "port": 9464},
        "logging": {"level": "debug"},
        "tracing": {"enabled": True},
        "security": {"tls_required": False, "pii_policy": "forbid"},
    }))

    try:
        build_effective_config(
            schema_path=SCHEMA,
            defaults_path=str(bad_defaults),
            profile_yaml=str(minimal_profile),
            overlays=[], service_overrides=[],
            env_allowlist_path="env_allowlist.txt",
            env_file=None,
            runtime_overrides_path=None,
        )
        assert False, "Expected semantic assertion to trigger"
    except AssertionError as e:
        assert "min_models" in str(e) and "max_models" in str(e)

def test_semantic_validation_fx_priorities(tmp_path):
    """Test semantic validation for unique FX provider priorities"""
    bad_defaults = tmp_path / "defaults.yaml"
    bad_defaults.write_text(yaml.safe_dump({
        "bus": {"env": "dev", "cluster": "us-east-1/a", "transport": "nats", "topic_prefix": "ampy/dev", "compression_threshold": "128KiB", "max_payload_size": "1MiB"},
        "oms": {"risk": {"max_drawdown_halt_bp": 300}},
        "ml": {"ensemble": {"min_models": 1, "max_models": 2}},
        "broker": {"alpaca": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}, {"name": "b", "api_key": "secret://vault/y#k", "priority": 1}]},  # Duplicate priority
    }))

    minimal_profile = tmp_path / "minimal_profile.yaml"
    minimal_profile.write_text(yaml.safe_dump({
        "ingest": {"yfinance": {"enabled": True}, "tiingo": {"enabled": False}, "databento": {"enabled": False}, "marketbeat": {"enabled": True}},
        "warehouse": {"format": "parquet", "path": "s3://test/", "write_mode": "append", "compression": "zstd"},
        "ml": {"model_server": {"inference_timeout": "300ms", "max_batch": 64, "model_registry": "s3://test/"}, "ensemble": {"strategy": "rank_weighted", "min_models": 1, "max_models": 2}},
        "oms": {"risk": {"max_drawdown_halt_bp": 300}, "fail_policy": "fail_shut"},
        "broker": {"alpaca": {"enabled": False}, "ibkr": {"enabled": False}},
        "fx": {"providers": [{"name": "a", "api_key": "secret://vault/x#k", "priority": 1}, {"name": "b", "api_key": "secret://vault/y#k", "priority": 1}], "pairs": ["USD/JPY"], "cache_ttl": "2s"},
        "feature_flags": {},
        "metrics": {"exporter": "prom", "port": 9464},
        "logging": {"level": "debug"},
        "tracing": {"enabled": True},
        "security": {"tls_required": False, "pii_policy": "forbid"},
    }))

    try:
        build_effective_config(
            schema_path=SCHEMA,
            defaults_path=str(bad_defaults),
            profile_yaml=str(minimal_profile),
            overlays=[], service_overrides=[],
            env_allowlist_path="env_allowlist.txt",
            env_file=None,
            runtime_overrides_path=None,
        )
        assert False, "Expected semantic assertion to trigger"
    except AssertionError as e:
        assert "priorities must be unique" in str(e)
