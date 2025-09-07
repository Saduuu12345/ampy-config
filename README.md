# ampy-config — Typed Configuration & Secrets Façade (Open Source)

> **Mission:** Provide a **single, consistent, transport‑agnostic configuration layer** for all AmpyFin services. `ampy-config` defines how configuration is **declared, layered, validated, resolved (incl. secrets), reloaded, audited, and observed** across environments—so modules built with **`ampy-proto`** (payload contracts) and **`ampy-bus`** (messaging rules) can run safely and predictably without per‑service, ad‑hoc config.

This README is **LLM‑ready**: it specifies what to build and how it should behave, without prescribing repository structure or leaking implementation code. It includes **rich, concrete examples** to guide design decisions and validation logic.

---

## 0) Status & Scope

- **Status:** Spec complete / implementation unstarted.
- **Artifact:** Library (Go + Python façade; optional adapters for secret stores).
- **Open Source:** Yes (permissive license preferred).
- **Integrations:** `ampy-proto` for typed envelopes; `ampy-bus` for control‑plane events (preview/apply/confirm), plus adapters for secret stores (Vault, AWS Secrets Manager / KMS, Google Secret Manager).

**Out of scope (here):** Broker‑specific SDKs, message broker clients, concrete repo layout, infra code, or product‑specific business logic.

---

## 1) Problem Statement (What this solves)

1. **Config sprawl & drift** — Each service invents its own flags/ENV layout; values diverge across `dev`/`paper`/`prod`.
2. **Secrets hygiene** — Keys/tokens leak via logs or “.env” files; rotation is ad‑hoc and risky.
3. **Reload inconsistency** — Some services require restarts; others ignore changes; no audit of who changed what, when, and why.
4. **Non‑reproducibility** — Incidents cannot be reconstructed because the **effective config** at time *T* isn’t recorded.
5. **Safety gaps** — Risk‑critical knobs (OMS limits) can be mis‑set without guardrails or staged rollout.

**Thesis:** A typed, layered, and observable config façade prevents class‑wide incidents and accelerates safe delivery.

---

## 2) Design Goals (and Non‑Goals)

### Goals
- **Typed, validated config**: Every key has type, units, constraints, default, and safety classification.
- **Layered precedence**: Defaults → environment profile → region/cluster overlay → service override → ENV → runtime overrides.
- **Secrets separation**: Indirection to secret stores, redaction in logs/metrics, TTL‑based caching, and rotation.
- **Runtime reloads**: Transactional preview/apply/confirm flow via `ampy-bus` control topics; canary rollouts.
- **Auditability**: Immutable change journal linking actor, diff, validation result, rollout, and affected services.
- **Observability**: Metrics, logs, traces for load/resolve/rotate/reload outcomes.
- **Reproducibility**: Ability to materialize the exact **effective config** for a given run_id and timestamp.

### Non‑Goals
- Defining repository layout or build tooling.
- Shipping broker or cloud vendor SDKs in this module.
- Implementing business logic; `ampy-config` is purely a configuration/secret façade.

---

## 3) Relationship to `ampy-proto` and `ampy-bus`

- **`ampy-proto`**: Provides the canonical envelope and header contracts used by control‑plane events (`ConfigPreviewRequested`, `ConfigApply`, `ConfigApplied`, `SecretRotated`). `ampy-config` **describes** those payload shapes and consumes/produces them but does not define protobuf files itself.
- **`ampy-bus`**: Supplies messaging semantics (topics, headers, partitions, DLQ, tracing propagation). `ampy-config` relies on `ampy-bus` control topics to coordinate configuration preview/apply/confirm and secret rotation signals.

**Result:** Services get a uniform config API, while control‑plane changes are transported and audited through the existing bus infrastructure.

---

## 4) Responsibilities (What `ampy-config` must do)

1. **Schema Registry (conceptual)** — Defines the typed keyspace with constraints, defaults, units, and redaction policy.
2. **Layering Engine** — Computes effective view with provenance for every key.
3. **Secrets Resolver** — Resolves `secret://` references at load‑time or use‑time; caches with TTL; redacts everywhere.
4. **Reload Orchestrator** — Applies preview/apply/confirm, supports canary % and deadlines, publishes/consumes control events.
5. **Audit Writer** — Records immutable change events and diffs; links to run_id, commit, and rollout status.
6. **Observability Hooks** — Exposes metrics/logs/traces for load/resolve/rotate/reload outcomes and redactions.
7. **Safety Policies** — Enforces fail‑shut/open per domain; quarantines unknown keys; rate‑limits churn.

