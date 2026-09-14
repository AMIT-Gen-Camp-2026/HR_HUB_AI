.PHONY: install run test lint fmt check-env

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

run:
	. .venv/bin/activate && flask --app app.main:create_app run --port $${API_PORT:-8100} --debug

test:
	. .venv/bin/activate && pytest -v

lint:
	. .venv/bin/activate && ruff check . && mypy app

fmt:
	. .venv/bin/activate && ruff format .

check-env:
	. .venv/bin/activate && python scripts/check_env.py
