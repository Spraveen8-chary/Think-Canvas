"""A user's saved canvases. Each canvas holds `items`: strokes, typed text, images and AI blocks.
Plain CRUD, so routes talk to the repository directly (no service layer needed)."""
from fastapi import APIRouter, Depends

from ...core.errors import NotFound
from ...core.ids import object_id
from ...repositories.canvases import CanvasRepository
from ..deps import canvas_repo, current_user
from ..schemas import CanvasIn

router = APIRouter(prefix="/api/canvases", tags=["canvases"])


def _title(t: str) -> str:
    return t.strip()[:100] or "Untitled"


@router.get("")
def list_canvases(user: dict = Depends(current_user), repo: CanvasRepository = Depends(canvas_repo)):
    return [{"id": str(c["_id"]), "title": c["title"], "updated_at": c["updated_at"].isoformat()} for c in repo.for_user(user["_id"])]


@router.post("", status_code=201)
def create_canvas(body: CanvasIn, user: dict = Depends(current_user), repo: CanvasRepository = Depends(canvas_repo)):
    return {"id": str(repo.create(user["_id"], _title(body.title)))}


@router.get("/{canvas_id}")
def get_canvas(canvas_id: str, user: dict = Depends(current_user), repo: CanvasRepository = Depends(canvas_repo)):
    c = repo.get(user["_id"], object_id(canvas_id))
    if not c:
        raise NotFound("Not found")
    return {"id": str(c["_id"]), "title": c["title"], "items": c["items"]}


@router.put("/{canvas_id}")
def save_canvas(canvas_id: str, body: CanvasIn, user: dict = Depends(current_user), repo: CanvasRepository = Depends(canvas_repo)):
    if not repo.save(user["_id"], object_id(canvas_id), _title(body.title), body.items):
        raise NotFound("Not found")
    return {"ok": True}


@router.delete("/{canvas_id}")
def delete_canvas(canvas_id: str, user: dict = Depends(current_user), repo: CanvasRepository = Depends(canvas_repo)):
    if not repo.delete(user["_id"], object_id(canvas_id)):
        raise NotFound("Not found")
    return {"ok": True}
