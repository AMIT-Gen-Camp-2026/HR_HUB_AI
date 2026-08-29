.PHONY: help install run ui test lint fmt typecheck check-secrets eval docker clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Create the environment and install everything
	python -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev,ui,eval]"
	.venv/bin/pre-commit install

install-hf:  ## Add the Hugging Face extras (large — torch)
	.venv/bin/pip install -e ".[hf]"

run:  ## Start the API (Flask dev server, reads FLASK_PORT from .env, default 5000)
	.venv/bin/python -m app.main

run-prod:  ## Start the API with gunicorn (used by Dockerfile too)
	.venv/bin/gunicorn --bind 0.0.0.0:$${FLASK_PORT:-5000} --workers 2 --timeout 90 app.main:app

ui:  ## Start the Streamlit tool
	.venv/bin/streamlit run ui/streamlit_app.py

test:  ## Run the test suite (all mocked/deterministic - no network, no key needed)
	.venv/bin/pytest

lint:  ## Lint
	.venv/bin/ruff check .

fmt:  ## Format
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

typecheck:  ## Type check
	.venv/bin/mypy app

check-secrets:  ## Fail if a secret is about to be committed
	.venv/bin/detect-secrets scan --baseline .secrets.baseline

eval:  ## Run the CV extraction evaluation
	.venv/bin/python -m eval.runners.run_extraction --dataset cv-extraction@v1

docker:  ## Build and run in Docker
	docker compose up --build

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +