"""Images the user imports onto a canvas (the browser shrinks them first), stored in MongoDB."""
import asyncio

from fastapi import APIRouter, Depends, File, Response, UploadFile

from ...core.errors import BadRequest, NotFound, TooLarge
from ...core.ids import object_id
from ...repositories.assets import AssetRepository
from ..deps import asset_repo, current_user

router = APIRouter(prefix="/api/assets", tags=["assets"])
ALLOWED = {"image/png", "image/jpeg", "image/webp"}
MAX_BYTES = 3_000_000


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user), repo: AssetRepository = Depends(asset_repo)):
    if file.content_type not in ALLOWED:
        raise BadRequest("Use a PNG, JPEG or WebP image")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TooLarge("Image is too large (max 3 MB)")
    asset_id = await asyncio.to_thread(repo.add, user["_id"], file.content_type, data)
    return {"id": str(asset_id)}


@router.get("/{asset_id}")
def download(asset_id: str, user: dict = Depends(current_user), repo: AssetRepository = Depends(asset_repo)):
    a = repo.get(user["_id"], object_id(asset_id))
    if not a:
        raise NotFound("Not found")
    return Response(bytes(a["data"]), media_type=a["mime"], headers={"Cache-Control": "private, max-age=3600"})
