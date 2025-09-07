.PHONY: validate
validate:
	python3 tools/validate.py --schema schema/ampy-config.schema.json examples/dev.yaml examples/paper.yaml examples/prod.yaml
