from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Condition, Lock


STAGE_LABELS = {
    "uploading": "Выполняется загрузка",
    "queued": "В очереди на перевод",
    "converting": "Выполняется конвертация в XLIFF",
    "translating": "Выполняется перевод",
    "exporting": "Выполняется экспорт перевода",
    "cancelling": "Выполняется отмена",
    "cancelled": "Отменено",
    "ready": "Готово",
    "failed": "Ошибка",
}


ERROR_STAGE_LABELS = {
    "uploading": "загрузка файла",
    "converting": "конвертация DOCX в XLIFF",
    "queued": "ожидание в очереди",
    "translating": "перевод сегментов моделью",
    "exporting": "экспорт перевода в DOCX",
}


def failure_hint(error: str, stage: str | None) -> str:
    """Return an actionable, non-technical first hint for a failed job."""
    message = error.lower()
    if "tikal" in message or "java" in message:
        return "Проверьте путь к tikal.exe, установку Java и доступность папок Okapi."
    if any(token in message for token in ("api модели", "gemini api", "gateway", "timeout", "timed out", "connection", "подключ")):
        return "Проверьте адрес API, модель, API-ключ, доступность сети и лимиты выбранного провайдера."
    if any(token in message for token in ("json", "inline-тег", "inline tag", "xliff")):
        return "Модель вернула ответ в неподходящем формате. Проверьте системный промт и попробуйте меньший размер партии сегментов."
    if "spacy" in message or "pymorphy" in message or "model" in message and "not found" in message:
        return "Проверьте установку языковых моделей spaCy и pymorphy3 на сервере."
    if "глоссар" in message or "tsv" in message or "utf-8" in message:
        return "Проверьте формат глоссария: TSV с двумя колонками и кодировкой UTF-8."
    if stage == "converting":
        return "Проверьте, что исходный DOCX не повреждён и может открываться в Microsoft Word."
    if stage == "exporting":
        return "Проверьте установку Okapi и наличие исходного DOCX в папке задания."
    return "Откройте технические сведения ниже и проверьте журнал сервера для полной диагностики."


class JobCancelled(Exception):
    pass


