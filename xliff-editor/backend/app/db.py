import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, source_language TEXT, target_language TEXT,
 original_xml BLOB NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 xliff_id TEXT, original_path TEXT NOT NULL, position INTEGER NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS units (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE, xliff_id TEXT,
 original_path TEXT NOT NULL, position INTEGER NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS segments (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE, unit_id TEXT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
 xliff_id TEXT, original_path TEXT NOT NULL, segment_index INTEGER NOT NULL,
 source_text TEXT NOT NULL, source_xml TEXT NOT NULL DEFAULT '', target_xml TEXT, state TEXT NOT NULL DEFAULT 'untranslated',
 notes_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS notes (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE, category TEXT, content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segments_document_id ON segments(document_id);
CREATE INDEX IF NOT EXISTS ix_segments_file_id ON segments(file_id);
CREATE INDEX IF NOT EXISTS ix_segments_unit_id ON segments(unit_id);
CREATE INDEX IF NOT EXISTS ix_segments_segment_index ON segments(segment_index);
CREATE INDEX IF NOT EXISTS ix_segments_state ON segments(state);
"""

def database_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "editor.db"

@contextmanager
def connection():
    path = database_path(); path.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(path); con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()