---

## 5) Architecture (Logical)

```
                ┌──────────────────────┐
    Defaults ──▶│                      │
   Profiles  ──▶│  Layering Engine     │──┐
 Region/Node ──▶│   (with provenance)  │  │  Effective
      ENV   ──▶│                      │  │  Config (typed)
 Runtime Ov. ─▶└──────────────────────┘  │
                                           ▼
                                    ┌───────────────┐
                                    │ Validation    │  (types, units, constraints,
                                    │ & Safety      │   redaction policies)
                                    └─────┬─────────┘
                                          │
                    Secrets refs           │ ok
    secret://..., aws-sm://..., gcp-sm://… │
                ┌───────────────┐         ▼
                │ Secrets       │   ┌─────────────┐
                │ Resolver      │◀──│  Audit      │  (immutable journal)
                └───────────────┘   └─────────────┘
                         ▲                 ▲
                         │                 │
                  SecretRotated      ConfigApply/Applied
                  (ampy-bus)         (ampy-bus control topics)
```

**Key properties**
- Every key retains **origin lineage** (which layer last set it).
- **Transactional reloads**: build candidate → validate → canary apply → confirm/rollback.
- **Strict redaction**: secrets never appear in logs/metrics/traces.

---

## 6) Conventions & Types (apply to all keys)

- **Namespacing**: `bus.*`, `ingest.*`, `warehouse.*`, `ml.*`, `oms.*`, `broker.*`, `fx.*`, `feature_flags.*`, `metrics.*`, `logging.*`, `tracing.*`, `security.*`.
- **Durations** as strings with units: `150ms`, `2s`, `5m`, `1h`.
- **Sizes** as strings with units: `512KiB`, `1MiB`, `10GB`.
- **Ratios / bps** explicit: `orders.max_reject_rate_bp=50` → 0.50%.
- **Time** is **UTC** / ISO‑8601 only.
- **Safety classification** per key: `critical`, `risky`, `safe`.
- **Redaction policy** per key: `public`, `sensitive`, `secret`.

---

## 7) Precedence & Layering

1) **Defaults** (checked into config registry)  
2) **Environment profile** (`dev` / `paper` / `prod`)  
3) **Region/cluster overlay** (e.g., `us-east-1/a`)  
4) **Service instance override** (optional)  
5) **ENV variables** (explicit mapping)  
6) **Runtime overrides** (temporary; expire or are reverted)

**Provenance:** Each key exposes its source and version (e.g., `prod.us-east-1.overlay@sha256:...`).

---

## 8) Domain Catalog & Example Keys (illustrative)

> Examples show shape/semantics only; values are placeholders. Secrets are references, not literals.

### 8.1 Bus (aligns with `ampy-bus`)
```yaml
bus:
  env: "prod"
  cluster: "us-east-1/a"
  transport: "nats"        # "kafka" | "nats" | "inproc"
  topic_prefix: "ampy/prod"
  compression_threshold: "128KiB"
  max_payload_size: "1MiB"
  headers:
    require_trace: true
    schema_strict: true
  partitions:
    bars: "symbol_mic"
    ticks: "symbol_mic"
    orders: "client_order_id"
```

### 8.2 Ingestion connectors (Databento, Tiingo, yfinance, Marketbeat/news)
```yaml
ingest:
  databento:
    enabled: true
    sdk: "cpp"
    streams:
      - dataset: "XBBO"
        symbols: ["AAPL","MSFT"]
        book_depth: 5
        heartbeat: "500ms"
  tiingo:
    enabled: false
    api_token: "secret://vault/tiingo#token"
    http_timeout: "5s"
  yfinance:
    enabled: true
    golang_client: "github.com/AmpyFin/yfinance-go@^1" # conceptual; OSS goal
    http_timeout: "5s"
    max_concurrency: 64
    rate_limit_qps: 50
    markets: ["XNYS","XNAS"]
  marketbeat:
    enabled: true
    poll_interval: "30s"
    dedupe_horizon: "3h"
```

