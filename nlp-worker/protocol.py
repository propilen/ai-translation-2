"""Validation and dispatch for the line-oriented NLP worker protocol."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from backend import nlp_glossary as nlp


class ProtocolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class PreparedGlossary:
    lang: str
    terms: list[dict]


class WorkerProtocol:
    def __init__(self):
        self.glossaries: dict[str, PreparedGlossary] = {}

    @staticmethod
    def _string(request: dict, name: str, *, nonempty: bool = False) -> str:
        value = request.get(name)
        if not isinstance(value, str) or (nonempty and not value.strip()):
            raise ProtocolError("INVALID_REQUEST", f"'{name}' must be a string" + (" and nonempty" if nonempty else ""))
        return value

    @staticmethod
    def _texts(request: dict) -> list[str]:
        texts = request.get("texts")
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise ProtocolError("INVALID_REQUEST", "'texts' must be an array of strings")
        return texts

    @staticmethod
    def _lang(request: dict) -> str:
        lang = WorkerProtocol._string(request, "lang", nonempty=True).lower()
        if lang not in {"ru", "en", "de"}:
            raise ProtocolError("UNSUPPORTED_LANGUAGE", f"Unsupported language: {lang}")
        return lang

    @staticmethod
    def _threshold(request: dict) -> float:
        value = request.get("threshold", 0.86)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ProtocolError("INVALID_THRESHOLD", "'threshold' must be a finite number between 0 and 1")
        return float(value)

    @staticmethod
    def _ensure_model(lang: str) -> None:
        current = {"ru": nlp.morph_ru, "en": nlp.nlp_en, "de": nlp.nlp_de}[lang]
        if current is None:
            try:
                nlp.init_nlp(lang)
            except Exception as error:
                raise ProtocolError("NLP_MODEL_ERROR", f"Could not load {lang} NLP model: {error}") from error

    def _glossary(self, request: dict) -> PreparedGlossary:
        glossary_id = self._string(request, "glossary_id", nonempty=True)
        glossary = self.glossaries.get(glossary_id)
        if glossary is None:
            raise ProtocolError("GLOSSARY_NOT_FOUND", f"Glossary '{glossary_id}' is not loaded")
        return glossary

    def dispatch(self, request: object) -> tuple[dict, bool]:
        if not isinstance(request, dict):
            raise ProtocolError("INVALID_REQUEST", "Request must be a JSON object")
        request_id = request.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)) or request_id == "":
            raise ProtocolError("INVALID_REQUEST", "'id' must be a nonempty string or integer")
        action = self._string(request, "action", nonempty=True)
        result: dict = {"id": request_id, "ok": True}

        if action == "ping":
            result["status"] = "ready"
        elif action == "shutdown":
            result["status"] = "shutdown"
            return result, True
        elif action in {"lemmatize", "lemmatize_batch"}:
            lang = self._lang(request)
            texts = [self._string(request, "text")] if action == "lemmatize" else self._texts(request)
            self._ensure_model(lang)
            lemmas = [nlp.lemmatize(text, lang) for text in texts]
            result["lemmas"] = lemmas[0] if action == "lemmatize" else lemmas
        elif action == "load_glossary":
            glossary_id = self._string(request, "glossary_id", nonempty=True)
            lang = self._lang(request)
            path = Path(self._string(request, "path", nonempty=True))
            self._ensure_model(lang)
            try:
                # Prepare a complete replacement before touching the live glossary.
                terms = nlp.load_glossary(path, lang)
            except FileNotFoundError as error:
                raise ProtocolError("GLOSSARY_FILE_NOT_FOUND", f"TSV file not found: {path}") from error
            except OSError as error:
                raise ProtocolError("GLOSSARY_READ_ERROR", f"Could not read TSV file: {error}") from error
            except UnicodeError as error:
                raise ProtocolError("GLOSSARY_READ_ERROR", f"Could not decode TSV file: {error}") from error
            self.glossaries[glossary_id] = PreparedGlossary(lang, terms)
            result["count"] = len(terms)
        elif action in {"find_terms", "find_terms_batch"}:
            glossary = self._glossary(request)
            lang = self._lang(request)
            if glossary.lang != lang:
                raise ProtocolError("LANGUAGE_MISMATCH", f"Glossary is loaded for {glossary.lang}, not {lang}")
            threshold = self._threshold(request)
            texts = [self._string(request, "text")] if action == "find_terms" else self._texts(request)
            matches = [nlp.find_glossary_terms(text, lang, glossary.terms, threshold) or [] for text in texts]
            result["terms"] = matches[0] if action == "find_terms" else matches
        elif action == "unload_glossary":
            glossary_id = self._string(request, "glossary_id", nonempty=True)
            self._glossary(request)
            del self.glossaries[glossary_id]
            result["unloaded"] = True
        else:
            raise ProtocolError("UNKNOWN_ACTION", f"Unknown action: {action}")
        return result, False
