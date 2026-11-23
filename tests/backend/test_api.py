from fastapi.testclient import TestClient

from backend.api import deps
from backend.main import app

from conftest import FakeProvider, register


def error_code(response):
    return response.json()["error"]["code"]


def test_register_login_logout_and_profile(client):
    user = register(client)
    assert user["email"] == "a@example.com" and "password" not in str(user)
    assert client.get("/api/auth/me").json()["name"] == "Asha"
    assert client.put("/api/auth/me", json={"name": "Asha K", "organisation": "MIT"}).json()["organisation"] == "MIT"

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrongpass1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "A@Example.com", "password": "password123"}).status_code == 200
    assert client.get("/api/auth/me").json()["name"] == "Asha K"


def test_register_rules_and_error_shape(client):
    register(client)
    body = {"name": "X", "email": "a@example.com", "password": "password123"}
    dup = client.post("/api/auth/register", json=body)
    assert dup.status_code == 409 and error_code(dup) == "conflict"                   # every error has the same shape
    assert client.post("/api/auth/register", json={**body, "email": "nope"}).status_code == 400
    assert client.post("/api/auth/register", json={**body, "email": "b@x.io", "password": "short"}).status_code == 400
    assert error_code(client.post("/api/auth/register", json={"name": "X"})) == "invalid_request"   # missing fields


def test_password_is_not_stored_in_plain_text(client, database):
    register(client)
    stored = database.users.find_one()["password_hash"]
    assert stored.startswith("scrypt$") and "password123" not in stored


def test_login_is_rate_limited(client):
    register(client)
    deps.auth_limiter.limit = 3
    try:
        bad = {"email": "a@example.com", "password": "bad-password"}
        codes = [client.post("/api/auth/login", json=bad).status_code for _ in range(5)]
        retry_after = client.post("/api/auth/login", json=bad).headers.get("retry-after")
    finally:
        deps.auth_limiter.limit = 10
    assert codes == [401, 401, 401, 429, 429]
    assert retry_after


def test_everything_requires_login(client):
    for method, url in [("get", "/api/canvases"), ("post", "/api/ask"), ("get", "/api/documents"), ("get", "/api/history")]:
        assert getattr(client, method)(url).status_code in (401, 422)


def test_users_cannot_see_each_others_canvases(client):
    register(client)
    cid = client.post("/api/canvases", json={"title": "Mine"}).json()["id"]
    items = [{"type": "stroke", "points": [[1, 2], [3, 4]]}]
    assert client.put(f"/api/canvases/{cid}", json={"title": "Mine", "items": items}).status_code == 200
    assert client.get(f"/api/canvases/{cid}").json()["items"] == items

    other = TestClient(app)                      # a second browser
    register(other, "b@example.com", "Bala")
    assert other.get("/api/canvases").json() == []
    assert other.get(f"/api/canvases/{cid}").status_code == 404
    assert other.put(f"/api/canvases/{cid}", json={"title": "x", "items": []}).status_code == 404
    assert other.delete(f"/api/canvases/{cid}").status_code == 404
    assert client.get("/api/canvases/not-an-id").status_code == 404
    assert client.delete(f"/api/canvases/{cid}").status_code == 200


def test_image_assets_are_private(client):
    register(client)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    aid = client.post("/api/assets", files={"file": ("a.png", png, "image/png")}).json()["id"]
    r = client.get(f"/api/assets/{aid}")
    assert r.content == png and r.headers["content-type"] == "image/png"
    assert client.post("/api/assets", files={"file": ("a.exe", b"x", "application/octet-stream")}).status_code == 400
    other = TestClient(app)
    register(other, "b@example.com")
    assert other.get(f"/api/assets/{aid}").status_code == 404


