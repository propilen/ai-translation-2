import json
import re
import time

import requests


class ModelError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_batch_prompt(segments: list[dict], source_lang: str, target_lang: str, glossary: list[dict] | None, instructions: str) -> str:
    parts = [
        instructions.strip(),
        "Inline XLIFF tags have been replaced with protected placeholders of the form [[XLF_TAG_0_0]]. Preserve every placeholder verbatim, exactly once, and in its original position. Do not output XML tags.",
        "Return one valid JSON object only: {\"translations\":[{\"id\":\"...\",\"text\":\"...\"}]}. Do not use Markdown code fences, comments, or any text outside this JSON object.",
        f"Source: {source_lang}. Target: {target_lang}.",
    ]
    if glossary:
        parts.append("Glossary (strict):")
        parts.extend(f'- "{item["source"]}" -> "{item["target"]}"' for item in glossary)
    parts.append("Segments to translate:")
    parts.append(json.dumps(segments, ensure_ascii=False))
    return "\n".join(parts)


class OpenAICompatibleClient:
    def __init__(self, api_url: str, model: str, api_key: str | None, timeout: int, retries: int = 3, max_tokens: int = 2000, temperature: float = 0.2, prompt: str = "") -> None:
        self.api_url, self.model, self.api_key = api_url, model, api_key
        self.timeout, self.retries, self.max_tokens = timeout, retries, max_tokens
        self.temperature, self.prompt = temperature, prompt
        self._resolved_model: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def available_models(self) -> list[dict]:
        models_url = self.api_url.rsplit("/chat/completions", 1)[0] + "/models"
        try:
            response = requests.get(models_url, headers=self._headers(), timeout=10, proxies={"http": None, "https": None})
            response.raise_for_status()
            models = response.json().get("data", [])
        except (requests.RequestException, ValueError) as error:
            raise ModelError(f"Не удалось подключиться к API модели: {error}") from error
        if not isinstance(models, list):
            raise ModelError("API модели вернул некорректный список моделей")
        return models

    def test_connection(self) -> str:
        models = self.available_models()
        model_ids = {item.get("id") for item in models if item.get("id")}
        if self.model == "auto":
            if not model_ids:
                raise ModelError("Подключение установлено, но в LM Studio не загружена модель.")
            if len(model_ids) > 1:
                raise ModelError("Подключение установлено, но загружено несколько моделей. Укажите модель явно.")
            return next(iter(model_ids))
        if self.model not in model_ids:
            raise ModelError(f"Подключение установлено, но модель «{self.model}» недоступна для этого API.")
        return self.model

    def _model_name(self) -> str:
        if self.model != "auto":
            return self.model
        if self._resolved_model:
            return self._resolved_model
        loaded_models = self.available_models()
        if not loaded_models:
            raise ModelError("В LM Studio не загружена модель. Загрузите её и запустите сервер API.")
        if len(loaded_models) > 1:
            raise ModelError("В LM Studio загружено несколько моделей. Укажите нужную в TRANSLATION_MODEL.")
        self._resolved_model = loaded_models[0]["id"]
        return self._resolved_model

    def translate(self, segments: list[dict], source_lang: str, target_lang: str, glossary: list[dict] | None) -> dict[str, str]:
        headers = self._headers()
        payload = {
            "model": self._model_name(),
            "messages": [{"role": "user", "content": build_batch_prompt(segments, source_lang, target_lang, glossary, self.prompt)}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        response = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.timeout, proxies={"http": None, "https": None})
                # A 504 is a completed gateway timeout. Retrying the same large
                # payload only waits for another timeout; the pipeline splits it.
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    break
                if response.status_code == 504:
                    response.raise_for_status()
                if attempt == self.retries:
                    response.raise_for_status()
                time.sleep(2 ** (attempt - 1))
            except requests.RequestException as error:
                status_code = error.response.status_code if getattr(error, "response", None) else None
                retryable = status_code in {429, 500, 502, 503} or status_code is None
                if attempt == self.retries or not retryable:
                    raise ModelError(f"Ошибка API модели после {attempt} попыток: {error}", status_code) from error
                time.sleep(2 ** (attempt - 1))
        try:
            content = response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, ValueError, TypeError) as error:
            raise ModelError("API модели вернул ответ без перевода") from error
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1)
        try:
            data = json.loads(content)
            translations = {item["id"]: item["text"] for item in data["translations"]}
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ModelError("Модель вернула ответ не в требуемом JSON-формате") from error
        missing = {item["id"] for item in segments} - set(translations)
        if missing:
            raise ModelError(f"Модель не вернула перевод сегментов: {', '.join(sorted(missing))}")
        return translations
