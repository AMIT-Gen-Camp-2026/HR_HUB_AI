"""Thin wrapper around provider.embed() with content-hash caching, so re-running the
pipeline on the same claim text doesn't re-embed it every time."""
from __future__ import annotations

import hashlib

from app.providers.base import ProviderAdapter

_cache: dict[str, list[float]] = {}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_cached(provider: ProviderAdapter, texts: list[str]) -> list[list[float]]:
    to_fetch = [t for t in texts if _hash(t) not in _cache]
    if to_fetch:
        fresh = provider.embed(to_fetch)
        for t, vec in zip(to_fetch, fresh):
            _cache[_hash(t)] = vec
    return [_cache[_hash(t)] for t in texts]