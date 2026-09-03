from types import SimpleNamespace

from app.providers import embeddings


def test_api_embeddings_are_returned_in_input_order(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(embeddings.httpx, "Client", lambda timeout: FakeClient())
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_api_key="test-key",
            embedding_api_base_url="https://example.test/",
            embedding_api_model="test-model",
        ),
    )

    assert embeddings._embed_uncached_api(["cv", "jd"]) == [[1.0, 0.0], [0.0, 1.0]]
