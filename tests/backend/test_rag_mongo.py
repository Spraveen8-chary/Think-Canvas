"""RAG search uses MongoDB's real $text index, so this runs against a real MongoDB.
Set TEST_MONGODB_URI (e.g. mongodb://localhost:27018). Skipped when it is not set or not reachable."""
import os

import pytest
from bson import ObjectId
from pymongo import MongoClient

from backend import db as dbmod
from backend.repositories.library import LibraryRepository
from backend.services.library_service import LibraryService

URI = os.environ.get("TEST_MONGODB_URI")


@pytest.fixture()
def real_db():
    if not URI:
        pytest.skip("TEST_MONGODB_URI not set")
    client = MongoClient(URI, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception:
        pytest.skip("MongoDB not reachable")
    name = f"think_canvas_test_{ObjectId()}"
    d = client[name]
    dbmod.set_db(d)
    yield d
    client.drop_database(name)


def make_pdf(pages: list[str]) -> bytes:
    """A tiny valid PDF with one line of text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        content = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
        n = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {n + 2} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(f"{n + 1} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + (o if isinstance(o, bytes) else o.encode()) + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)


def test_pdf_is_indexed_and_searched_with_page_numbers(real_db):
    library = LibraryService(LibraryRepository(real_db))
    uid = ObjectId()
    pdf = make_pdf(["Photosynthesis converts light energy into chemical energy in chloroplasts and plants.",
                    "Newton second law says force equals mass times acceleration for moving bodies."])
    doc = library.ingest(uid, "Science.pdf", pdf)
    assert doc["pages"] == 2

    hits = library.search(uid, "what is the force on a mass with acceleration")
    assert hits and hits[0]["source"] == "Science.pdf" and hits[0]["page"] == 2
    assert library.search(uid, "chloroplast photosynthesis")[0]["page"] == 1
    assert library.search(ObjectId(), "force mass") == []                           # other users see nothing

    library.set_active(uid, doc["_id"], False)
    assert library.search(uid, "force mass") == []                                  # switched off in the dialog
