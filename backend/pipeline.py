from itertools import islice
from pathlib import Path
import re

from .config import Settings
from .jobs import JobCancelled, jobs
from .gemini_client import GeminiClient
from .model_client import ModelError, OpenAICompatibleClient
from .nlp_glossary import find_glossary_terms, init_nlp, load_glossary
from .tikal import TikalCancelled, TikalClient
from .xliff import XliffDocument


INLINE_TAG = re.compile(r"<[^>]+>")
UNESCAPED_AMPERSAND = re.compile(r"&(?!#(?:x[0-9A-Fa-f]+|[0-9]+);|[A-Za-z][A-Za-z0-9]+;)")


def protect_inline_tags(value: str, segment_number: int) -> tuple[str, list[tuple[str, str]]]:
    """Replace XML codes with opaque markers so the model cannot corrupt markup."""
    protected: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        token = f"[[XLF_TAG_{segment_number}_{len(protected)}]]"
        protected.append((token, match.group(0)))
        return token

    return INLINE_TAG.sub(replace, value), protected


def restore_inline_tags(value: str, protected: list[tuple[str, str]]) -> str:
    """Restore codes only if the model returned the complete ordered marker set."""
    expected = [token for token, _ in protected]
    actual = re.findall(r"\[\[XLF_TAG_\d+_\d+\]\]", value)
    if actual != expected:
        raise ModelError("Модель изменила защищённые inline-маркеры XLIFF")
    for token, tag in protected:
        value = value.replace(token, tag)
    # Plain text from a model may contain an ampersand; it must be XML-escaped.
    return UNESCAPED_AMPERSAND.sub("&amp;", value)


def batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def assert_not_cancelled(job_id):
    if jobs.is_cancel_requested(job_id):
        raise JobCancelled()


def word_count(text: str) -> int:
    """Count visible words in an XLIFF segment, excluding inline XML tags."""
    return len(re.findall(r"[^\W_]+(?:[’'-][^\W_]+)*", text, flags=re.UNICODE))


def translate_batch(client, segments, source_language, target_language, glossary, job_id):
    """Retrying a batch is handled by the client; split only persistent gateway failures."""
    assert_not_cancelled(job_id)
    batch_glossary = []
    for segment in segments:
        batch_glossary.extend(find_glossary_terms(segment.source_text, source_language, glossary) or [])
    unique_glossary = {(term["source"], term["target"]): term for term in batch_glossary}
    protected_by_id: dict[str, list[tuple[str, str]]] = {}
    request_segments = []
    for number, segment in enumerate(segments):
        text, protected = protect_inline_tags(segment.source_xml, number)
        protected_by_id[segment.id] = protected
        request_segments.append({"id": segment.id, "text": text})
    try:
        result = client.translate(request_segments, source_language, target_language, list(unique_glossary.values()) or None)
        assert_not_cancelled(job_id)
        return {segment_id: restore_inline_tags(text, protected_by_id[segment_id]) for segment_id, text in result.items()}
    except ModelError as error:
        if len(segments) == 1 or error.status_code not in {429, 500, 502, 503, 504, None}:
            raise
        midpoint = len(segments) // 2
        left = translate_batch(client, segments[:midpoint], source_language, target_language, glossary, job_id)
        right = translate_batch(client, segments[midpoint:], source_language, target_language, glossary, job_id)
        return left | right


def prepare_translation(job_id: str, settings: Settings) -> None:
    """Extract DOCX to XLIFF and calculate word totals before the translation slot is free."""
    job = jobs.get(job_id)
    if not job:
        return
    try:
        assert_not_cancelled(job_id)
        tikal = TikalClient(settings.tikal_exe, job.filter_config)
        jobs.update(job_id, stage="converting")
        assert_not_cancelled(job_id)
        source_docx = job.directory / "in" / job.original_name
        xliff_path = tikal.extract(source_docx, job.directory / "xliff", job.source_language, job.target_language, lambda: jobs.is_cancel_requested(job_id))
        document = XliffDocument(xliff_path)
        segments = document.segments()
        words_by_segment = {segment.id: word_count(segment.source_text) for segment in segments}
        assert_not_cancelled(job_id)
        jobs.update(
            job_id,
            progress_current=0,
            progress_total=len(segments),
            progress_words_current=0,
            progress_words_total=sum(words_by_segment.values()),
            stage="queued",
        )
    except (JobCancelled, TikalCancelled):
        jobs.update(job_id, stage="cancelled")
    except Exception as error:
        jobs.fail(job_id, error)


def run_translation(job_id: str, settings: Settings) -> None:
    """Translate a prepared XLIFF; only one instance of this function runs at a time."""
    job = jobs.get(job_id)
    if not job:
        return
    try:
        assert_not_cancelled(job_id)
        xliff_path = job.directory / "xliff" / f"{job.original_name}.xlf"
        if not xliff_path.is_file():
            raise FileNotFoundError(f"Не найден подготовленный XLIFF: {xliff_path}")
        init_nlp(job.source_language)
        glossary = load_glossary(job.glossary_path, job.source_language)
        document = XliffDocument(xliff_path)
        segments = document.segments()
        words_by_segment = {segment.id: word_count(segment.source_text) for segment in segments}
        client_class = GeminiClient if settings.provider == "gemini" else OpenAICompatibleClient
        client = client_class(
            settings.api_url, settings.model, settings.api_key,
            settings.request_timeout, settings.api_retries, settings.max_tokens,
            settings.temperature, settings.prompt,
        )

        for current_batch in batches(segments, settings.batch_size):
            translations = translate_batch(client, current_batch, job.source_language, job.target_language, glossary, job_id)
            for segment in current_batch:
                document.apply(segment, translations[segment.id])
            document.save()
            current_job = jobs.get(job_id)
            jobs.update(
                job_id,
                progress_current=current_job.progress_current + len(current_batch),
                progress_words_current=current_job.progress_words_current + sum(
                    words_by_segment[segment.id] for segment in current_batch
                ),
            )

        jobs.update(job_id, stage="exporting")
        assert_not_cancelled(job_id)
        tikal = TikalClient(settings.tikal_exe, job.filter_config)
        output = tikal.merge(xliff_path, job.directory / "in", job.directory / "out", job.source_language, job.target_language, lambda: jobs.is_cancel_requested(job_id))
        assert_not_cancelled(job_id)
        jobs.update(job_id, stage="ready", output_path=output)
    except (JobCancelled, TikalCancelled):
        jobs.update(job_id, stage="cancelled")
    except Exception as error:
        jobs.fail(job_id, error)
