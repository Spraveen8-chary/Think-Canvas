from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from backend.api import deps
from backend.core.config import get_settings
from backend.services import live as live_svc
from backend.services import stt as stt_svc
from conftest import register


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _patch_settings(monkeypatch, **overrides):
    base = get_settings()
    patched = replace(base, **overrides)
    deps.app_settings = patched if hasattr(deps, "app_settings") else None
    from backend.main import app
    app.dependency_overrides[deps.settings] = lambda: patched
    return patched


@pytest.fixture(autouse=True)
def _clear_overrides():
    from backend.main import app
    yield
    app.dependency_overrides.pop(deps.settings, None)


def test_voice_endpoints_require_auth(client):
    for method, url in [
        ("post", "/api/stt/token"),
        ("post", "/api/stt/transcribe"),
        ("post", "/api/live/blocks"),
        ("post", "/api/live/history"),
    ]:
        assert getattr(client, method)(url).status_code in (401, 422)


def test_stt_token_mints_temporary_token_and_masks_errors(client, monkeypatch):
    register(client)
    _patch_settings(monkeypatch, assemblyai_api_key="secret-aai-key")

    seen = {}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, params=None, headers=None):
            seen["url"] = url
            seen["params"] = params
            seen["headers"] = headers
            return _FakeResponse(200, {"token": "temp-aai-token"})

    monkeypatch.setattr(stt_svc.httpx, "AsyncClient", FakeClient)
    r = client.post("/api/stt/token")
    assert r.status_code == 200
    body = r.json()
    assert body == {"token": "temp-aai-token", "ws_url": stt_svc.STREAMING_WS_URL, "expires_in": 300}
    assert seen["headers"]["Authorization"] == "secret-aai-key"
    assert "secret-aai-key" not in r.text

    # Vendor failure never leaks raw vendor body
    class FailClient(FakeClient):
        async def get(self, url, params=None, headers=None):
            return _FakeResponse(500, text="internal vendor secret trace")

    monkeypatch.setattr(stt_svc.httpx, "AsyncClient", FailClient)
    err = client.post("/api/stt/token")
    assert err.status_code == 502
    assert err.json()["error"]["code"] == "upstream_error"
    assert "vendor secret" not in err.text


def test_stt_token_missing_key_and_rate_limit(client, monkeypatch):
    register(client)
    _patch_settings(monkeypatch, assemblyai_api_key="")
    r = client.post("/api/stt/token")
    assert r.status_code == 400

    _patch_settings(monkeypatch, assemblyai_api_key="secret-aai-key")
    deps.stt_limiter.reset()
    deps.stt_limiter.limit = 2

    class OkClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResponse(200, {"token": "t"})

    monkeypatch.setattr(stt_svc.httpx, "AsyncClient", OkClient)
    try:
        assert client.post("/api/stt/token").status_code == 200
        assert client.post("/api/stt/token").status_code == 200
        assert client.post("/api/stt/token").status_code == 429
    finally:
        deps.stt_limiter.limit = 20


def test_stt_transcribe_fallback_and_validation(client, monkeypatch):
    register(client)
    _patch_settings(monkeypatch, assemblyai_api_key="secret-aai-key")

    # Bad mime type rejected
    bad = client.post(
        "/api/stt/transcribe",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"language": "auto"},
    )
    assert bad.status_code == 400

    polls = {"count": 0}
    captured = {}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, headers=None, content=None, json=None):
            if url == stt_svc.UPLOAD_URL:
                return _FakeResponse(200, {"upload_url": "https://cdn.example/audio.webm"})
            captured["transcript_payload"] = json
            return _FakeResponse(200, {"id": "tr_123"})

        async def get(self, url, headers=None):
            polls["count"] += 1
            if polls["count"] == 1:
                return _FakeResponse(200, {"status": "processing"})
            return _FakeResponse(200, {"status": "completed", "text": "नमस्ते दुनिया", "language_code": "hi"})

    monkeypatch.setattr(stt_svc.httpx, "AsyncClient", FakeClient)
    r = client.post(
        "/api/stt/transcribe",
        files={"file": ("clip.webm", b"\x1a\x45\xdf\xa3audio", "audio/webm;codecs=opus")},
        data={"language": "auto"},
    )
    assert r.status_code == 200
    assert r.json() == {"text": "नमस्ते दुनिया", "language_code": "hi"}
    assert captured["transcript_payload"]["language_detection"] is True


def test_live_setup_is_built_on_the_server():
    setup = live_svc.build_setup("models/gemini-3.1-flash-live-preview", "be a tutor")["setup"]
    assert setup["model"] == "models/gemini-3.1-flash-live-preview"
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert setup["tools"][0]["functionDeclarations"]
    assert setup["sessionResumption"] == {}
    assert live_svc.build_setup("m", "x", "h1")["setup"]["sessionResumption"] == {"handle": "h1"}


def test_live_socket_requires_login(client):
    from starlette.websockets import WebSocketDisconnect
    with client.websocket_connect("/api/live/ws") as w:
        with pytest.raises(WebSocketDisconnect) as e:
            w.receive_text()
    assert "log in" in (e.value.reason or "")


def test_live_socket_needs_gemini_key(client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    register(client)
    monkeypatch.setattr("backend.api.routes.live.get_settings", lambda: SimpleNamespace(gemini_api_key="", gemini_live_model="m"))
    with client.websocket_connect("/api/live/ws") as w:
        with pytest.raises(WebSocketDisconnect) as e:
            w.receive_text()
    assert "GEMINI_API_KEY" in (e.value.reason or "")


def test_live_blocks_validation_and_history(client):
    register(client)

    plot = client.post("/api/live/blocks", json={"name": "draw_plot", "args": {"f": ["sin(x)"], "x": [-5, 5]}})
    assert plot.status_code == 200
    assert plot.json() == {"action": "draw", "block": {"t": "plot", "f": ["sin(x)"], "x": [-5.0, 5.0]}}

    flow = client.post("/api/live/blocks", json={
        "name": "draw_flow",
        "args": {"dir": "right", "nodes": [["a", "Client", "oval"], ["b", "API", "box"]], "edges": [["a", "b", "HTTPS"]]},
    })
    assert flow.status_code == 200
    assert flow.json()["block"]["t"] == "flow"

    clear = client.post("/api/live/blocks", json={"name": "clear_canvas_area", "args": {}})
    assert clear.status_code == 200
    assert clear.json() == {"action": "clear", "block": None}

    bad_expr = client.post("/api/live/blocks", json={"name": "draw_plot", "args": {"f": ["alert(1);"]}})
    assert bad_expr.status_code == 400

    unknown = client.post("/api/live/blocks", json={"name": "eval_js", "args": {}})
    assert unknown.status_code == 400

    hist = client.post("/api/live/history", json={
        "canvas_id": "c1",
        "transcript": [{"role": "user", "text": "Explain projectile motion"}, {"role": "model", "text": "Here is the arc."}],
        "kinds": ["plot"],
    })
    assert hist.status_code == 200
    items = client.get("/api/history").json()
    assert len(items) == 1
    assert "[Live]" in items[0]["read"]
    assert items[0]["kinds"] == ["plot"]
