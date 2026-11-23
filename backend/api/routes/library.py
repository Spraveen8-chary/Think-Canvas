"""The user's library of textbooks / PDFs used for RAG."""
import asyncio

from fastapi import APIRouter, Depends, File, UploadFile

from ...core.errors import TooLarge
from ...core.ids import object_id
from ...repositories.library import LibraryRepository
from ...services.library_service import LibraryService
from ..deps import current_user, library_repo, library_service
from ..schemas import ActiveIn

router = APIRouter(prefix="/api/documents", tags=["library"])
MAX_BYTES = 40_000_000


def _row(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d["name"], "pages": d["pages"], "chunks": d["chunks"], "active": d["active"]}


@router.get("")
def list_documents(user: dict = Depends(current_user), repo: LibraryRepository = Depends(library_repo)):
    return [_row(d) for d in repo.for_user(user["_id"])]


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user), service: LibraryService = Depends(library_service)):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TooLarge("File is too large (max 40 MB)")
    # Parsing a big PDF is slow CPU work: run it off the event loop so other requests keep flowing.
    return _row(await asyncio.to_thread(service.ingest, user["_id"], file.filename or "document", data))


@router.put("/{doc_id}")
def set_active(doc_id: str, body: ActiveIn, user: dict = Depends(current_user), service: LibraryService = Depends(library_service)):
    service.set_active(user["_id"], object_id(doc_id), body.active)
    return {"ok": True}


@router.delete("/{doc_id}")
def delete_document(doc_id: str, user: dict = Depends(current_user), service: LibraryService = Depends(library_service)):
    service.delete(user["_id"], object_id(doc_id))
    return {"ok": True}
