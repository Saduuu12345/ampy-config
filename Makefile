.PHONY: validate
validate:
	python3 tools/validate.py --schema schema/ampy-config.schema.json examples/dev.yaml examples/paper.yaml examples/prod.yaml

PROFILE ?= dev
OVERLAYS ?= overlays/region.us-east-1.yaml
SERVICE_OVERRIDES ?= overrides/service.oms-tighten.yaml
ENV_FILE ?= .env
RUNTIME ?= runtime/overrides.yaml
OUTPUT ?= effective.yaml

.PHONY: effective
effective:
	python3 -m ampy_config.cli render --profile $(PROFILE) --overlay $(OVERLAYS) \
		--service-override $(SERVICE_OVERRIDES) --env-file $(ENV_FILE) \
		--env-allowlist env_allowlist.txt --runtime $(RUNTIME) \
		--schema schema/ampy-config.schema.json --defaults config/defaults.yaml \
		--provenance --output $(OUTPUT)

.PHONY: effective-noenv
effective-noenv:
	python3 -m ampy_config.cli render --profile $(PROFILE) --overlay $(OVERLAYS) \
		--service-override $(SERVICE_OVERRIDES) --env-allowlist env_allowlist.txt \
		--schema schema/ampy-config.schema.json --defaults config/defaults.yaml \
		--provenance --output $(OUTPUT)
.PHONY: secret-get secret-rotate render-redacted render-values
secret-get:
	python3 -m ampy_config.cli secret get --plain $(REF)

secret-rotate:
	python3 -m ampy_config.cli secret rotate $(REF)

render-redacted:
	python3 -m ampy_config.cli render --profile $(PROFILE) --resolve-secrets redacted --provenance

render-values:
	python3 -m ampy_config.cli render --profile $(PROFILE) --resolve-secrets values --provenance

.PHONY: agent ops-preview ops-apply ops-rotated
agent:
	python3 -m ampy_config.cli agent --profile $(PROFILE)

ops-preview:
	python3 -m ampy_config.cli ops preview --profile $(PROFILE) --overlay-file $(OVERLAY_FILE) --expires-at $(EXPIRES_AT) --reason "$(REASON)"

ops-apply:
	python3 -m ampy_config.cli ops apply --profile $(PROFILE) --overlay-file $(OVERLAY_FILE) --change-id $(CHANGE_ID) --canary-percent $(CANARY_PCT) --canary-duration $(CANARY_DUR)

ops-rotated:
	python3 -m ampy_config.cli ops secret-rotated --profile $(PROFILE) --reference $(REF) --rotated-at $(ROTATED_AT)

.PHONY: build publish test
build:
	python -m build

test:
	pytest -q

publish:
	@echo "Remember to set TWINE_USERNAME/TWINE_PASSWORD or use API token"
	python -m pip install --upgrade twine
	twine upload dist/*

