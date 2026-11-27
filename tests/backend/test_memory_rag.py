"""Conversation memory (follow-ups) and hybrid RAG (meaning + keywords), with a fake AI and a fake embedder."""
import numpy as np
import pytest
from bson import ObjectId

from backend.api import deps
from backend.repositories.library import LibraryRepository
from backend.services import prompts, rag
from backend.services.embeddings import EmbeddingError
from backend.services.library_service import LibraryService
from conftest import FakeProvider, register

# ---- conversation memory ----------------------------------------------------------------------------------------


def test_follow_up_on_the_same_canvas_sees_the_earlier_turns(client, fake_ai):
    register(client)
    fake_ai.reply = '{"read":"Newton second law","blocks":[{"t":"text","text":"Force equals mass times acceleration."}]}'
    client.post("/api/ask", json={"typed": "What is Newton's second law?", "canvas_id": "c1"})
    client.post("/api/ask", json={"typed": "explain it with an example", "canvas_id": "c1"})
    first, second = fake_ai.calls
    assert "Conversation so far" not in first["text"]
    assert "Conversation so far" in second["text"] and "Force equals mass times acceleration" in second["text"] and "Q1: Newton second law" in second["text"]
    assert prompts.CONTEXT_NOTE in second["system"] and prompts.CONTEXT_NOTE not in first["system"]
    assert "Typed: explain it with an example" in second["text"]


def test_a_different_canvas_starts_fresh(client, fake_ai):
    register(client)
    client.post("/api/ask", json={"typed": "What is osmosis?", "canvas_id": "c1"})
    client.post("/api/ask", json={"typed": "What is diffusion?", "canvas_id": "c2"})
    assert "Conversation so far" not in fake_ai.calls[1]["text"]


def test_only_the_last_four_turns_are_remembered(client, fake_ai):
    register(client)
    for n in range(6):
        fake_ai.reply = '{"read":"question %d","blocks":[{"t":"text","text":"answer %d"}]}' % (n, n)
        client.post("/api/ask", json={"typed": f"study question number {n}", "canvas_id": "c1"})
    last = fake_ai.calls[-1]["text"]
    assert "question 1" in last and "question 4" in last and "question 0" not in last


def test_answered_typed_text_and_grey_ink_are_passed_as_context(client, fake_ai):
    register(client)
    client.post("/api/ask", json={
        "typed": "now find b", "earlier": "a + b = 10 and a = 4", "grey_ink": True,
        "image": "data:image/png;base64,AAAA", "canvas_id": "c9",
    })
    call = fake_ai.calls[0]
    assert "Earlier (already answered): a + b = 10 and a = 4" in call["text"] and "Typed: now find b" in call["text"]
    assert prompts.CONTEXT_NOTE in call["system"]


def test_off_topic_replies_are_not_remembered(client, monkeypatch):
    from backend.services.llm import registry
    provider = FakeProvider('{"read":"pizza","flag":"off_topic","blocks":[]}')
    monkeypatch.setattr(registry, "get_provider", lambda: provider)
    register(client)
    client.post("/api/ask", json={"typed": "which pizza is the best", "canvas_id": "c1"})
    provider.reply = '{"read":"osmosis","blocks":[{"t":"text","text":"Water moves across a membrane."}]}'
    client.post("/api/ask", json={"typed": "what is osmosis", "canvas_id": "c1"})
    assert "Conversation so far" not in provider.calls[1]["text"]


# ---- RAG: embeddings + keyword, merged ----------------------------------------------------------------------------
CONCEPTS = [
    {"car", "automobile", "engine", "vehicle", "fuel", "motor", "petrol"},
    {"photosynthesis", "leaf", "leaves", "plant", "chlorophyll", "sunlight"},
]


class FakeEmbedder:
    """Maps words to a few 'meaning' dimensions, so synonyms land on the same axis."""
    dims = 3
    calls = 0

    def embed(self, texts):
        FakeEmbedder.calls += 1
        out = np.zeros((len(texts), 3), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().replace(".", " ").replace(",", " ").split():
                hit = [d for d, group in enumerate(CONCEPTS) if w in group]
                out[i, hit[0] if hit else 2] += 1.0 if hit else 0.05
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


BOOK = ("The automobile engine burns petrol inside its cylinders and the motor turns the wheels. " * 9
        + "\n" + "In a plant the leaves use sunlight and chlorophyll to make sugar by photosynthesis. " * 9)


@pytest.fixture()
def library(database):
    return LibraryService(LibraryRepository(database), FakeEmbedder())


def test_rrf_prefers_items_high_in_both_lists():
    assert set(rag.rrf(["a", "b", "c"], ["c", "b", "d"])[:2]) == {"b", "c"}
    assert rag.rrf([], []) == []


def test_ingest_stores_vectors(library, database):
    doc = library.ingest(ObjectId(), "science.txt", BOOK.encode())
    assert doc["embedded"] is True
    assert all("emb" in c for c in database.chunks.find({"doc_id": doc["_id"]}))


def test_search_finds_a_passage_by_meaning_with_no_shared_words(library):
    uid = ObjectId()
    library.ingest(uid, "science.txt", BOOK.encode())
    hits = library.search(uid, "How does a vehicle use fuel?")
    assert hits and "automobile" in hits[0]["text"] and hits[0]["source"] == "science.txt"
    plant = library.search(uid, "how do leaves get energy from sunlight")
    assert plant and "photosynthesis" in plant[0]["text"]


def test_unrelated_questions_get_no_book_passages(library):
    uid = ObjectId()
    library.ingest(uid, "science.txt", BOOK.encode())
    assert library.search(uid, "who won the cricket world cup") == []


def test_the_previous_question_helps_a_follow_up_find_the_right_passage(library):
    uid = ObjectId()
    library.ingest(uid, "science.txt", BOOK.encode())
    assert library.search(uid, "and why is that?") == []
    hits = library.search(uid, "and why is that?", context="how does a car engine work")
    assert hits and "automobile" in hits[0]["text"]


def test_a_book_still_works_when_the_embedding_service_fails(database):
    class Broken:
        def embed(self, texts):
            raise EmbeddingError("down")

    service = LibraryService(LibraryRepository(database), Broken())
    doc = service.ingest(ObjectId(), "science.txt", BOOK.encode())
    assert doc["embedded"] is False and database.chunks.count_documents({"doc_id": doc["_id"]}) > 0


def test_reindex_adds_vectors_to_an_old_book(client, monkeypatch):
    register(client)
    doc = client.post("/api/documents", files={"file": ("science.txt", BOOK.encode(), "text/plain")}).json()
    assert doc["embedded"] is False                          # uploaded while no embedding service was configured
    monkeypatch.setattr(deps, "get_embedder", lambda settings: FakeEmbedder())
    again = client.post(f"/api/documents/{doc['id']}/reindex").json()
    assert again["embedded"] is True
    assert client.get("/api/documents").json()[0]["embedded"] is True