### 8.3 Warehouse & storage
```yaml
warehouse:
  format: "parquet"
  path: "s3://ampy-warehouse/prod/"
  write_mode: "append"
  compression: "zstd"
  manifest_versioning: true
  checkpoint_interval: "1m"
```

### 8.4 ML model server & ensemble
```yaml
ml:
  model_server:
    inference_timeout: "200ms"
    max_batch: 256
    warmup_signals: true
    model_registry: "s3://ampy-models/prod/"
    allowed_models: ["hyper@*", "prag@*", "baseline@*"]
  ensemble:
    strategy: "rank_weighted"
    decay_half_life: "14d"
    min_models: 2
    max_models: 8
    guardrails:
      score_clip: [-1.0, 1.0]
      expiry_default: "1d"
```

### 8.5 OMS & execution (safety‑critical)
```yaml
oms:
  risk:
    max_notional_usd: 5000000
    max_order_notional_usd: 100000
    max_symbol_gross_exposure_usd: 2500000
    max_drawdown_halt_bp: 300
    news_halt_enabled: true
    news_halt_sources: ["marketbeat"]
  throt:
    max_orders_per_min: 900
    min_inter_order_delay: "20ms"
  clock:
    trading_calendar: "XNYS"
    enforce_session: true
  fail_policy: "fail_shut"
```

### 8.6 Broker connectors
```yaml
broker:
  alpaca:
    enabled: true
    base_url: "https://api.alpaca.markets"
    key_id: "secret://aws-sm/ALPACA_KEY#value"
    secret_key: "secret://aws-sm/ALPACA_SECRET#value"
    recv_window: "2s"
    order_timeout: "1s"
    sandbox: false
  ibkr:
    enabled: false
```

### 8.7 FX & currency normalization (incl. real‑time conversion cache)
```yaml
fx:
  providers:
    - name: "provider_a"
      api_key: "secret://vault/fx#key"
      priority: 1
    - name: "provider_b"
      api_key: "secret://vault/fx_backup#key"
      priority: 2
  cache_ttl: "2s"
  pairs: ["USD/JPY","EUR/USD","USD/KRW"]
  fallback_on_stale: true
  max_staleness: "5s"
```

### 8.8 Feature flags (typed, time‑boxed)
```yaml
feature_flags:
  enable_mbp_depth: { type: "bool", value: false }
  use_new_ensemble: { type: "bool", value: true, expires_at: "2025-12-31T23:59:59Z" }
  backtester_fast_path: { type: "enum", value: "v2", allowed: ["v1","v2"] }
```

### 8.9 Observability
```yaml
metrics:
  exporter: "otlp"
  endpoint: "https://otel.prod.ampyfin.com:4317"
  sampling_ratio: 0.25
logging:
  level: "info"
  json: true
  redact_fields: ["*.secret", "*.api_key", "broker.alpaca.secret_key"]
tracing:
  enabled: true
  propagate_traceparent: true
```

### 8.10 Security & compliance
```yaml
security:
  tls_required: true
  mutual_tls: true
  allowed_ciphers: ["TLS_AES_128_GCM_SHA256","TLS_AES_256_GCM_SHA384"]
  acls:
    - subject: "service:ampy-oms"
      allow_publish: ["ampy/prod/orders/v1/requests"]
      allow_consume: ["ampy/prod/signals/v1/*"]
    - subject: "service:broker-alpaca"
      allow_publish: ["ampy/prod/fills/v1/events"]
      allow_consume: ["ampy/prod/orders/v1/requests"]
  pii_policy: "forbid"
```

---

## 9) Secrets: Reference Grammar, Resolution, Rotation

**Reference forms**
- `secret://vault/<path>#<key>`
- `aws-sm://<name>?versionStage=AWSCURRENT`
- `gcp-sm://projects/<id>/secrets/<name>/versions/latest`

**Resolution modes**
- **Load‑time** (resolve once; cache with TTL; refresh on rotation signal).
- **Use‑time** (resolve per access; higher latency; for short‑lived creds).

**Rotation triggers**
- Secret backend event → publish `SecretRotated` on control topic.
- Scheduled rotations with staggered rollouts.

**Redaction**
- Replace values with `***` in logs/metrics; optionally log key fingerprints (non‑reversible) for correlation.

---

## 10) Runtime Reload via Control‑Plane (Preview → Apply → Confirm)

