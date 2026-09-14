"""Shared pytest fixtures. Every test that needs the Flask app gets it via `app`/
`client` below, always with PROVIDER=stub forced — no test in this suite is allowed
to make a real network call."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("PROVIDER", "stub")


@pytest.fixture()
def app():
    from app.main import create_app
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
