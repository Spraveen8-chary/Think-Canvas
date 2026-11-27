"""Reading and splitting documents for RAG, and ranking passages. Pure functions: no database, no network.

RAG here is HYBRID: each passage has a keyword index (MongoDB $text) and an embedding vector (meaning).
A question finds candidates both ways and the two rankings are merged with Reciprocal Rank Fusion, so a
paraphrase ("how does a car engine work") still finds the passage that says "internal combustion". Only the
best few passages (trimmed) are sent to the AI, never the whole book.
"""
import io
import re

from pypdf import PdfReader

from ..core.errors import BadRequest

CHUNK_CHARS = 800
CHUNK_STEP = 650             # passages overlap by ~150 characters so sentences are not cut in half
EXCERPT_CHARS = 700          # trimmed before sending: this is what costs tokens
TOP_K = 4
MIN_SIMILARITY = 0.25        # cosine: below this a passage is not about the question (keeps unrelated questions book-free)
RRF_K = 60


def extract_pages(filename: str, data: bytes) -> list[tuple[int, str]]:
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            return [(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
        except Exception as e:
            raise BadRequest(f"Could not read this PDF ({e.__class__.__name__})")
    if name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
        return [(i // 3000 + 1, text[i:i + 3000]) for i in range(0, len(text), 3000)]   # ~3000 chars = one "page"
    raise BadRequest("Use a PDF, TXT or MD file")


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(“])")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
MIN_PARAGRAPH = 80           # only headings / one-liners are joined with the next paragraph (never merge real paragraphs of different topics)


def _pack(paragraph: str) -> list[str]:
    """Packs whole sentences into passages of at most CHUNK_CHARS; the last sentence is repeated at the start of the
    next passage (a small overlap) so an idea that spans two passages is still found."""
    sentences: list[str] = []
    for s in _SENTENCE.split(paragraph):
        while len(s) > CHUNK_CHARS:                          # a very long "sentence" (no punctuation): cut it
            sentences.append(s[:CHUNK_STEP])
            s = s[CHUNK_STEP:]
        if s:
            sentences.append(s)
    chunks, current, last = [], "", ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > CHUNK_CHARS:
            chunks.append(current)
            current = f"{last} {sentence}" if last and len(last) <= 250 else sentence
        else:
            current = f"{current} {sentence}".strip()
        last = sentence
    if current:
        chunks.append(current)
    return chunks


def chunk_pages(pages: list[tuple[int, str]]) -> list[dict]:
    """Splits each page into topic-friendly passages: paragraph breaks are respected, and passages end at sentence
    boundaries. (Passages that mix two topics get a blurry embedding and match nothing well.)"""
    chunks = []
    for page, text in pages:
        paragraphs, carry = [], ""
        for raw in _PARAGRAPH_BREAK.split(text or ""):
            p = re.sub(r"\s+", " ", raw).strip()
            if not p:
                continue
            p = f"{carry} {p}".strip() if carry else p
            if len(p) < MIN_PARAGRAPH:
                carry = p
                continue
            paragraphs.append(p)
            carry = ""
        if carry:
            paragraphs.append(carry)
        for paragraph in paragraphs:
            for piece in _pack(paragraph):
                if len(piece) > 40:
                    chunks.append({"page": page, "text": piece})
    return chunks


def rrf(*rankings: list, k: int = RRF_K) -> list:
    """Reciprocal Rank Fusion: merges several best-first lists of ids into one list. An id that is high in
    several lists wins; no score scaling between keyword and vector search is needed."""
    score: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=score.get, reverse=True)
