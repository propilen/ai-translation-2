from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import RLock
import json
import os


DEFAULT_PROMPT = """Translate every XLIFF segment exactly.
Never merge, split, omit, or reorder segments.
Protected inline placeholders such as [[XLF_TAG_0_0]] are not text: copy every one exactly once, without translating, moving, deleting, or modifying it.
When a Glossary (strict) is provided, use every listed target term exactly as specified."""
DEFAULT_WORKSPACE_ROOT = Path(os.getenv("TRANSLATION_WORKSPACE", r"C:\ai_trans"))


@dataclass(frozen=True)
class Settings:
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT
    tikal_exe: Path = Path(os.getenv("TIKAL_EXE", r"C:\Users\propi\Documents\Okapi\tikal.exe"))
    provider: str = os.getenv("TRANSLATION_PROVIDER", "lmstudio")
    api_url: str = os.getenv("TRANSLATION_API_URL", "http://192.168.2.105:1234/v1/chat/completions")
    model: str = os.getenv("TRANSLATION_MODEL", "auto")
    api_key: str | None = os.getenv("TRANSLATION_API_KEY")
    request_timeout: int = int(os.getenv("TRANSLATION_REQUEST_TIMEOUT", "180"))
    api_retries: int = int(os.getenv("TRANSLATION_API_RETRIES", "3"))
    batch_size: int = int(os.getenv("TRANSLATION_BATCH_SIZE", "5"))
    max_tokens: int = int(os.getenv("TRANSLATION_MAX_TOKENS", "2000"))
    temperature: float = float(os.getenv("TRANSLATION_TEMPERATURE", "0.2"))
    prompt: str = os.getenv("TRANSLATION_PROMPT", DEFAULT_PROMPT)


class SettingsManager:
    """Thread-safe, persistent settings for new translation jobs."""
    editable_fields = {"workspace_root", "provider", "api_url", "model", "api_key", "request_timeout", "api_retries", "batch_size", "max_tokens", "temperature", "prompt"}

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("TRANSLATION_SETTINGS_FILE", str(Settings().workspace_root / "service-settings.json")))
        self._settings = self._load()

    def _load(self) -> Settings:
        defaults = Settings()
        if not self._path.is_file():
            return defaults
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            valid = {key: value for key, value in data.items() if key in self.editable_fields}
            if valid.get("workspace_root"):
                valid["workspace_root"] = Path(valid["workspace_root"])
            return replace(defaults, **valid)
        except (OSError, ValueError, TypeError):
            return defaults

    def get(self) -> Settings:
        with self._lock:
            return self._settings

    def public(self) -> dict:
        current = self.get()
        data = {key: value for key, value in asdict(current).items() if key in self.editable_fields and key != "api_key"}
        data["workspace_root"] = str(current.workspace_root)
        data["api_key_configured"] = bool(current.api_key)
        return data

    def update(self, changes: dict) -> dict:
        with self._lock:
            values = {key: value for key, value in changes.items() if key in self.editable_fields and key != "api_key"}
            if "workspace_root" in values:
                values["workspace_root"] = Path(values["workspace_root"].strip()) if values["workspace_root"].strip() else DEFAULT_WORKSPACE_ROOT
            api_key = changes.get("api_key")
            if api_key:
                values["api_key"] = api_key
            elif changes.get("clear_api_key"):
                values["api_key"] = None
            self._settings = replace(self._settings, **values)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            stored = {key: value for key, value in asdict(self._settings).items() if key in self.editable_fields}
            stored["workspace_root"] = str(self._settings.workspace_root)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._path)
            return self.public()


runtime_settings = SettingsManager()