1. **Preview**: Publish `ConfigPreviewRequested` with candidate overlay, targets, and expiry.
2. **Apply**: If validation passes, publish `ConfigApply` with `change_id`, canary percent/duration, and deadline.
3. **Confirm**: Services emit `ConfigApplied` (success) or `ConfigRejected` (reasons). Automatic rollback on threshold failure.

**Abridged example (payload semantics only):**
```json
{
  "change_id": "chg_20250905_1142",
  "targets": ["oms.risk.max_order_notional_usd"],
  "candidate": {"oms":{"risk":{"max_order_notional_usd":70000}}},
  "canary": {"percent": 10, "duration": "10m"},
  "global_deadline": "2025-09-05T17:00:00Z"
}
```

---

## 11) Safety & Failure Modes

- **Fail‑shut** (critical domains: OMS risk, broker creds): invalid → refuse to start or rollback.
- **Fail‑open** (non‑critical domains: metrics sampling): continue with last‑known‑good + alert.
- **Quarantine**: Unknown/extra keys are rejected or quarantined by policy; always warn.
- **Churn circuit‑breaker**: Excess reloads halt further changes and page on‑call.

---

## 12) Reproducibility & Audit

- **Audit record**: Actor, ticket/approval ref, diffs, validation outcome, canary results, rollbacks, affected services.
- **Point‑in‑time materialization**: Given `{run_id, timestamp}`, reconstruct effective config to reproduce behavior in paper/sim.
- **Trace correlation**: Attach `trace_id` to preview/apply and per‑service reload spans.

---

## 13) Usage Examples (LLM‑oriented, no implementation code)

> These are workflows that the library must enable; they specify IO/behavior, not code.

### Example A — Effective config at startup
- Inputs: defaults + `prod` profile + `us-east-1` overlay + ENV.
- Behavior: Build effective tree with provenance; validate types/units; resolve secrets with TTL cache; expose read‑only view.

### Example B — Temporary runtime override (risk tightening)
- Inputs: `ConfigPreviewRequested` with candidate `{ oms.risk.max_order_notional_usd=70000 }`, expiry `18:00Z`.
- Behavior: Validate, canary apply (10%), then ramp to 100% if healthy; at expiry, revert to prior value.

### Example C — Secret rotation
- Inputs: `SecretRotated` for `aws-sm://ALPACA_SECRET#value`.
- Behavior: Invalidate cache; re‑resolve; atomically update consumers; publish `ConfigApplied` with affected services.

### Example D — Incident reconstruction
- Inputs: `{ run_id="run_2025-09-05T16:12Z", timestamp="2025-09-05T16:12:30Z" }`.
- Behavior: Materialize exact effective config; export as JSON/YAML for audit; link to change journal and bus message IDs.

### Example E — ENV mapping conventions
- `OMS_RISK_MAX_ORDER_NOTIONAL_USD` ↔ `oms.risk.max_order_notional_usd`
- `INGEST_YFINANCE_RATE_LIMIT_QPS` ↔ `ingest.yfinance.rate_limit_qps`
- Rules: upper‑snake; dot → underscore; numeric/string parsing with units; explicit allow‑list.

---

## 14) Validation Rules (illustrative set)

- `oms.risk.max_drawdown_halt_bp`: integer ∈ [50, 1000]. Default 300.
- `oms.throt.min_inter_order_delay`: duration ∈ [0ms, 1s]; prod min 5ms.
- `ml.model_server.inference_timeout`: duration ∈ [10ms, 2s]; must exceed network p99.
- `bus.max_payload_size`: size ∈ [64KiB, 5MiB]; require `compression_threshold < max_payload_size`.
- `broker.alpaca.base_url`: must match `^https://`.
- `feature_flags.*.type`: enum in {bool, int, enum}; optional `expires_at` ISO‑8601; expired flags revert to default.

---

## 15) Observability

- **Metrics (examples)**
  - `config_load_success_total{service}`
  - `config_load_failure_total{service,reason}`
  - `config_reload_total{service}`
  - `secret_resolve_latency_ms{backend}` histogram
  - `config_redactions_total{field}`
- **Logs**: Structured; include `change_id`, `run_id`, and diff summaries; redact secrets; include provenance.
- **Tracing**: Control events and per‑service reload spans share `trace_id` for end‑to‑end visibility.

---

## 16) Success Criteria — Checklist (Definition of Done v1)

