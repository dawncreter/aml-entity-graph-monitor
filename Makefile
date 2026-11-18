.PHONY: install test lint demo docker
install:
	pip install -e ".[dev]"
test:
	pytest -q
lint:
	ruff check src tests && mypy src
demo:
	aml-monitor demo
docker:
	docker build -t aml-entity-graph-monitor . && docker run --rm aml-entity-graph-monitor