@dataclass
class TranslationJob:
    id: str
    directory: Path
    original_name: str
    source_language: str
    target_language: str
    glossary_path: Path | None = None
    filter_config: Path | None = None
    stage: str = "queued"
    progress_current: int = 0
    progress_total: int = 0
    progress_words_current: int = 0
    progress_words_total: int = 0
    queue_order: int = 0
    cancel_requested: bool = False
    error: str | None = None
    error_stage: str | None = None
    error_hint: str | None = None
    output_path: Path | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def public(self) -> dict:
        payload = asdict(self)
        payload["directory"] = str(self.directory)
        payload["glossary_path"] = str(self.glossary_path) if self.glossary_path else None
        payload["filter_config"] = str(self.filter_config) if self.filter_config else None
        payload["output_path"] = str(self.output_path) if self.output_path else None
        payload["created_at"] = self.created_at.isoformat()
        payload["status"] = STAGE_LABELS[self.stage]
        payload["error_stage_label"] = ERROR_STAGE_LABELS.get(self.error_stage or "", "")
        return payload


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, TranslationJob] = {}
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._next_queue_order = 0

    def add(self, job: TranslationJob) -> None:
        with self._condition:
            self._next_queue_order += 1
            job.queue_order = self._next_queue_order
            self._jobs[job.id] = job
            self._condition.notify()

    def _queued_locked(self) -> list[TranslationJob]:
        return sorted(
            (item for item in self._jobs.values() if item.stage == "queued"),
            key=lambda item: (item.queue_order, item.created_at),
        )

    def _prioritized_locked(self) -> list[TranslationJob]:
        return sorted(
            (item for item in self._jobs.values() if item.stage in {"converting", "queued"}),
            key=lambda item: (item.queue_order, item.created_at),
        )

    def take_next(self) -> str:
        """Wait for, claim and return the highest-priority pending job."""
        with self._condition:
            while True:
                queue = self._queued_locked()
                if queue:
                    job = queue[0]
                    # Claim the job before leaving the lock, so a priority change
                    # can never affect a translation that has already started.
                    job.stage = "translating"
                    return job.id
                self._condition.wait()

    def get(self, job_id: str) -> TranslationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: object) -> TranslationJob:
        with self._condition:
            job = self._jobs[job_id]
            next_stage = fields.get("stage")
            if job.cancel_requested and next_stage not in {None, "cancelling", "cancelled"}:
                return job
            for name, value in fields.items():
                setattr(job, name, value)
            if job.stage == "queued":
                self._condition.notify()
            return job

    def fail(self, job_id: str, error: Exception | str) -> TranslationJob:
        """Finish a job with diagnostics while preserving the stage that failed."""
        with self._condition:
            job = self._jobs[job_id]
            if job.cancel_requested:
                job.stage = "cancelled"
                return job
            failed_stage = job.stage if job.stage in ERROR_STAGE_LABELS else None
            message = str(error).strip() or error.__class__.__name__
            job.error_stage = failed_stage
            job.error = message
            job.error_hint = failure_hint(message, failed_stage)
            job.stage = "failed"
            return job

    def request_cancel(self, job_id: str) -> TranslationJob | None:
        with self._condition:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.stage in {"ready", "failed", "cancelled"}:
                return job
            job.cancel_requested = True
            job.stage = "cancelled" if job.stage == "queued" else "cancelling"
            self._condition.notify_all()
            return job

    def remove_cancelled(self, job_id: str) -> bool:
        """Hide a finished cancelled job from the shared list without touching its files."""
        with self._condition:
            job = self._jobs.get(job_id)
            if not job or job.stage != "cancelled":
                return False
            del self._jobs[job_id]
            self._condition.notify_all()
            return True

    def remove_ready(self, job_id: str) -> bool:
        """Remove a downloaded result from the in-memory list, keeping its files intact."""
        with self._condition:
            job = self._jobs.get(job_id)
            if not job or job.stage != "ready":
                return False
            del self._jobs[job_id]
            self._condition.notify_all()
            return True

    def move(self, job_id: str, direction: str) -> TranslationJob | None:
        """Swap a queued job with its neighbor and return the updated job."""
        with self._condition:
            job = self._jobs.get(job_id)
            if not job or job.stage not in {"converting", "queued"}:
                return None
            queue = self._prioritized_locked()
            index = queue.index(job)
            target_index = index - 1 if direction == "up" else index + 1
            if direction not in {"up", "down"} or not 0 <= target_index < len(queue):
                return job
            other = queue[target_index]
            job.queue_order, other.queue_order = other.queue_order, job.queue_order
            self._condition.notify_all()
            return job

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancel_requested)

    def public(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            data = job.public()
            if job.stage in {"converting", "queued"}:
                queue = self._prioritized_locked()
                data["queue_position"] = queue.index(job) + 1
            return data

    def queue(self) -> list[dict]:
        with self._lock:
            active = [
                item for item in self._jobs.values()
                if item.stage in {"translating", "exporting", "cancelling"}
            ]
            active.sort(key=lambda item: item.created_at)
            queued = self._prioritized_locked()
            finished = [
                item for item in self._jobs.values()
                if item.stage in {"ready", "failed", "cancelled"}
            ]
            finished.sort(key=lambda item: item.created_at, reverse=True)
            result = [item.public() for item in active]
            for position, item in enumerate(queued, start=1):
                data = item.public()
                data["queue_position"] = position
                result.append(data)
            result.extend(item.public() for item in finished)
            return result

    def pending_count(self) -> int:
        with self._lock:
            return sum(
                item.stage in {"converting", "queued", "translating", "exporting", "cancelling"}
                for item in self._jobs.values()
            )


jobs = JobRegistry()
