"""Streaming TMX → SQLite conversion and indexed translation-memory search."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import heapq
import json
from pathlib import Path
import sqlite3
import re
import unicodedata
from xml.sax.saxutils import escape, quoteattr

from defusedxml.ElementTree import iterparse
from rapidfuzz.fuzz import ratio


SEARCH_SCHEMA_VERSION = 2
FUZZY_SCAN_THRESHOLD = 50
FUZZY_MIN_QUERY_LENGTH = 3


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def tag(element):
    return element.tag.rsplit("}", 1)[-1]


def segment_text(element):
    # TMX code payloads describe markup, not visible text.
    parts = [element.text or ""]
    for child in element:
        if tag(child) not in {"bpt", "ept", "ph", "it", "ut"}:
            parts.append(segment_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def ensure_segment_metadata_columns(db: sqlite3.Connection) -> None:
    """Add segment metadata columns to memories created by earlier versions."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(segments)")}
    if "author" not in columns:
        db.execute("ALTER TABLE segments ADD COLUMN author TEXT")
    if "created_at" not in columns:
        db.execute("ALTER TABLE segments ADD COLUMN created_at TEXT")
    db.commit()


def configure_database(db: sqlite3.Connection) -> None:
    """Use SQLite settings that keep readers responsive while segments are written."""
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=5000")