def test_ask_returns_blocks_tokens_and_is_saved_to_history(client, fake_ai):
    register(client)
    fake_ai.reply = '```json\n{"read":"2+2","blocks":[{"t":"text","text":"**4**"},{"t":"bad"}]}\n```'
    r = client.post("/api/ask", json={"image": "data:image/png;base64,AAAA"})
    body = r.json()
    assert r.status_code == 200
    assert body["blocks"] == [{"t": "text", "text": "4"}] and body["tokens"] == {"in": 300, "out": 20}
    assert fake_ai.calls[0]["image"].startswith("data:image/png")

    typed = client.post("/api/ask", json={"typed": "what is 3+3"}).json()
    assert fake_ai.calls[1]["image"] is None and "what is 3+3" in fake_ai.calls[1]["text"] and typed["read"] == "2+2"

    hist = client.get("/api/history").json()
    assert len(hist) == 2 and hist[0]["kinds"] == ["text"] and hist[0]["answer"] == "4"
    assert client.post("/api/ask", json={}).status_code == 400


def test_ask_reports_unreadable_ai_reply(client, fake_ai):
    register(client)
    fake_ai.reply = "I think the answer is four"
    r = client.post("/api/ask", json={"typed": "2+2"})
    assert r.status_code == 502 and error_code(r) == "upstream_error"


def test_ask_retries_once_when_the_reply_is_not_valid_json(client, fake_ai):
    register(client)
    replies = iter(['{"read":"x","blocks":[{"t":"anim","w":300,"h":200,"o":[],"m":[], "ms": 25*2}]}',     # arithmetic: not JSON
                    '{"read":"x","blocks":[{"t":"text","text":"ok"}]}'])
    original = fake_ai.complete

    async def flaky(system, text, image=None):
        fake_ai.reply = next(replies)
        return await original(system, text, image)

    fake_ai.complete = flaky
    r = client.post("/api/ask", json={"typed": "projectile motion"})
    assert r.status_code == 200 and r.json()["blocks"] == [{"t": "text", "text": "ok"}]
    assert len(fake_ai.calls) == 2 and "not valid JSON" in fake_ai.calls[1]["text"]
    assert r.json()["tokens"] == {"in": 600, "out": 40}                     # both attempts are counted


def test_ask_is_rate_limited_per_user(client, fake_ai):
    register(client)
    deps.ask_limiter.limit = 2
    try:
        codes = [client.post("/api/ask", json={"typed": "hi"}).status_code for _ in range(3)]
    finally:
        deps.ask_limiter.limit = 20
    assert codes == [200, 200, 429]


def test_logs_show_token_use_but_never_content_or_secrets(client, fake_ai, caplog, monkeypatch):
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-SUPERSECRET")
    register(client)
    with caplog.at_level("INFO"):
        client.post("/api/ask", json={"typed": "my private homework question"})
        client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ask.done" in text and "tokens_in=300" in text and "tokens_out=20" in text and "provider=fake" in text
    assert "auth.login_failed" in text and "a***@example.com" in text
    assert "http method=POST path=/api/ask status=200" in text
    for secret in ("private homework", "SUPERSECRET", "password123", "wrong-password-1", "a@example.com"):
        assert secret not in text


def test_cross_site_writes_are_blocked_and_headers_are_set(client):
    register(client)
    r = client.post("/api/canvases", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = client.get("/api/health")
    assert ok.json() == {"status": "ok", "database": True}
    assert "frame-ancestors 'none'" in ok.headers["content-security-policy"] and ok.headers["x-request-id"]


def test_library_upload_and_toggle(client):
    register(client)
    text = ("Newton's second law states that force equals mass times acceleration. " * 20).encode()
    doc = client.post("/api/documents", files={"file": ("physics.txt", text, "text/plain")}).json()
    assert doc["name"] == "physics.txt" and doc["chunks"] >= 1 and doc["active"]
    assert client.put(f"/api/documents/{doc['id']}", json={"active": False}).status_code == 200
    assert client.get("/api/documents").json()[0]["active"] is False
    assert client.post("/api/documents", files={"file": ("x.docx", b"x", "application/zip")}).status_code == 400
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert client.get("/api/documents").json() == []
