"""Small optional domain-word layer kept separate from pymorphy dictionaries."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class DomainWord:
    forms: tuple[str, ...]
    pos: str | None = None
    gender: str | None = None
    number: str | None = None
    indeclinable: bool = False


DEFAULT_DOMAIN_WORDS = {
    "wi-fi": DomainWord(("Wi-Fi",), pos="NOUN", gender="Masc", indeclinable=True),
    "bluetooth": DomainWord(("Bluetooth",), pos="NOUN", gender="Masc", indeclinable=True),
    "gps": DomainWord(("GPS",), pos="PROPN", indeclinable=True),
}


class DomainLexicon:
    def __init__(self, words: dict[str, DomainWord] | None = None):
        self._words = {key.casefold(): value for key, value in (words or DEFAULT_DOMAIN_WORDS).items()}

    def lookup(self, form: str) -> DomainWord | None:
        return self._words.get(form.casefold())

    @classmethod
    def from_json(cls, path: str | Path) -> "DomainLexicon":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        words = {}
        for form, value in raw.items():
            forms = tuple(value.get("forms", [form]))
            words[form] = DomainWord(forms, value.get("pos"), value.get("gender"), value.get("number"), bool(value.get("indeclinable", False)))
        return cls(words)