- [ ] **Typed schema** for domains in §8 finalized (types, defaults, constraints, units, safety/redaction).
- [ ] **Layering/precedence** implemented with provenance per key.
- [ ] **Secret reference grammar** supported with load‑time and use‑time resolution + TTL caching.
- [ ] **Rotation workflow**: consumes `SecretRotated`; zero‑downtime updates; redaction verified.
- [ ] **Runtime reload**: preview/apply/confirm with canary; rollback on threshold failure.
- [ ] **Audit store**: immutable journal with actor, diffs, outcomes, run_id/timestamp linkage.
- [ ] **Observability**: metrics/logs/traces for load/resolve/rotate/reload; alerting on failures/churn.
- [ ] **Safety policies**: fail‑shut/open enforced; quarantine + warnings for unknown keys.
- [ ] **Golden configs & fuzz tests**: cover types/units/precedence and negative cases.
- [ ] **Point‑in‑time materialization** of effective config (run_id + timestamp).

---

## 17) Testing Matrix

- **Golden configs**: typical/sparse/edge for each environment.
- **Fuzzing**: durations/sizes/ratios parsers; invalid unit handling.
- **Precedence tests**: _defaults → profile → overlay → ENV → runtime_.
- **Secret tests**: mocked stores; rotation; TTL expiry; redaction.
- **Reload tests**: preview/apply/confirm happy‑path, canary, rollback; DLQ behavior via `ampy-bus`.
- **Chaos**: drop/misorder control messages; ensure idempotence and safe rollback.
- **Soak**: frequent reloads under load; memory/handle leak checks.

---

## 18) Operational Runbooks (what operators can expect)

- **Applying a runtime override**: Prepare candidate overlay, preview with expiry, canary at 10%, monitor metrics, ramp to 100%.
- **Rotating a secret**: Rotate in backend; emit `SecretRotated`; confirm services publish `ConfigApplied`; verify no plaintext appears.
- **Incident review**: Query audit by `run_id`/time; export effective config; diff against current; attach to RCA.

---

## 19) Implementation Plan (single‑track, stepwise; LLM friendly)

1. **Define the typed keyspace** (sections in §8) with constraints/defaults/units/safety/redaction.
2. **Build the layering engine** with provenance and ENV mapping rules.
3. **Implement secret reference grammar** and resolver adapters (Vault, AWS SM, GSM); choose load‑time vs use‑time policies.
4. **Wire control‑plane events** (consume/produce via `ampy-bus` topics) for preview/apply/confirm & rotation.
5. **Add observability hooks** (metrics/logs/traces) and the **audit journal**.
6. **Ship golden configs & test harness** (fuzz, chaos, soak); document failure modes and runbooks.
7. **Cut v1** once Definition of Done in §16 is satisfied.

> If external credentials are required (e.g., Vault token, AWS/GCP access for secret stores), **flag early** for ops to provision non‑prod keys.

---

## 20) Future Work (post‑v1)

- **Multi‑tenant overlays** (per‑strategy, per‑account, per‑symbol lists) with precedence guarantees.
- **UI/CLI config explorer** with provenance, diffs, and “render effective view” export.
- **Plugin resolvers** (e.g., SOPS, Azure Key Vault, 1Password Connect).
- **Policy as code** (OPA/Rego) checks for high‑risk changes.
- **Schema export** to JSON Schema/OpenAPI for cross‑language validation.

---

## 21) Maintainers & Contributions

- **Owner:** AmpyFin Core (Config/Control Plane)
- **Contributions:** Welcome via PRs and design proposals; please include test updates and runbook impacts.
- **Security:** Report potential secret/redaction issues privately to maintainers.

---

### Appendix — ENV Naming Rules

- Key path → UPPER_SNAKE: dots become underscores.
- Only **allow‑listed** keys are mappable from ENV (to prevent surprise overrides).
- Values parse with units; booleans accept `true|false|1|0`; lists accept comma‑separated with escaping.

**Examples**
- `OMS_RISK_MAX_ORDER_NOTIONAL_USD` ↔ `oms.risk.max_order_notional_usd`
- `INGEST_YFINANCE_RATE_LIMIT_QPS` ↔ `ingest.yfinance.rate_limit_qps`

---

With `ampy-config` in place, AmpyFin gains **safety, reproducibility, and velocity**: teams iterate quickly without trading off control or compliance.
