import os
import sys
import tempfile
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="tc-test-logs-")      # tests must not write into the real logs/ folder

from backend import db as dbmod  # noqa: E402
from backend.api import deps  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services.llm import LLMProvider, LLMReply, registry  # noqa: E402


@pytest.fixture()
def database():
    d = mongomock.MongoClient().think_canvas_test
    dbmod.set_db(d)
    deps.ask_limiter.reset()
    deps.auth_limiter.reset()
    return d


@pytest.fixture()
def client(database):
    with TestClient(app) as c:
        yield c


class FakeProvider(LLMProvider):
    """Stands in for the AI: records what it was sent and returns a canned reply."""
    name, model = "fake", "fake-model"

    def __init__(self, reply='{"read":"2+2","blocks":[{"t":"text","text":"4"}]}', tokens=(300, 20)):
        self.reply, self.tokens, self.calls = reply, tokens, []

    async def complete(self, system, text, image=None):
        self.calls.append({"system": system, "text": text, "image": image})
        return LLMReply(self.reply, *self.tokens, model=self.model)


@pytest.fixture()
def fake_ai(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(registry, "get_provider", lambda: provider)
    return provider


def register(client, email="a@example.com", name="Asha"):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return r.json()
