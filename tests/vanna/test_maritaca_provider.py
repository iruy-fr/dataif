import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

VANNA_ROOT = Path(__file__).resolve().parents[2] / "services" / "vanna"
if str(VANNA_ROOT) not in sys.path:
    sys.path.insert(0, str(VANNA_ROOT))

from app.vanna_engine import MaritacaChat


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, object] | str):
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


def test_maritaca_submit_prompt_posts_chat_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": "SELECT * FROM curated.foo"}}]})

    monkeypatch.setattr("app.vanna_engine.urlopen", fake_urlopen)
    client = MaritacaChat(
        {
            "maritaca_api_url": "https://chat.maritaca.ai/api/chat/completions",
            "maritaca_api_key": "secret",
            "maritaca_timeout_seconds": 12,
            "model": "sabia-4",
        }
    )

    assert client.submit_prompt("gere sql") == "SELECT * FROM curated.foo"
    assert captured["url"] == "https://chat.maritaca.ai/api/chat/completions"
    assert captured["timeout"] == 12
    assert captured["body"] == {
        "model": "sabia-4",
        "messages": [{"role": "user", "content": "gere sql"}],
    }
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_maritaca_submit_prompt_requires_api_key() -> None:
    client = MaritacaChat({"model": "sabia-4"})
    with pytest.raises(RuntimeError, match="VANNA_MARITACA_API_KEY"):
        client.submit_prompt("gere sql")


def test_maritaca_submit_prompt_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"unauthorized"}'),
        )

    monkeypatch.setattr("app.vanna_engine.urlopen", fake_urlopen)
    client = MaritacaChat({"maritaca_api_key": "secret", "model": "sabia-4"})

    with pytest.raises(RuntimeError, match="HTTP 401"):
        client.submit_prompt("gere sql")


def test_maritaca_submit_prompt_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout: int):
        return FakeResponse("not-json")

    monkeypatch.setattr("app.vanna_engine.urlopen", fake_urlopen)
    client = MaritacaChat({"maritaca_api_key": "secret", "model": "sabia-4"})

    with pytest.raises(RuntimeError, match="invalid response"):
        client.submit_prompt("gere sql")
