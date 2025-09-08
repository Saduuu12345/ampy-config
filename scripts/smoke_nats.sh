# scripts/smoke_nats.sh
#!/usr/bin/env bash
set -euo pipefail

export NATS_URL="${NATS_URL:-nats://127.0.0.1:4222}"

echo "== NATS server info =="
nats --server "$NATS_URL" server info || true

echo "== Streams =="
nats --server "$NATS_URL" stream ls || true

echo "== Ensure stream/consumers =="
nats --server "$NATS_URL" stream add ampy-control \
  --subjects "ampy.*.control.v1.*" \
  --retention limits --max-age 24h --storage file \
  --max-msgs 10000 --max-bytes 100MB --discard old --defaults || true

for C in \
  ampy-config-agent-ampy-dev-control-v1-config-preview:ampy.dev.control.v1.config_preview \
  ampy-config-agent-ampy-dev-control-v1-config-apply:ampy.dev.control.v1.config_apply \
  ampy-config-agent-ampy-dev-control-v1-secret-rotated:ampy.dev.control.v1.secret_rotated \
  ampy-service-demo-ampy-dev-control-v1-config-preview:ampy.dev.control.v1.config_preview \
  ampy-service-demo-ampy-dev-control-v1-config-apply:ampy.dev.control.v1.config_apply \
  ampy-service-demo-ampy-dev-control-v1-secret-rotated:ampy.dev.control.v1.secret_rotated
do
  NAME="${C%%:*}"; SUBJ="${C##*:}"
  nats --server "$NATS_URL" consumer add ampy-control "$NAME" \
    --filter "$SUBJ" --pull --deliver all --ack explicit --defaults || true
done

echo "== Consumers =="
nats --server "$NATS_URL" consumer ls ampy-control
