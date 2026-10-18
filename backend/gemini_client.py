import json
import re
import time

import requests

from .model_client import ModelError, build_batch_prompt


class GeminiClient:
    """Adapter for Gemini's native generateContent REST API."""

    def __init__(self, api_url, model, api_key, timeout, retries=3, max_tokens=2000, temperature=0.2, prompt=""):
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.prompt = prompt

    def _headers(self):
        if not self.api_key:
            raise ModelError("Для Gemini API требуется API-ключ.")
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def _models_url(self):
        return f"{self.api_url}/models"

    def _generation_url(self):
        return f"{self.api_url}/models/{self.model}:generateContent"

    def available_models(self) -> list[dict]:
        try:
            response = requests.get(self._models_url(), headers=self._headers(), timeout=10, proxies={"http": None, "https": None})
            response.raise_for_status()
            models = response.json().get("models", [])
        except (requests.RequestException, ValueError) as error:
            raise ModelError(f"Не удалось подключиться к Gemini API: {error}") from error
        if not isinstance(models, list):
            raise ModelError("Gemini API вернул некорректный список моделей")
        return models

    def test_connection(self):
        models = self.available_models()
        names = {item.get("name", "").removeprefix("models/") for item in models}
        if self.model not in names:
            raise ModelError(f"Подключение установлено, но модель «{self.model}» недоступна для Gemini API.")
        return self.model

    def translate(self, segments, source_lang, target_lang, glossary):
        prompt = build_batch_prompt(segments, source_lang, target_lang, glossary, self.prompt)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "object",
                    "properties": {
                        "translations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "text": {"type": "string"},
                                },
                                "required": ["id", "text"],
                            },
                        },
                    },
                    "required": ["translations"],
                },
            },
        }
        response = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(self._generation_url(), headers=self._headers(), json=payload, timeout=self.timeout, proxies={"http": None, "https": None})
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    break
                if response.status_code == 504 or attempt == self.retries:
                    response.raise_for_status()
                time.sleep(2 ** (attempt - 1))
            except requests.RequestException as error:
                status_code = error.response.status_code if getattr(error, "response", None) else None
                if attempt == self.retries or status_code not in {None, 429, 500, 502, 503}:
                    raise ModelError(f"Ошибка Gemini API после {attempt} попыток: {error}", status_code) from error
                time.sleep(2 ** (attempt - 1))
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ModelError("Gemini API вернул ответ без перевода") from error
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1)
        try:
            translations = {item["id"]: item["text"] for item in json.loads(content)["translations"]}
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ModelError("Gemini вернул ответ не в требуемом JSON-формате") from error
        missing = {item["id"] for item in segments} - set(translations)
        if missing:
            raise ModelError(f"Gemini не вернул перевод сегментов: {', '.join(sorted(missing))}")
        return translations
