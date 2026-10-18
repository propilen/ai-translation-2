from pathlib import Path
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import runtime_settings
from .memory_api import memory_path, router as memory_router
from .openxml_options import (analyse_word_document, create_word_template,
                              delete_word_template, openxml_options,
                              resolve_word_template, word_template_options,
                              word_templates)
from .auth import (authenticate, authenticate_api_key, create_api_key, create_session, create_user, get_user,
                   initialize_database, list_all_api_keys, list_api_keys, list_users, read_session, revoke_api_key,
                   revoke_api_key_admin, update_api_key_admin, update_user_access)
from .gemini_client import GeminiClient
from .jobs import TranslationJob, jobs
from .model_client import ModelError, OpenAICompatibleClient
from .pipeline import prepare_translation, run_translation
from .storage import create_batch_directory, create_batch_job_directory, create_job_directory, save_upload


ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="LinguaFlow")
app.include_router(memory_router)
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
SESSION_COOKIE = "linguaflow_session"
pending_settings: dict[str, object] = {}
pending_settings_lock = Lock()
# Conversion is CPU/light I/O work and can run ahead of the single LLM translator.
conversion_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="xliff-conversion")


class SettingsPayload(BaseModel):
    workspace_root: str = Field(default="", max_length=1000)
    provider: str = Field(pattern="^(lmstudio|openai|gemini)$")
    api_url: str = Field(min_length=10, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    request_timeout: int = Field(ge=10, le=900)
    api_retries: int = Field(ge=0, le=10)
    batch_size: int = Field(ge=1, le=10)
    max_tokens: int = Field(ge=128, le=16000)
    temperature: float = Field(ge=0, le=2)
    prompt: str = Field(min_length=20, max_length=12000)

    @field_validator("api_url")
    @classmethod
    def endpoint_must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("Укажите адрес, начинающийся с http:// или https://")
        return value.rstrip("/")


class OpenXmlOptionsPayload(BaseModel):
    values: dict[str, object]
    template_name: str = Field(default="copy-of-default", min_length=1, max_length=120)


class CreateOpenXmlTemplatePayload(BaseModel):
    template_name: str = Field(min_length=1, max_length=120)
    base_template_id: str = Field(default="", max_length=180)


class QueueMovePayload(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CreateApiKeyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    memory_id: str | None = Field(default=None, max_length=36)


class UpdateApiKeyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    memory_id: str | None = Field(default=None, max_length=36)
    can_read: bool = True
    can_write: bool = False
    secret: str | None = Field(default=None, max_length=500)


class CreateUserPayload(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class UpdateUserAccessPayload(BaseModel):
    can_access_settings: bool = False
    can_manage_filters: bool = False
    password: str | None = Field(default=None, max_length=256)


@app.on_event("startup")
def initialize_service() -> None:
    initialize_database()


@app.middleware("http")
async def require_login(request: Request, call_next):
    public_paths = {"/login", "/login.css", "/api/auth/login"}
    if request.url.path in public_paths:
        return await call_next(request)
    user = read_session(request.cookies.get(SESSION_COOKIE))
    api_key_authenticated = False
    if not user and request.url.path.startswith("/api/"):
        authorization = request.headers.get("authorization", "")
        raw_key = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else request.headers.get("x-api-key")
        user = authenticate_api_key(raw_key)
        api_key_authenticated = bool(user)
        if raw_key and not user:
            return JSONResponse({"detail": "Недействительный API-ключ."}, status_code=401)
    if not user:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Требуется вход в сервис."}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)
    if api_key_authenticated:
        if not request.url.path.startswith("/api/memories"):
            return JSONResponse({"detail": "API-ключ действует только для памяти переводов."}, status_code=403)
        can_read = user.get("api_key_can_read", True)
        can_write = user.get("api_key_can_write", False)
        if request.method in {"GET", "HEAD"} and not can_read:
            return JSONResponse({"detail": "У API-ключа нет права чтения памяти переводов."}, status_code=403)
        if request.method not in {"GET", "HEAD"} and not can_write:
            return JSONResponse({"detail": "У API-ключа нет права записи в память переводов."}, status_code=403)
    api_key_memory_id = user.get("api_key_memory_id") if api_key_authenticated else None
    api_key_can_read = user.get("api_key_can_read", True) if api_key_authenticated else False
    api_key_can_write = user.get("api_key_can_write", False) if api_key_authenticated else False
    user = get_user(user["id"]) or user
    if api_key_authenticated:
        user["api_key_authenticated"] = True
        user["api_key_memory_id"] = api_key_memory_id
        user["api_key_can_read"] = api_key_can_read
        user["api_key_can_write"] = api_key_can_write
    admin_only = (
        request.url.path == "/admin"
        or request.url.path == "/admin.css"
        or request.url.path.startswith("/api/admin/")
    )
    if admin_only and not user["is_admin"]:
        return JSONResponse({"detail": "Раздел доступен только администратору."}, status_code=403)
    settings_area = request.url.path in {"/settings.html", "/settings.css"} or request.url.path.startswith("/api/settings")
    filters_area = request.url.path in {"/openxml-word-options.html", "/openxml-excel-options.html", "/openxml-powerpoint-options.html", "/openxml-options.css", "/openxml-options.js"} or request.url.path.startswith("/api/openxml-options")
    if settings_area and not (user["is_admin"] or user.get("can_access_settings")):
        return JSONResponse({"detail": "Нет доступа к настройкам перевода."}, status_code=403)
    if filters_area and not (user["is_admin"] or user.get("can_manage_filters")):
        return JSONResponse({"detail": "Нет права на создание фильтров."}, status_code=403)
    request.state.user = user
    return await call_next(request)


def require_admin(request: Request) -> dict:
    user = request.state.user
    if not user["is_admin"]:
        raise HTTPException(403, "Раздел доступен только администратору.")
    return user


def process_translation_queue() -> None:
    """One persistent worker takes jobs in the order managed by JobRegistry."""
    while True:
        job_id = jobs.take_next()
        with pending_settings_lock:
            settings = pending_settings.get(job_id)
        if settings is not None:
            try:
                run_translation(job_id, settings)
            finally:
                with pending_settings_lock:
                    pending_settings.pop(job_id, None)


def prepare_job(job_id: str, settings: object) -> None:
    prepare_translation(job_id, settings)
    job = jobs.get(job_id)
    if job and job.stage in {"cancelled", "failed"}:
        with pending_settings_lock:
            pending_settings.pop(job_id, None)


Thread(target=process_translation_queue, name="translation-queue", daemon=True).start()


@app.get("/")
def index():
    return FileResponse(ROOT / "translate.html")


@app.get("/login")
def login_page(request: Request):
    if read_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(ROOT / "login.html")


@app.get("/login.css")
def login_stylesheet():
    return FileResponse(ROOT / "login.css", media_type="text/css")


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, response: Response):
    user = authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(401, "Неверное имя пользователя или пароль.")
    response.set_cookie(
        SESSION_COOKIE,
        create_session(user),
        max_age=60 * 60 * 12,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"user": user}


@app.get("/api/auth/api-keys")
def api_keys(request: Request):
    return {"keys": list_api_keys(request.state.user["id"])}


@app.post("/api/auth/api-keys", status_code=201)
def create_new_api_key(payload: CreateApiKeyPayload, request: Request):
    try:
        if payload.memory_id:
            memory_path(payload.memory_id)
        key, secret = create_api_key(request.state.user["id"], payload.name, payload.memory_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"key": key, "secret": secret}


@app.delete("/api/auth/api-keys/{key_id}", status_code=204)
def delete_api_key(key_id: int, request: Request):
    if not revoke_api_key(request.state.user["id"], key_id):
        raise HTTPException(404, "API-ключ не найден")


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.get("/api/auth/me")
def current_user(request: Request):
    return {"user": request.state.user}


@app.get("/admin")
def admin_page(request: Request):
    require_admin(request)
    return FileResponse(ROOT / "admin.html")


@app.get("/admin.css")
def admin_stylesheet():
    return FileResponse(ROOT / "admin.css", media_type="text/css")


@app.get("/app-navigation.js")
def app_navigation_script():
    return FileResponse(ROOT / "app-navigation.js", media_type="application/javascript")


@app.get("/app-nav.css")
def app_navigation_stylesheet():
    return FileResponse(ROOT / "app-nav.css", media_type="text/css")


@app.get("/api/admin/memory-api-keys")
def admin_memory_api_keys(request: Request):
    require_admin(request)
    return {"keys": list_all_api_keys()}


@app.post("/api/admin/memory-api-keys", status_code=201)
def admin_create_memory_api_key(payload: CreateApiKeyPayload, request: Request):
    admin = require_admin(request)
    try:
        if payload.memory_id:
            memory_path(payload.memory_id)
        key, secret = create_api_key(admin["id"], payload.name, payload.memory_id)
    except (ValueError, HTTPException) as error:
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(422, str(error)) from error
    return {"key": key, "secret": secret}


@app.put("/api/admin/memory-api-keys/{key_id}")
def admin_update_memory_api_key(key_id: int, payload: UpdateApiKeyPayload, request: Request):
    require_admin(request)
    try:
        if payload.memory_id:
            memory_path(payload.memory_id)
        key, secret = update_api_key_admin(key_id, payload.name, payload.memory_id, payload.can_read, payload.can_write, payload.secret)
    except (ValueError, HTTPException) as error:
        if isinstance(error, HTTPException):
            raise error
        raise HTTPException(422, str(error)) from error
    return {"key": key, "secret": secret}


@app.delete("/api/admin/memory-api-keys/{key_id}", status_code=204)
def admin_delete_memory_api_key(key_id: int, request: Request):
    require_admin(request)
    if not revoke_api_key_admin(key_id):
        raise HTTPException(404, "API-ключ не найден")


@app.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    return {"users": list_users()}


@app.post("/api/admin/users", status_code=201)
def admin_create_user(payload: CreateUserPayload, request: Request):
    require_admin(request)
    try:
        user = create_user(payload.username, payload.password)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"user": user}


@app.get("/api/admin/users/{user_id}")
def admin_user_card(user_id: int, request: Request):
    require_admin(request)
    user = get_user(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден.")
    return {"user": user}


@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: UpdateUserAccessPayload, request: Request):
    require_admin(request)
    try:
        return {"user": update_user_access(user_id, payload.can_access_settings, payload.can_manage_filters, payload.password)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/translate.css")
def stylesheet():
    return FileResponse(ROOT / "translate.css", media_type="text/css")


@app.get("/settings.html")
def settings_page():
    return FileResponse(ROOT / "settings.html")


@app.get("/settings.css")
def settings_stylesheet():
    return FileResponse(ROOT / "settings.css", media_type="text/css")


@app.get("/settings-layout.css")
def settings_layout_stylesheet():
    return FileResponse(ROOT / "settings-layout.css", media_type="text/css")


@app.get("/settings-layout.js")
def settings_layout_script():
    return FileResponse(ROOT / "settings-layout.js", media_type="application/javascript")


@app.get("/openxml-word-options.html")
def openxml_word_options_page():
    return FileResponse(ROOT / "openxml-word-options.html")


@app.get("/openxml-excel-options.html")
def openxml_excel_options_page():
    return FileResponse(ROOT / "openxml-excel-options.html")


@app.get("/openxml-powerpoint-options.html")
def openxml_powerpoint_options_page():
    return FileResponse(ROOT / "openxml-powerpoint-options.html")


@app.get("/openxml-options.css")
def openxml_options_stylesheet():
    return FileResponse(ROOT / "openxml-options.css", media_type="text/css")


@app.get("/openxml-options.js")
def openxml_options_script():
    return FileResponse(ROOT / "openxml-options.js", media_type="application/javascript")


@app.get("/api/openxml-options")
def get_openxml_options(template_id: str = ""):
    try:
        return word_template_options(template_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@app.put("/api/openxml-options")
def update_openxml_options(payload: OpenXmlOptionsPayload):
    try:
        return openxml_options.save_template(payload.template_name, payload.values)
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(422, f"Не удалось сохранить конфигурацию OpenXML: {error}") from error


@app.post("/api/openxml-options/templates")
def create_openxml_template(payload: CreateOpenXmlTemplatePayload):
    try:
        return create_word_template(payload.template_name, payload.base_template_id)
    except (OSError, ValueError) as error:
        raise HTTPException(422, f"Не удалось создать шаблон OpenXML: {error}") from error


@app.delete("/api/openxml-options/templates/{template_id}")
def delete_openxml_template(template_id: str):
    try:
        delete_word_template(template_id)
        return {"deleted": template_id}
    except (OSError, ValueError) as error:
        raise HTTPException(422, f"Не удалось удалить шаблон OpenXML: {error}") from error


@app.post("/api/openxml-options/analyze")
async def analyse_openxml_word(document: UploadFile = File(...)):
    if not (document.filename or "").lower().endswith(".docx"):
        raise HTTPException(422, "Выберите файл DOCX.")
    from tempfile import NamedTemporaryFile
    try:
        with NamedTemporaryFile(suffix=".docx", delete=False) as temporary:
            temporary.write(await document.read())
            temporary_path = Path(temporary.name)
        return analyse_word_document(temporary_path)
    except (OSError, ValueError, ET.ParseError) as error:
        raise HTTPException(422, f"Не удалось прочитать DOCX: {error}") from error
    finally:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)


@app.get("/api/settings")
def get_settings():
    return runtime_settings.public()


@app.put("/api/settings")
def update_settings(payload: SettingsPayload):
    return runtime_settings.update(payload.model_dump())


@app.post("/api/settings/test")
def test_settings_connection(payload: SettingsPayload):
    saved = runtime_settings.get()
    client_class = GeminiClient if payload.provider == "gemini" else OpenAICompatibleClient
    client = client_class(
        payload.api_url, payload.model, payload.api_key or saved.api_key,
        payload.request_timeout, payload.api_retries, payload.max_tokens,
        payload.temperature, payload.prompt,
    )
    try:
        raw_models = client.available_models()
    except ModelError as error:
        raise HTTPException(422, str(error)) from error
    key = "name" if payload.provider == "gemini" else "id"
    models = sorted({
        str(item.get(key, "")).removeprefix("models/")
        for item in raw_models
        if isinstance(item, dict) and item.get(key)
    })
    if not models:
        return {
            "connected": True,
            "models": [],
            "suggested_model": None,
            "message": "Подключение установлено, но API не вернул список моделей. Укажите модель вручную.",
        }
    current_model_available = payload.model in models or (payload.model == "auto" and len(models) == 1)
    message = f"Подключение установлено. Доступно моделей: {len(models)}."
    if not current_model_available:
        message += " Выберите модель из загруженного списка."
    return {
        "connected": True,
        "models": models,
        "suggested_model": models[0] if len(models) == 1 else None,
        "message": message,
    }


@app.post("/api/jobs", status_code=202)
def create_job(
    document: UploadFile = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    word_template: str = Form(""),
    glossary: UploadFile | None = File(None),
):
    if source_language not in {"ru", "en", "de"} or target_language not in {"ru", "en", "de"}:
        raise HTTPException(422, "Поддерживаются только русский, английский и немецкий языки.")
    if source_language == target_language:
        raise HTTPException(422, "Язык оригинала и язык перевода не должны совпадать.")
    original_name = Path(document.filename or "").name
    if not original_name.lower().endswith(".docx"):
        raise HTTPException(422, "Нужен документ в формате DOCX.")
    if glossary and not Path(glossary.filename or "").name.lower().endswith(".tsv"):
        raise HTTPException(422, "Глоссарий должен быть в формате TSV.")

    try:
        filter_config = resolve_word_template(word_template)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    current_settings = runtime_settings.get()
    job_id, directory = create_job_directory(current_settings.workspace_root)
    save_upload(document, directory / "in" / original_name)
    glossary_path = None
    if glossary:
        glossary_path = directory / "gloss" / Path(glossary.filename).name
        save_upload(glossary, glossary_path)
    job = TranslationJob(job_id, directory, original_name, source_language, target_language, glossary_path, filter_config, stage="converting")
    with pending_settings_lock:
        pending_settings[job_id] = current_settings
    jobs.add(job)
    conversion_executor.submit(prepare_job, job_id, current_settings)
    return jobs.public(job_id)


@app.get("/api/word-templates")
def get_word_templates():
    return {"templates": word_templates()}


@app.post("/api/jobs/batch", status_code=202)
def create_batch_jobs(
    documents: list[UploadFile] = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    word_template: str = Form(""),
    glossary: UploadFile | None = File(None),
):
    if source_language not in {"ru", "en", "de"} or target_language not in {"ru", "en", "de"}:
        raise HTTPException(422, "Поддерживаются только русский, английский и немецкий языки.")
    if source_language == target_language:
        raise HTTPException(422, "Язык оригинала и язык перевода не должны совпадать.")
    if not documents:
        raise HTTPException(422, "Добавьте хотя бы один документ DOCX.")
    names = [Path(document.filename or "").name for document in documents]
    if any(not name.lower().endswith(".docx") for name in names):
        raise HTTPException(422, "Каждый документ должен быть в формате DOCX.")
    if glossary and not Path(glossary.filename or "").name.lower().endswith(".tsv"):
        raise HTTPException(422, "Глоссарий должен быть в формате TSV.")

    try:
        filter_config = resolve_word_template(word_template)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    current_settings = runtime_settings.get()
    batch_id, batch_directory = create_batch_directory(current_settings.workspace_root)
    glossary_path = None
    if glossary:
        glossary_path = batch_directory / "gloss" / Path(glossary.filename).name
        save_upload(glossary, glossary_path)

    created_jobs = []
    for index, (document, original_name) in enumerate(zip(documents, names), start=1):
        directory = create_batch_job_directory(batch_directory, index, original_name)
        save_upload(document, directory / "in" / original_name)
        job_id = f"{batch_id}_{index:03d}"
        job = TranslationJob(job_id, directory, original_name, source_language, target_language, glossary_path, filter_config, stage="converting")
        with pending_settings_lock:
            pending_settings[job_id] = current_settings
        jobs.add(job)
        conversion_executor.submit(prepare_job, job_id, current_settings)
        created_jobs.append(jobs.public(job_id))
    return {"batch_id": batch_id, "jobs": created_jobs}


@app.get("/api/queue")
def queue_status():
    return {"jobs": jobs.queue(), "in_progress": jobs.pending_count()}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    data = jobs.public(job_id)
    if not data:
        raise HTTPException(404, "Задание не найдено")
    return data


@app.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str):
    job = jobs.request_cancel(job_id)
    if not job:
        raise HTTPException(404, "Задание не найдено")
    if job.stage in {"ready", "failed"}:
        raise HTTPException(409, "Это задание уже нельзя отменить")
    if job.stage == "cancelled":
        with pending_settings_lock:
            pending_settings.pop(job_id, None)
    return jobs.public(job_id)


@app.delete("/api/jobs/{job_id}/record", status_code=204)
def remove_cancelled_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задание не найдено")
    if job.stage != "cancelled":
        raise HTTPException(409, "Удалить из списка можно только отменённое задание")
    jobs.remove_cancelled(job_id)


@app.post("/api/jobs/{job_id}/priority")
def move_job(job_id: str, payload: QueueMovePayload):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задание не найдено")
    if job.stage not in {"converting", "queued"}:
        raise HTTPException(409, "Приоритет можно менять только у заданий в очереди")
    jobs.move(job_id, payload.direction)
    return {"jobs": jobs.queue()}


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job.stage != "ready" or not job.output_path or not job.output_path.is_file():
        raise HTTPException(404, "Готовый перевод пока недоступен")
    response = FileResponse(job.output_path, filename=job.output_path.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    jobs.remove_ready(job_id)
    return response
