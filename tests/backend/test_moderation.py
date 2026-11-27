import pytest

from backend.services import moderation
from conftest import FakeProvider, register

CLEAN = [
    "Explain the class assignment about the passage",
    "Solve x^2 + 3x + 5 = 0",
    "What is the capital of Niger?",
    "Moby Dick is a novel by Herman Melville",
    "How do I kill a process in Linux? kill -9 1234",
    "Why is garbage collection slow? do you know the reason",
    "shiitake mushrooms grow on wood",
    "Describe the Scunthorpe problem in text filters",
    "(a+b)^2 = ?",
    "the cat sat on the mat and the assassin class",
]
BAD = [
    "you are a fucking idiot",
    "f u c k this",
    "f*ck this homework",
    "fuuuuuck",
    "sh1t",
    "BULLSHIT answer",
    "i will kill you",
    "you are stupid",
    "madarchod",
    "lanja",
    "watch porn",
    "go die",
]


@pytest.mark.parametrize("text", CLEAN)
def test_normal_study_text_is_not_flagged(text):
    assert moderation.scan(text) is None


@pytest.mark.parametrize("text", BAD)
def test_bad_language_is_flagged_even_when_disguised(text):
    assert moderation.scan(text) is not None


def test_reports_never_contain_the_full_word():
    assert "*" in moderation.scan("fuck").term and "fuck" not in moderation.scan("fuck").term


def test_smalltalk_detection():
    assert moderation.is_smalltalk("Hello!") and moderation.is_smalltalk("thank you")
    assert not moderation.is_smalltalk("hello world program in C")


# ---- through the API ------------------------------------------------------------------------------------------------
def test_abusive_text_is_blocked_before_the_ai_and_counts_a_strike(client, fake_ai):
    register(client)
    r = client.post("/api/ask", json={"typed": "you fucking idiot", "source": "type"})
    assert r.status_code == 200
    v = r.json()["violation"]
    assert v["strikes"] == 1 and v["limit"] == 3 and not v["suspended"] and "reported" in v["message"]
    assert fake_ai.calls == []                                   # the AI never saw it


def test_third_strike_suspends_the_account(client, fake_ai):
    register(client)
    for n in (1, 2, 3):
        assert client.post("/api/ask", json={"typed": "fuck you"}).json()["violation"]["strikes"] == n
    last = client.post("/api/ask", json={"typed": "ok"})
    assert last.status_code == 403 and "suspended" in last.json()["error"]["message"]
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"}).status_code == 403


def test_ai_flag_abuse_is_reported_and_blocks_are_dropped(client, monkeypatch):
    from backend.services.llm import registry
    provider = FakeProvider('{"read":"","flag":"abuse","blocks":[{"t":"text","text":"x"}]}')
    monkeypatch.setattr(registry, "get_provider", lambda: provider)
    register(client)
    r = client.post("/api/ask", json={"typed": "some hateful sentence without keywords"})
    assert r.json()["violation"]["strikes"] == 1 and r.json()["blocks"] == []


def test_off_topic_gets_the_fixed_education_message_and_no_strike(client, monkeypatch):
    from backend.services.llm import registry
    provider = FakeProvider('{"read":"best pizza","flag":"off_topic","blocks":[{"t":"text","text":"Try Dominos!"}]}')
    monkeypatch.setattr(registry, "get_provider", lambda: provider)
    register(client)
    r = client.post("/api/ask", json={"typed": "which pizza is best"}).json()
    assert "violation" not in r and r["flag"] == "off_topic"
    assert r["blocks"] == [{"t": "text", "text": moderation.OFF_TOPIC_MESSAGE}]


def test_greeting_is_answered_locally_without_calling_the_ai(client, fake_ai):
    register(client)
    r = client.post("/api/ask", json={"typed": "hi"}).json()
    assert r["blocks"][0]["text"] == moderation.OFF_TOPIC_MESSAGE and fake_ai.calls == []


def test_confidence_and_flag_are_parsed(client, monkeypatch):
    from backend.services.llm import registry
    provider = FakeProvider('{"read":"(a+b)^2=","conf":0.55,"kind":"math","flag":"none","blocks":[{"t":"text","text":"a^2+2ab+b^2"}]}')
    monkeypatch.setattr(registry, "get_provider", lambda: provider)
    register(client)
    r = client.post("/api/ask", json={"typed": "(a+b)^2 ="}).json()
    assert r["conf"] == 0.55 and r["flag"] is None and r["blocks"][0]["text"] == "a^2+2ab+b^2"


def test_live_relay_reports_bad_language_heard_in_speech(client, monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace

    from backend.api.routes import live as live_route

    register(client)
    monkeypatch.setattr(live_route, "get_settings", lambda: SimpleNamespace(gemini_api_key="k", gemini_live_model="models/m"))

    class FakeGem:
        async def send(self, m):
            pass

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield json.dumps({"serverContent": {"inputTranscription": {"text": "you fucking idiot"}}})
            await asyncio.sleep(5)

    class Ctx:
        async def __aenter__(self):
            return FakeGem()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(live_route.websockets, "connect", lambda *a, **k: Ctx())
    with client.websocket_connect("/api/live/ws") as w:
        w.send_text(json.dumps({"start": True, "language": "en"}))
        msg = json.loads(w.receive_text())
    assert msg["tcViolation"]["strikes"] == 1 and "reported" in msg["tcViolation"]["message"]


def test_live_setup_has_language_noise_and_education_rules():
    from backend.services import live as live_svc
    from backend.services.prompts import LIVE_TUTOR_INSTRUCTION

    setup = live_svc.build_setup("gemini-3.8-live", LIVE_TUTOR_INSTRUCTION, None, "te")["setup"]
    text = setup["systemInstruction"]["parts"][0]["text"]
    assert "RESPOND IN TELUGU" in text and "ONLY help with education" in text
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["startOfSpeechSensitivity"] == "START_SENSITIVITY_LOW"
    assert "customVocabulary" in setup["inputAudioTranscription"]
    assert "customVocabulary" not in live_svc.build_setup("gemini-3.1-flash-live-preview", "x")["setup"]["inputAudioTranscription"]
