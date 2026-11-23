"""Reading and splitting documents for RAG. Pure functions: no database, no network.

Indexing is free: passages go to MongoDB, which searches them with its built-in $text index.
No embedding model is called, so adding a book costs no tokens and a question costs none extra;
only the 3 best passages (trimmed) are sent to the AI.
"""
import io
import re

from pypdf import PdfReader

from ..core.errors import BadRequest

CHUNK_CHARS = 800
CHUNK_STEP = 650             # passages overlap by ~150 characters so sentences are not cut in half
EXCERPT_CHARS = 520          # trimmed before sending: this is what costs tokens
TOP_K = 3


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


def chunk_pages(pages: list[tuple[int, str]]) -> list[dict]:
    chunks = []
    for page, text in pages:
        text = re.sub(r"\s+", " ", text).strip()
        for start in range(0, len(text), CHUNK_STEP):
            piece = text[start:start + CHUNK_CHARS].strip()
            if len(piece) > 40:
                chunks.append({"page": page, "text": piece})
            if start + CHUNK_CHARS >= len(text):
                break
    return chunks
