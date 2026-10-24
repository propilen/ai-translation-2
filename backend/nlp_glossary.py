"""Лемматизация и поиск терминов.

Логика сохранена из проверенного gemma-lemma-commented_gemma4.py; изменён
только способ передачи настроек: вместо глобального ctx используются аргументы.
"""
import difflib
import re
from pathlib import Path

import pymorphy3
import spacy

morph_ru = None
nlp_en = None
nlp_de = None
nlp_ru = None


def init_nlp(source_lang: str):
    global morph_ru, nlp_en, nlp_de
    source_lang = source_lang.lower()
    if source_lang == "ru":
        morph_ru = pymorphy3.MorphAnalyzer()
    elif source_lang == "en":
        nlp_en = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    elif source_lang == "de":
        nlp_de = spacy.load("de_core_news_sm", disable=["parser", "ner"])
    else:
        raise ValueError("source_lang must be en/de/ru")


def tokenize_ru(text):
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text.lower())


def lemmatize_ru(text):
    return [morph_ru.parse(w)[0].normal_form for w in tokenize_ru(text)]


def lemmatize_en(text):
    doc = nlp_en(text.lower())
    return [t.lemma_.lower() for t in doc if not t.is_punct and not t.is_space]


def lemmatize_de(text):
    doc = nlp_de(text.lower())
    return [t.lemma_.lower() for t in doc if not t.is_punct and not t.is_space]


def lemmatize(text, lang):
    lang = lang.lower()
    if lang == "ru":
        return lemmatize_ru(text)
    if lang == "en":
        return lemmatize_en(text)
    if lang == "de":
        return lemmatize_de(text)
    raise ValueError("lang must be en/de/ru")


def ensure_ru_grammar():
    global morph_ru, nlp_ru
    if morph_ru is None:
        morph_ru = pymorphy3.MorphAnalyzer()
    if nlp_ru is None:
        nlp_ru = spacy.load("ru_core_news_sm", exclude=["ner"])
    return nlp_ru


def analyze_ru(texts: list[str]) -> list[dict]:
    from backend import ru_grammar
    return ru_grammar.analyze(ensure_ru_grammar(), texts)


def check_grammar_ru(texts: list[str]) -> list[list[dict]]:
    from backend import ru_grammar
    nlp = ensure_ru_grammar()
    return ru_grammar.check(nlp, morph_ru, texts)


def load_glossary(path: Path | None, source_lang: str) -> list[dict]:
    glossary_terms = []
    if not path:
        return glossary_terms
    with path.open(encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            source, target = parts[0].strip(), parts[1].strip()
            if not source or not target:
                continue
            lemmas = lemmatize(source, source_lang)
            if lemmas:
                glossary_terms.append({"source": source, "target": target, "lemmas": lemmas, "length": len(lemmas)})
    glossary_terms.sort(key=lambda x: x["length"], reverse=True)
    return glossary_terms


def similarity(a, b):
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def token_matches(text_token, term_token, threshold):
    if text_token == term_token:
        return True
    if len(text_token) <= 3 or len(term_token) <= 3:
        return False
    return similarity(text_token, term_token) >= threshold


def match_term_at(words, start_index, term, threshold):
    lemmas = term["lemmas"]
    if start_index + len(lemmas) > len(words):
        return False
    for offset, term_lemma in enumerate(lemmas):
        if not token_matches(words[start_index + offset], term_lemma, threshold):
            return False
    return True


def find_glossary_terms(text: str, lang: str, glossary_terms: list[dict], threshold: float = 0.86):
    if not glossary_terms:
        return None
    words = lemmatize(text, lang)
    found, occupied = [], [False] * len(words)
    i = 0
    while i < len(words):
        if occupied[i]:
            i += 1
            continue
        best = None
        for term in glossary_terms:
            length = term["length"]
            if i + length > len(words) or any(occupied[i:i + length]):
                continue
            if match_term_at(words, i, term, threshold) and (best is None or length > best["length"]):
                best = term
        if best:
            found.append({"source": best["source"], "target": best["target"]})
            for j in range(i, i + best["length"]):
                occupied[j] = True
            i += best["length"]
        else:
            i += 1
    unique = {item["source"]: item["target"] for item in found}
    return [{"source": source, "target": target} for source, target in unique.items()] or None
