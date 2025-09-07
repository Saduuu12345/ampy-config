
<!--
AmpyFin / ampy-config Pull Request Template
Guidance: This module is a typed configuration & secrets façade. PRs must respect safety,
reproducibility, and observability guarantees across AmpyFin subsystems.
-->

## Summary
<!-- What problem does this solve? Why now? Link context. -->

## Related Issue(s) / Docs
Fixes #
Relates to #
Design Doc / Spec:

## Changes
- [ ] Config schema additions/edits (describe keys, types, units, defaults, constraints)
- [ ] Layering/precedence behavior
- [ ] Secrets resolution/rotation behavior
- [ ] Control-plane wiring (preview/apply/confirm via ampy-bus)
- [ ] Observability (metrics/logs/traces)
- [ ] Auditability (immutable journal / diffs)
- [ ] Safety policy (fail-shut/open, quarantine, circuit-breakers)
- [ ] Tests (golden, fuzz, precedence, secret, reload, chaos, soak)
- [ ] Docs/runbooks updates

## Backward Compatibility
- [ ] No breaking changes to public API
- [ ] If breaking, provide migration notes and deprecation schedule
- [ ] ENV mapping remains stable (list any new/renamed env keys)

## Config Schema Deltas
<!-- List new/changed keys with type, units, default, constraints, safety classification, redaction policy -->
```
key.path.example (type: duration, default: "200ms", min: "10ms", max: "2s", safety: safe, redaction: public)
```

## Secrets & Security
- [ ] No plaintext secrets in code, tests, logs
- [ ] Only secret references used (e.g., secret://..., aws-sm://...)
- [ ] Redaction verified (unit/integration)
- [ ] Rotation path tested (SecretRotated → re-resolve → atomic swap)

## Rollout Plan
- Canary %:
- Rollout duration:
- Monitoring signals:
- Rollback conditions:
- Data migrations / state impact:

## How to Test
1. Golden config(s): 
2. Precedence scenario(s):
3. Secret resolution & rotation:
4. Control-plane E2E (publish preview/apply; observe applied/rollback):
5. Failure mode(s) expected and verified:

## Screenshots / Logs / Traces
<!-- Attach helpful artifacts. Omit/redact sensitive info. -->

## Checklist
- [ ] Added/updated tests
- [ ] Updated README/runbooks where applicable
- [ ] Metrics/traces/logs added or updated
- [ ] Verified no secret leakage (CI logs checked)
- [ ] Linked to issues / closed via keywords
