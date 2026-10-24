"""Conservative Russian morphology/dependency grammar checks for the NLP worker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pymorphy3


@dataclass(frozen=True)
class RuToken:
    index: int
    text: str
    lemma: str
    pos: str
    dep: str
    head_index: int
    start_cp: int
    end_cp: int
    start_utf16: int
    end_utf16: int
    morph: dict[str, str]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _utf16_offsets(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for char in text:
        total += 2 if ord(char) > 0xFFFF else 1
        offsets.append(total)
    return offsets


def _morph(token) -> dict[str, str]:
    return {key: value for key, value in token.morph.to_dict().items() if value}


_PYMORPHY_TO_UD = {"nomn": "Nom", "gent": "Gen", "datv": "Dat", "accs": "Acc", "ablt": "Ins", "loct": "Loc",
                   "sing": "Sing", "plur": "Plur", "masc": "Masc", "femn": "Fem", "neut": "Neut",
                   "pres": "Pres", "past": "Past", "futr": "Fut", "1per": "1", "2per": "2", "3per": "3"}


def normalize_pymorphy_grammemes(grammemes) -> dict[str, str]:
    """Convert pymorphy grammemes to UD names without losing multi-values."""
    result: dict[str, list[str]] = {}
    for raw in grammemes:
        value = _PYMORPHY_TO_UD.get(str(raw).lower())
        if value is None:
            continue
        key = {"Nom": "Case", "Gen": "Case", "Dat": "Case", "Acc": "Case", "Ins": "Case", "Loc": "Case",
               "Sing": "Number", "Plur": "Number", "Masc": "Gender", "Fem": "Gender", "Neut": "Gender",
               "Pres": "Tense", "Past": "Tense", "Fut": "Tense", "1": "Person", "2": "Person", "3": "Person"}[value]
        result.setdefault(key, []).append(value)
    return {key: ",".join(dict.fromkeys(values)) for key, values in result.items()}


def _tokens(doc) -> list[RuToken]:
    utf16 = _utf16_offsets(doc.text)
    return [RuToken(t.i, t.text, t.lemma_, t.pos_, t.dep_, t.head.i,
                    t.idx, t.idx + len(t.text), utf16[t.idx], utf16[t.idx + len(t.text)], _morph(t))
            for t in doc]


def _sentence_dict(sentence, tokens: list[RuToken]) -> dict:
    start = sentence.start_char
    end = sentence.end_char
    return {"start_cp": start, "end_cp": end, "start_utf16": tokens[sentence.start].start_utf16 if sentence.start < len(tokens) else 0,
            "end_utf16": tokens[sentence.end - 1].end_utf16 if sentence.end > sentence.start else (tokens[sentence.start].start_utf16 if sentence.start < len(tokens) else 0),
            "tokens": [token.as_dict() for token in tokens[sentence.start:sentence.end]]}


def analyze_docs(docs: Iterable, texts: list[str]) -> list[dict]:
    output = []
    for doc, text in zip(docs, texts):
        tokens = _tokens(doc)
        sentences = []
        for sentence in doc.sents:
            item = _sentence_dict(sentence, tokens)
            item["text"] = text[sentence.start_char:sentence.end_char]
            sentences.append(item)
        output.append({"sentences": sentences})
    return output


def _feature(token: RuToken, name: str) -> str | None:
    value = token.morph.get(name)
    return value


def _feature_values(token: RuToken, name: str) -> set[str]:
    value = _feature(token, name)
    return set(value.split(",")) if value else set()


_NOMINAL_BRIDGES = {"nmod", "nmod:poss", "appos", "flat", "flat:name", "compound", "amod", "case", "det", "conj"}


def _is_nominal(token: RuToken) -> bool:
    return token.pos in {"NOUN", "PROPN", "X"}


def _has_additive_cc(tokens: list[RuToken], token: RuToken) -> bool:
    """Return true only for a high-confidence ``и`` conjunction."""
    for candidate in tokens:
        if candidate.dep == "cc" and candidate.head_index == token.index and candidate.text.casefold() == "и":
            return True
    previous = tokens[token.index - 1] if token.index > 0 else None
    return bool(previous and previous.text.casefold() == "и")


def subject_group(tokens: list[RuToken], subject: RuToken) -> list[RuToken]:
    """Find additive coordinated nominal members of an ``nsubj`` phrase.

    The parser sometimes attaches a foreign conjunct below an oblique noun
    inside the subject phrase (for example ``... в автомобиле и Wi-Fi``), so
    the walk follows nominal bridge dependencies before inspecting ``conj``.
    Only an explicit ``и`` is accepted; ``или``/``либо`` remain ambiguous.
    """
    children: dict[int, list[RuToken]] = {}
    for token in tokens:
        children.setdefault(token.head_index, []).append(token)
    members = [subject]
    seen: set[int] = {subject.index}

    def walk(parent: RuToken) -> None:
        for child in children.get(parent.index, []):
            if child.index in seen:
                continue
            if child.dep == "conj":
                if _is_nominal(child) and _has_additive_cc(tokens, child):
                    members.append(child)
                    seen.add(child.index)
                    walk(child)
                continue
            if child.dep in _NOMINAL_BRIDGES:
                seen.add(child.index)
                walk(child)

    walk(subject)
    return members if len(members) > 1 else []


def _group_number(subject: RuToken, group: list[RuToken], predicate: RuToken, morph: pymorphy3.MorphAnalyzer) -> bool | None:
    if not group:
        return _compatible(subject, predicate, "Number", morph)
    values = _feature_values(predicate, "Number")
    # spaCy can mis-tag a short/indeclinable predicate as plural.  When
    # pymorphy gives one unambiguous number, use it for this high-confidence
    # coordinated-subject comparison; ambiguity still abstains.
    pymorphy_values = set()
    for parse in _parse_candidates(morph, predicate):
        pymorphy_values.update(normalize_pymorphy_grammemes(parse.tag.grammemes).get("Number", "").split(","))
    pymorphy_values.discard("")
    if len(pymorphy_values) == 1:
        values = pymorphy_values
    if not values:
        return _compatible(subject, predicate, "Number", morph)
    if "Plur" in values:
        return True
    return None if len(values) > 1 else False


def _parse_candidates(morph: pymorphy3.MorphAnalyzer, token: RuToken):
    return morph.parse(token.text)


def _compatible(subject: RuToken, predicate: RuToken, name: str, morph: pymorphy3.MorphAnalyzer) -> bool | None:
    left, right = _feature(subject, name), _feature(predicate, name)
    if left and right:
        return bool(_feature_values(subject, name) & _feature_values(predicate, name))
    # spaCy is authoritative for the dependency relation. Use pymorphy only to
    # fill missing features; ambiguity means we deliberately abstain.
    parses = _parse_candidates(morph, predicate)
    values = set()
    for parse in parses:
        values.update(normalize_pymorphy_grammemes(parse.tag.grammemes).get(name, "").split(","))
    values.discard("")
    if not left or not values:
        return None
    if _feature_values(subject, name) & values:
        return True
    return False if len(values) == 1 else None


def _issue(rule_id: str, message: str, a: RuToken, b: RuToken, *, features: dict, text: str) -> dict:
    start, end = min(a.start_cp, b.start_cp), max(a.end_cp, b.end_cp)
    utf_start, utf_end = min(a.start_utf16, b.start_utf16), max(a.end_utf16, b.end_utf16)
    return {"rule_id": rule_id, "category": "GRAMMAR", "severity": "WARNING", "message": message,
            "start_cp": start, "end_cp": end, "start_utf16": utf_start, "end_utf16": utf_end,
            "context": text[start:end], "tokens": [a.text, b.text], "features": features, "confidence": "high"}


def _check_doc(doc, text: str, morph: pymorphy3.MorphAnalyzer) -> list[dict]:
    tokens = _tokens(doc)
    issues: list[dict] = []
    for token in tokens:
        if token.dep in {"amod", "acl", "acl:relcl"} and token.head_index != token.index:
            head = tokens[token.head_index]
            if head.pos in {"NOUN", "PROPN"}:
                is_participle = token.pos == "VERB" and _feature(token, "VerbForm") == "Part"
                if token.pos == "VERB" and not is_participle:
                    continue
                agreement_rule = "RU_PARTICIPLE_NOUN_AGREEMENT" if is_participle else "RU_ADJ_NOUN_AGREEMENT"
                agreement_message = "Participle and noun do not agree" if is_participle else "Adjective and noun do not agree"
                checks = [("Number", agreement_rule), ("Case", agreement_rule)]
                if _feature(head, "Number") == "Sing": checks.append(("Gender", agreement_rule))
                for name, rule in checks:
                    value = _compatible(token, head, name, morph)
                    if value is False:
                        issues.append(_issue(rule, f"{agreement_message} in {name.lower()}.", token, head,
                                             features={"modifier_" + name.lower(): _feature(token, name), "noun_" + name.lower(): _feature(head, name)}, text=text))
                        break
        if token.dep in {"det", "nmod:poss"} and token.head_index != token.index:
            head = tokens[token.head_index]
            if head.pos in {"NOUN", "PROPN"} and _feature(token, "Number") and _feature(head, "Number") and _feature(token, "Number") != _feature(head, "Number"):
                issues.append(_issue("RU_DET_NOUN_AGREEMENT", "Determiner and noun do not agree in number.", token, head,
                                     features={"determiner_number": _feature(token, "Number"), "noun_number": _feature(head, "Number")}, text=text))
        if token.dep == "nsubj" or token.dep.startswith("nsubj:"):
            if token.head_index == token.index:
                continue
            predicate = tokens[token.head_index]
            if predicate.pos in {"ADJ", "VERB", "AUX"}:
                coordinated = subject_group(tokens, token)
                if predicate.pos == "VERB":
                    number = _group_number(token, coordinated, predicate, morph)
                    gender = None if coordinated else _compatible(token, predicate, "Gender", morph)
                    tense = _feature(predicate, "Tense")
                    rule = "RU_SUBJECT_PAST_VERB_AGREEMENT" if tense == "Past" else "RU_SUBJECT_FINITE_VERB_NUMBER"
                    if number is False or (tense == "Past" and gender is False):
                        issues.append(_issue(rule, "Subject and verb do not agree.", token, predicate,
                                             features={"subject_number": _feature(token, "Number"), "verb_number": _feature(predicate, "Number"), "subject_gender": _feature(token, "Gender"), "verb_gender": _feature(predicate, "Gender")}, text=text))
                else:
                    number = _group_number(token, coordinated, predicate, morph)
                    if number is False:
                        issues.append(_issue("RU_SUBJECT_PREDICATIVE_NUMBER", "Subject and predicate do not agree in number.", token, predicate,
                                             features={"subject_number": _feature(token, "Number"), "predicate_number": _feature(predicate, "Number")}, text=text))
                    gender = None if coordinated else _compatible(token, predicate, "Gender", morph)
                    if gender is False and not coordinated and _feature(token, "Number") == "Sing":
                        issues.append(_issue("RU_SUBJECT_PREDICATIVE_GENDER", "Subject and predicate do not agree in gender.", token, predicate,
                                             features={"subject_gender": _feature(token, "Gender"), "predicate_gender": _feature(predicate, "Gender"), "number": _feature(token, "Number")}, text=text))

                # In a compound verbal predicate the auxiliary carries the
                # finite agreement.  Check it against the subject separately;
                # do not infer an error when morphology is ambiguous.
                for auxiliary in tokens:
                    if auxiliary.head_index != predicate.index or not (auxiliary.dep == "aux" or auxiliary.dep.startswith("aux:") or auxiliary.dep == "cop"):
                        continue
                    aux_number = _compatible(token, auxiliary, "Number", morph)
                    aux_gender = _compatible(token, auxiliary, "Gender", morph)
                    if aux_number is False or (_feature(auxiliary, "Tense") == "Past" and _feature(token, "Number") == "Sing" and aux_gender is False):
                        issues.append(_issue("RU_SUBJECT_AUX_AGREEMENT", "Subject and auxiliary do not agree.", token, auxiliary,
                                             features={"subject_number": _feature(token, "Number"), "aux_number": _feature(auxiliary, "Number"), "subject_gender": _feature(token, "Gender"), "aux_gender": _feature(auxiliary, "Gender")}, text=text))
    # Keep one high-confidence issue for a relation instead of duplicate copula diagnostics.
    unique = {}
    for item in issues:
        # One subject/predicate disagreement must not become a gender issue
        # and a second generic verb issue for the same token pair.
        key = (item["start_utf16"], item["end_utf16"])
        unique.setdefault(key, item)
    return list(unique.values())


def analyze(nlp, texts: list[str], batch_size: int = 32) -> list[dict]:
    docs = nlp.pipe(texts, batch_size=batch_size)
    return analyze_docs(docs, texts)


def check(nlp, morph: pymorphy3.MorphAnalyzer, texts: list[str], batch_size: int = 32) -> list[list[dict]]:
    return [_check_doc(doc, text, morph) for doc, text in zip(nlp.pipe(texts, batch_size=batch_size), texts)]
