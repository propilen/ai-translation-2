from pathlib import Path
import uuid
from typing import Literal
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse

from .config import runtime_settings
from .translation_memory import (add_segment, append_tmx, checkpoint_database,
                                 convert_tmx, delete_segment, read_metadata,
                                 search_memory, stream_tmx)

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent


class SegmentPayload(BaseModel):
    source: str = Field(min_length=1, max_length=10000)
    target: str = Field(min_length=1, max_length=10000)
    tuid: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)


def require_memory_write_scope(request: Request, memory_id: str) -> None:
    user = request_user(request)
    if user.get("api_key_authenticated") and not user.get("api_key_can_write", False):
        raise HTTPException(403, "У API-ключа нет права записи в память переводов.")
    scope = user.get("api_key_memory_id")
    if user.get("api_key_authenticated") and scope and scope != memory_id:
        raise HTTPException(403, "API-ключ не имеет права записи в эту память переводов.")


def memory_directory():
    directory = runtime_settings.get().workspace_root / "memories"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def request_user(request: Request) -> dict:
    # Router tests can run without the application's authentication middleware.
    return getattr(request.state, "user", {})


def require_memory_scope(request: Request, memory_id: str) -> None:
    user = request_user(request)
    scope = user.get("api_key_memory_id")
    if user.get("api_key_authenticated") and not user.get("api_key_can_read", True):
        raise HTTPException(403, "У API-ключа нет права чтения памяти переводов.")
    if user.get("api_key_authenticated") and scope and scope != memory_id:
        raise HTTPException(403, "API-ключ не имеет доступа к этой памяти переводов.")


def memory_path(memory_id):
    try:
        canonical = str(uuid.UUID(memory_id))
    except ValueError:
        raise HTTPException(404, "Память не найдена")
    path = memory_directory() / f"{canonical}.sqlite"
    if not path.is_file():
        raise HTTPException(404, "Память не найдена")
    return path


@router.get("/memories.html")
def page():
    return FileResponse(ROOT / "memories.html")


@router.get("/memories.js")
def script():
    return FileResponse(ROOT / "memories.js", media_type="text/javascript")


@router.get("/memories.css")
def style():
    return FileResponse(ROOT / "memories.css", media_type="text/css")


@router.get("/api/memories")
def list_memories(request: Request):
    user = request_user(request)
    if user.get("api_key_authenticated") and not user.get("api_key_can_read", True):
        raise HTTPException(403, "У API-ключа нет права чтения памяти переводов.")
    scope = user.get("api_key_memory_id")
    paths = [memory_path(scope)] if user.get("api_key_authenticated") and scope else sorted(memory_directory().glob("*.sqlite"))
    return [dict(read_metadata(path), id=path.stem) for path in paths]


@router.post("/api/memories", status_code=201)
def import_memory(request: Request, document: UploadFile = File(...), name: str = Form("", max_length=200),
                  source_language: str = Form(..., max_length=40), target_language: str = Form(..., max_length=40),
                  description: str = Form("", max_length=2000), existing_memory_id: str = Form("", max_length=36)):
    user = request_user(request)
    if user.get("api_key_authenticated") and not user.get("api_key_can_write", False):
        raise HTTPException(403, "У API-ключа нет права записи в память переводов.")
    if user.get("api_key_authenticated") and user.get("api_key_memory_id") != (existing_memory_id.strip() or None):
        raise HTTPException(403, "Ключ с доступом к одной памяти может дополнять только эту память.")
    filename = (document.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".tmx"):
        raise HTTPException(422, "Выберите файл TMX.")
    memory_id = existing_memory_id.strip() or str(uuid.uuid4())
    temporary = None
    try:
        if existing_memory_id.strip():
            metadata = append_tmx(document.file, memory_path(memory_id), source_language, target_language)
        else:
            temporary = memory_directory() / f"{memory_id}.partial"
            metadata = convert_tmx(document.file, temporary, name.strip() or Path(filename).stem,
                                   source_language, target_language, description.strip())
            temporary.rename(temporary.with_suffix(".sqlite"))
    except (ValueError, ParseError, DefusedXmlException) as error:
        raise HTTPException(422, str(error)) from error
    finally:
        document.file.close()
        if temporary:
            temporary.unlink(missing_ok=True)
    return dict(metadata, id=memory_id)


@router.post("/api/memories/{memory_id}/segments", status_code=201)
def create_segment(memory_id: str, payload: SegmentPayload, request: Request):
    require_memory_write_scope(request, memory_id)
    try:
        return add_segment(memory_path(memory_id), payload.source, payload.target, payload.tuid, payload.author)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.delete("/api/memories/{memory_id}/segments/{segment_id}", status_code=204)
def remove_segment(memory_id: str, segment_id: int, request: Request):
    require_memory_write_scope(request, memory_id)
    if not delete_segment(memory_path(memory_id), segment_id):
        raise HTTPException(404, "Сегмент не найден.")
    return Response(status_code=204)


@router.get("/api/memories/{memory_id}/search")
def search(memory_id: str, request: Request, q: str = Query("", max_length=10000), source_q: str = Query("", max_length=10000), target_q: str = Query("", max_length=10000),
           use_regex: bool = Query(False), respect_case: bool = Query(False),
           threshold: float = Query(70, ge=0, le=100), limit: int = Query(50, ge=1, le=200),
           mode: Literal["fuzzy", "words", "phrase", "all"] = Query("fuzzy")):
    require_memory_scope(request, memory_id)
    path = memory_path(memory_id)
    try:
        return {"results": search_memory(path, source_q or q, target_q, threshold, limit, mode, respect_case, use_regex), "limit": limit, "mode": mode}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/api/memories/{memory_id}/download")
def download(memory_id: str, request: Request):
    require_memory_scope(request, memory_id)
    path = memory_path(memory_id)
    checkpoint_database(path)
    return FileResponse(path, filename=f"memory-{memory_id}.sqlite", media_type="application/vnd.sqlite3")


@router.get("/api/memories/{memory_id}/download-tmx")
def download_tmx(memory_id: str, request: Request):
    require_memory_scope(request, memory_id)
    path = memory_path(memory_id)
    return StreamingResponse(
        stream_tmx(path),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="memory-{memory_id}.tmx"'},
    )