def ensure_search_indexes(db: sqlite3.Connection) -> bool:
    """Create and populate FTS indexes once; return False when FTS5 is unavailable."""
    try:
        existing = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('segments_fts', 'segments_trigram')"
        ).fetchall()
        existing_names = {row[0] for row in existing}
        needs_rebuild = existing_names != {"segments_fts", "segments_trigram"}
        db.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                source, target, content='segments', content_rowid='id', tokenize='unicode61'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_trigram USING fts5(
                source, target, content='segments', content_rowid='id', tokenize='trigram'
            );
            CREATE TRIGGER IF NOT EXISTS segments_search_ai AFTER INSERT ON segments BEGIN
                INSERT INTO segments_fts(rowid, source, target) VALUES (new.id, new.source, new.target);
                INSERT INTO segments_trigram(rowid, source, target) VALUES (new.id, new.source, new.target);
            END;
            CREATE TRIGGER IF NOT EXISTS segments_search_ad AFTER DELETE ON segments BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, source, target)
                    VALUES ('delete', old.id, old.source, old.target);
                INSERT INTO segments_trigram(segments_trigram, rowid, source, target)
                    VALUES ('delete', old.id, old.source, old.target);
            END;
            CREATE TRIGGER IF NOT EXISTS segments_search_au AFTER UPDATE OF source, target ON segments BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, source, target)
                    VALUES ('delete', old.id, old.source, old.target);
                INSERT INTO segments_trigram(segments_trigram, rowid, source, target)
                    VALUES ('delete', old.id, old.source, old.target);
                INSERT INTO segments_fts(rowid, source, target) VALUES (new.id, new.source, new.target);
                INSERT INTO segments_trigram(rowid, source, target) VALUES (new.id, new.source, new.target);
            END;
        """)
        if needs_rebuild or db.execute("PRAGMA user_version").fetchone()[0] < SEARCH_SCHEMA_VERSION:
            db.execute("INSERT INTO segments_fts(segments_fts) VALUES ('rebuild')")
            db.execute("INSERT INTO segments_trigram(segments_trigram) VALUES ('rebuild')")
            db.execute(f"PRAGMA user_version={SEARCH_SCHEMA_VERSION}")
        db.commit()
        return True
    except sqlite3.OperationalError:
        # Search remains functional on SQLite builds compiled without FTS5/trigram.
        db.rollback()
        return False


def convert_tmx(stream, destination: Path, name: str, source: str, target: str, description=""):
    source, target = source.strip().lower(), target.strip().lower()
    if not source or not target or source == target:
        raise ValueError("Укажите разные коды языков оригинала и перевода, например en-US и ru-RU.")
    count = skipped = duplicates = 0
    # Exclusive creation prevents overwriting an existing memory, including in CLI.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(destination)) as db, db:
            configure_database(db)
            db.executescript("""
                CREATE TABLE metadata (data TEXT NOT NULL);
                CREATE TABLE segments (
                    id INTEGER PRIMARY KEY, tuid TEXT, source TEXT NOT NULL,
                    target TEXT NOT NULL, normalized TEXT NOT NULL,
                    author TEXT, created_at TEXT NOT NULL,
                    UNIQUE(source, target));
                CREATE INDEX segments_normalized ON segments(normalized);
            """)
            root = None
            body = None
            for event, element in iterparse(stream, events=("start", "end"), forbid_entities=True, forbid_external=True):
                kind = tag(element)
                if root is None:
                    root = element
                    if kind != "tmx":
                        raise ValueError("Файл не является TMX: ожидается корневой элемент tmx.")
                if event == "start":
                    if kind == "body":
                        body = element
                    continue
                if kind != "tu":
                    continue
                variants = {}
                for tuv in element:
                    if tag(tuv) != "tuv":
                        continue
                    language = (tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or "").lower()
                    seg = next((child for child in tuv if tag(child) == "seg"), None)
                    if seg is not None:
                        variants[language] = segment_text(seg).strip()
                original, translated = variants.get(source), variants.get(target)
                if original and translated:
                    cursor = db.execute("INSERT OR IGNORE INTO segments(tuid,source,target,normalized,author,created_at) VALUES (?,?,?,?,?,?)",
                                        (element.get("tuid"), original, translated, normalize(original), None, datetime.now(timezone.utc).isoformat()))
                    count += cursor.rowcount
                    duplicates += 1 - cursor.rowcount
                else:
                    skipped += 1
                element.clear()
                if body is not None:
                    body.remove(element)
            if not count:
                raise ValueError("Для выбранной пары языков нет сегментов. Проверьте точные коды xml:lang в TMX (en и en-US различаются).")
            metadata = dict(name=name, description=description, source_language=source,
                            target_language=target, count=count, skipped=skipped, duplicates=duplicates,
                            created_at=datetime.now(timezone.utc).isoformat())
            db.execute("INSERT INTO metadata VALUES (?)", (json.dumps(metadata, ensure_ascii=False),))
            ensure_search_indexes(db)
        return dict(metadata, added=count)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise



def append_tmx(stream, destination: Path, source: str, target: str):
    """Append a TMX pair to an existing memory atomically."""
    source, target = source.strip().lower(), target.strip().lower()
    with closing(sqlite3.connect(destination)) as db:
        configure_database(db)
        ensure_segment_metadata_columns(db)
        ensure_search_indexes(db)
        row = db.execute("SELECT data FROM metadata").fetchone()
        if not row:
            raise ValueError("Выбранный файл не является памятью LinguaFlow.")
        metadata = json.loads(row[0])
        if (metadata.get("source_language", "").lower(), metadata.get("target_language", "").lower()) != (source, target):
            raise ValueError(f"Языки TMX ({source} → {target}) не совпадают с языками памяти ({metadata.get('source_language')} → {metadata.get('target_language')}).")
        added = skipped = duplicates = 0
        with db:
            root = body = None
            for event, element in iterparse(stream, events=("start", "end"), forbid_entities=True, forbid_external=True):
                kind = tag(element)
                if root is None:
                    root = element
                    if kind != "tmx":
                        raise ValueError("Файл не является TMX: ожидается корневой элемент tmx.")
                if event == "start":
                    if kind == "body":
                        body = element
                    continue
                if kind != "tu":
                    continue
                variants = {}
                for tuv in element:
                    if tag(tuv) != "tuv":
                        continue
                    language = (tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or "").lower()
                    seg = next((child for child in tuv if tag(child) == "seg"), None)
                    if seg is not None:
                        variants[language] = segment_text(seg).strip()
                original, translated = variants.get(source), variants.get(target)
                if original and translated:
                    cursor = db.execute("INSERT OR IGNORE INTO segments(tuid,source,target,normalized,author,created_at) VALUES (?,?,?,?,?,?)", (element.get("tuid"), original, translated, normalize(original), None, datetime.now(timezone.utc).isoformat()))
                    added += cursor.rowcount
                    duplicates += 1 - cursor.rowcount
                else:
                    skipped += 1
                element.clear()
                if body is not None:
                    body.remove(element)
            metadata["count"] = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            metadata["last_import_at"] = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE metadata SET data = ?", (json.dumps(metadata, ensure_ascii=False),))
    return dict(metadata, added=added, skipped=skipped, duplicates=duplicates)

def add_segment(destination: Path, source: str, target: str, tuid: str | None = None, author: str | None = None):
    """Add one source–target pair to a memory without changing existing pairs."""
    original, translated = source.strip(), target.strip()
    if not original or not translated:
        raise ValueError("Оригинал и перевод не должны быть пустыми.")
    with closing(sqlite3.connect(destination)) as db, db:
        db.row_factory = sqlite3.Row
        configure_database(db)
        ensure_segment_metadata_columns(db)
        ensure_search_indexes(db)
        row = db.execute("SELECT data FROM metadata").fetchone()
        if not row:
            raise ValueError("Выбранный файл не является памятью LinguaFlow.")
        metadata = json.loads(row[0])
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = db.execute(
            "INSERT OR IGNORE INTO segments(tuid, source, target, normalized, author, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tuid.strip() if tuid else None, original, translated, normalize(original), author.strip() if author else None, created_at),
        )
        segment = db.execute("SELECT id, tuid, author, created_at FROM segments WHERE source = ? AND target = ?", (original, translated)).fetchone()
        metadata["count"] = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        metadata["last_modified_at"] = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE metadata SET data = ?", (json.dumps(metadata, ensure_ascii=False),))
    return {"id": segment["id"], "tuid": segment["tuid"], "source": original, "target": translated,
            "author": segment["author"], "created_at": segment["created_at"], "added": bool(cursor.rowcount),
            "duplicate": not bool(cursor.rowcount)}


def delete_segment(destination: Path, segment_id: int) -> bool:
    """Delete one segment and keep the memory metadata count current."""
    with closing(sqlite3.connect(destination)) as db, db:
        configure_database(db)
        ensure_segment_metadata_columns(db)
        ensure_search_indexes(db)
        row = db.execute("SELECT data FROM metadata").fetchone()
        if not row:
            raise ValueError("Выбранный файл не является памятью LinguaFlow.")
        cursor = db.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
        if not cursor.rowcount:
            return False
        metadata = json.loads(row[0])
        metadata["count"] = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        metadata["last_modified_at"] = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE metadata SET data = ?", (json.dumps(metadata, ensure_ascii=False),))
    return True


def read_metadata(path):
    with closing(sqlite3.connect(path)) as db:
        return json.loads(db.execute("SELECT data FROM metadata").fetchone()[0])


def checkpoint_database(path: Path) -> None:
    """Move committed WAL pages into the main file before it is downloaded."""
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _xml_safe(value: object) -> str:
    text = str(value)
    return "".join(
        character for character in text
        if ord(character) in {0x09, 0x0A, 0x0D}
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )


def _tmx_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def stream_tmx(path: Path):
    """Yield a standards-compatible TMX 1.4 document without loading it into memory."""
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        configure_database(db)
        ensure_segment_metadata_columns(db)
        metadata_row = db.execute("SELECT data FROM metadata").fetchone()
        if not metadata_row:
            raise ValueError("Выбранный файл не является памятью LinguaFlow.")
        metadata = json.loads(metadata_row[0])
        source_language = _xml_safe(metadata.get("source_language") or "und")
        target_language = _xml_safe(metadata.get("target_language") or "und")
        header_attributes = [
            'creationtool="LinguaFlow"', 'creationtoolversion="2.0"',
            'segtype="sentence"', 'o-tmf="LinguaFlow SQLite"',
            'adminlang="en"', f"srclang={quoteattr(source_language)}", 'datatype="PlainText"',
        ]
        header_date = _tmx_datetime(metadata.get("created_at"))
        if header_date:
            header_attributes.append(f"creationdate={quoteattr(header_date)}")
        yield ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<tmx version="1.4">\n  <header ' + " ".join(header_attributes) + '/>\n  <body>\n').encode("utf-8")
        for row in db.execute("SELECT id, tuid, source, target, author, created_at FROM segments ORDER BY id"):
            attributes = [f"tuid={quoteattr(_xml_safe(row['tuid'] or row['id']))}"]
            if row["author"]:
                attributes.append(f"creationid={quoteattr(_xml_safe(row['author']))}")
            creation_date = _tmx_datetime(row["created_at"])
            if creation_date:
                attributes.append(f"creationdate={quoteattr(creation_date)}")
            source = escape(_xml_safe(row["source"]))
            target = escape(_xml_safe(row["target"]))
            yield (f"    <tu {' '.join(attributes)}>\n"
                   f"      <tuv xml:lang={quoteattr(source_language)}><seg>{source}</seg></tuv>\n"
                   f"      <tuv xml:lang={quoteattr(target_language)}><seg>{target}</seg></tuv>\n"
                   "    </tu>\n").encode("utf-8")
        yield b"  </body>\n</tmx>\n"


def _search_value(value, query, mode, threshold, respect_case):
    """Return (matched, fuzzy score, matching modes) for one text field."""
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    needle = " ".join(unicodedata.normalize("NFKC", query).split())
    if not respect_case:
        text, needle = text.casefold(), needle.casefold()
    words = set(re.findall(r"\w+", needle))
    phrase_pattern = re.compile((r"(?<!\w)" if re.match(r"\w", needle[0]) else "")
                                + re.escape(needle)
                                + (r"(?!\w)" if re.match(r"\w", needle[-1]) else ""))
    phrase = phrase_pattern.search(text) is not None
    word_match = bool(words) and words.issubset(set(re.findall(r"\w+", text)))
    score = ratio(needle, text)
    if mode == "fuzzy":
        return score >= threshold, score, ["fuzzy"] if score >= threshold else []
    if mode == "words":
        return word_match, score, ["words"] if word_match else []
    if mode == "phrase":
        return phrase, score, ["phrase"] if phrase else []
    modes = (["phrase"] if phrase else []) + (["words"] if word_match else []) + (["fuzzy"] if score >= threshold else [])
    return bool(modes), score, modes


def _fts_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _lexical_candidate_ids(db: sqlite3.Connection, column: str, query: str) -> set[int] | None:
    """Use the word index for a broad candidate set; Python performs final matching."""
    # unicode61 does not index a standalone underscore, so exclude underscores
    # from the broad FTS query and let the final Python check handle punctuation.
    words = list(dict.fromkeys(re.findall(r"[^\W_]+", normalize(query))))
    if not words:
        return None
    expression = f"{column} : (" + " AND ".join(_fts_quote(word) for word in words) + ")"
    try:
        return {row[0] for row in db.execute(
            "SELECT rowid FROM segments_fts WHERE segments_fts MATCH ?", (expression,)
        )}
    except sqlite3.OperationalError:
        return None


def _fuzzy_candidate_ids(db: sqlite3.Connection, column: str, query: str,
                         threshold: float, limit: int) -> set[int] | None:
    """Rank likely fuzzy matches through the trigram index before RapidFuzz scoring."""
    text = normalize(query)
    if threshold < FUZZY_SCAN_THRESHOLD or len(text) < FUZZY_MIN_QUERY_LENGTH:
        return None
    trigrams = list(dict.fromkeys(text[index:index + 3] for index in range(len(text) - 2)))
    if not trigrams:
        return None
    expression = f"{column} : (" + " OR ".join(_fts_quote(gram) for gram in trigrams) + ")"
    candidate_limit = max(300, min(2000, limit * 10))
    try:
        return {row[0] for row in db.execute(
            "SELECT rowid FROM segments_trigram WHERE segments_trigram MATCH ? "
            "ORDER BY bm25(segments_trigram) LIMIT ?", (expression, candidate_limit)
        )}
    except sqlite3.OperationalError:
        return None


def _search_candidate_ids(db: sqlite3.Connection, queries: list[tuple[str, str]], mode: str,
                          threshold: float, limit: int, indexes_available: bool) -> set[int] | None:
    if not indexes_available:
        return None
    combined: set[int] | None = None
    for column, query in queries:
        lexical = _lexical_candidate_ids(db, column, query) if mode in {"words", "phrase", "all"} else set()
        fuzzy = _fuzzy_candidate_ids(db, column, query, threshold, limit) if mode in {"fuzzy", "all"} else set()
        if lexical is None or fuzzy is None:
            # None means this part cannot be safely narrowed with an index.
            if mode == "all" and lexical is not None:
                field_candidates = None
            elif mode == "all" and fuzzy is not None:
                field_candidates = None
            elif mode in {"words", "phrase"}:
                field_candidates = lexical
            else:
                field_candidates = fuzzy
        else:
            field_candidates = lexical | fuzzy
        if field_candidates is None:
            return None
        combined = field_candidates if combined is None else combined & field_candidates
    return combined if combined is not None else set()


def _candidate_rows(db: sqlite3.Connection, candidate_ids: set[int] | None):
    if candidate_ids is None:
        yield from db.execute("SELECT * FROM segments ORDER BY id")
        return
    ordered = sorted(candidate_ids)
    for offset in range(0, len(ordered), 900):
        chunk = ordered[offset:offset + 900]
        placeholders = ",".join("?" for _ in chunk)
        yield from db.execute(f"SELECT * FROM segments WHERE id IN ({placeholders}) ORDER BY id", chunk)


def search_memory(path, source_query="", target_query="", threshold=70, limit=50, mode="fuzzy", respect_case=False, use_regex=False, regex=""):
    # Compatibility with the earlier positional signature: (path, query, threshold, limit, mode).
    if isinstance(target_query, (int, float)):
        old_threshold, old_limit, old_mode = target_query, threshold, limit
        target_query, threshold, limit = "", old_threshold, old_limit
        if isinstance(old_mode, str):
            mode = old_mode
    if mode not in {"fuzzy", "words", "phrase", "all"}:
        raise ValueError("Неизвестный режим поиска.")
    source_query, target_query, regex = source_query.strip(), target_query.strip(), regex.strip()
    # `regex` remains accepted for existing API clients; new clients apply regex in either text field.
    if regex and not (source_query or target_query):
        source_query, use_regex = regex, True
    if not (source_query or target_query):
        raise ValueError("Введите текст оригинала, перевода или регулярное выражение.")
    if mode == "words" and any(query and not re.search(r"\w", query) for query in (source_query, target_query)):
        raise ValueError("Введите хотя бы одно слово для поиска.")
    flags = 0 if respect_case else re.IGNORECASE
    regex_patterns = {}
    if use_regex:
        try:
            regex_patterns = {column: re.compile(query, flags) for column, query in
                              (("source", source_query), ("target", target_query)) if query}
        except re.error as error:
            raise ValueError(f"Некорректное регулярное выражение: {error.msg}.") from error
    with closing(sqlite3.connect(path)) as db:
        configure_database(db)
        ensure_segment_metadata_columns(db)
        db.row_factory = sqlite3.Row
        indexes_available = ensure_search_indexes(db)
        queries = [(column, query) for column, query in (("source", source_query), ("target", target_query)) if query]
        candidate_ids = None if use_regex else _search_candidate_ids(
            db, queries, mode, threshold, limit, indexes_available
        )
        matches = []
        for row in _candidate_rows(db, candidate_ids):
            if use_regex:
                if not all(pattern.search(row[column]) for column, pattern in regex_patterns.items()):
                    continue
                result = dict(row, score=None, exact=False, matched_modes=["regex"])
                matches.append(result)
                if len(matches) >= limit:
                    break
                continue
            conditions, modes, scores = [], [], []
            for column, query in (("source", source_query), ("target", target_query)):
                if query:
                    found, score, kinds = _search_value(row[column], query, mode, threshold, respect_case)
                    conditions.append(found)
                    modes.extend(kinds)
                    scores.append(score)
            if not all(conditions):
                continue
            score = round(min(scores), 2) if scores else None
            if mode in {"words", "phrase"}:
                score = None
            exact = bool(scores) and all(
                (query if respect_case else query.casefold()) == (row[column] if respect_case else row[column].casefold())
                for column, query in (("source", source_query), ("target", target_query)) if query
            )
            rank = 3 if exact else 2 if "phrase" in modes else 1 if "words" in modes else 0
            result = dict(row, score=score, exact=exact, matched_modes=list(dict.fromkeys(modes)))
            if mode in {"words", "phrase"}:
                matches.append(result)
                if len(matches) >= limit:
                    break
                continue
            item = (rank, score if score is not None else 0, -row["id"], result)
            if len(matches) < limit:
                heapq.heappush(matches, item)
            elif item[:3] > matches[0][:3]:
                heapq.heapreplace(matches, item)
        if use_regex or mode in {"words", "phrase"}:
            return matches
        return [item[3] for item in sorted(matches, reverse=True)]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--name")
    args = parser.parse_args()
    with args.input.open("rb") as stream:
        print(json.dumps(convert_tmx(stream, args.output, args.name or args.input.stem, args.source, args.target), ensure_ascii=False))
