"""Shared SQLite helpers for Nokia documentation indexes."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_FILE = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 1
APP_NAME = "nokia-docs-search"


def open_write_db(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    """Open a writable SQLite database and ensure the search schema exists."""
    db_path = Path(db_path)
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    ensure_metadata(conn)
    conn.commit()
    return conn


def ensure_metadata(conn: sqlite3.Connection) -> None:
    """Record schema/app metadata in a writable search database."""
    values = {
        "schema_version": str(SCHEMA_VERSION),
        "app_name": APP_NAME,
        "metadata_updated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    conn.executemany(
        """INSERT INTO metadata(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        values.items(),
    )


def read_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    """Read search database metadata as a dictionary."""
    try:
        return dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error as exc:
        raise RuntimeError("Database metadata table is missing or unreadable.") from exc


def validate_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    """Validate that a database is compatible with this package."""
    metadata = read_metadata(conn)
    actual = metadata.get("schema_version")
    expected = str(SCHEMA_VERSION)
    if actual != expected:
        raise RuntimeError(
            f"Database schema version {actual or 'missing'} is not compatible; "
            f"expected schema version {expected}."
        )
    return metadata


def record_build_manifest(conn: sqlite3.Connection, values: dict[str, object]) -> None:
    """Record build/source metadata for a generated database artifact."""
    normalized = {key: str(value) for key, value in values.items()}
    normalized["manifest_updated_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        """INSERT INTO build_manifest(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        normalized.items(),
    )
    conn.commit()


def read_build_manifest(conn: sqlite3.Connection) -> dict[str, str]:
    """Read optional DB build manifest values."""
    try:
        return dict(conn.execute("SELECT key, value FROM build_manifest").fetchall())
    except sqlite3.Error:
        return {}


def validate_database(conn: sqlite3.Connection) -> list[str]:
    """Return structural validation errors for a search database."""
    errors: list[str] = []
    validate_metadata(conn)

    doc_count = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    body_count = conn.execute("SELECT COUNT(*) FROM docs_body").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM docs_fts").fetchone()[0]

    if doc_count != body_count:
        errors.append(f"docs/docs_body row count mismatch: docs={doc_count}, docs_body={body_count}")
    if doc_count != fts_count:
        errors.append(f"docs/docs_fts row count mismatch: docs={doc_count}, docs_fts={fts_count}")

    orphan_body = conn.execute(
        "SELECT COUNT(*) FROM docs_body b LEFT JOIN docs d ON d.id = b.id WHERE d.id IS NULL"
    ).fetchone()[0]
    if orphan_body:
        errors.append(f"orphan docs_body rows: {orphan_body}")

    orphan_fts = conn.execute(
        "SELECT COUNT(*) FROM docs_fts f LEFT JOIN docs d ON d.id = f.rowid WHERE d.id IS NULL"
    ).fetchone()[0]
    if orphan_fts:
        errors.append(f"orphan docs_fts rows: {orphan_fts}")

    standards_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        ).fetchall()
    }
    if {"standards", "standards_fts"}.issubset(standards_tables):
        standards_count = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
        standards_fts_count = conn.execute("SELECT COUNT(*) FROM standards_fts").fetchone()[0]
        if standards_count != standards_fts_count:
            errors.append(
                "standards/standards_fts row count mismatch: "
                f"standards={standards_count}, standards_fts={standards_fts_count}"
            )

        orphan_standards_fts = conn.execute(
            """SELECT COUNT(*)
               FROM standards_fts f
               LEFT JOIN standards s ON s.id = f.rowid
               WHERE s.id IS NULL"""
        ).fetchone()[0]
        if orphan_standards_fts:
            errors.append(f"orphan standards_fts rows: {orphan_standards_fts}")

    return errors


def insert_records(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Insert normalized document records into docs, docs_body, and docs_fts."""
    inserted = 0
    conn.execute("BEGIN")
    try:
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO docs
                   (product_line, book, rel_path, page_title, section_id,
                    section_title, section_path, depth, char_len)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    r["product_line"],
                    r["book"],
                    r["rel_path"],
                    r["page_title"],
                    r["section_id"],
                    r["section_title"],
                    r["section_path"],
                    r["depth"],
                    r["char_len"],
                ),
            )
            if cur.lastrowid and cur.rowcount:
                doc_id = cur.lastrowid
                conn.execute(
                    "INSERT OR IGNORE INTO docs_body (id, body) VALUES (?,?)",
                    (doc_id, r["body"]),
                )
                conn.execute(
                    """INSERT INTO docs_fts
                       (rowid, section_title, page_title, section_path, body)
                       VALUES (?,?,?,?,?)""",
                    (
                        doc_id,
                        r["section_title"],
                        r["page_title"],
                        r["section_path"],
                        r["body"],
                    ),
                )
                inserted += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return inserted


def delete_product_lines(conn: sqlite3.Connection, product_lines: list[str]) -> int:
    """Delete all rows for the given product lines from docs and FTS tables."""
    ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM docs WHERE product_line IN ({','.join('?' * len(product_lines))})",
            product_lines,
        ).fetchall()
    ]
    if not ids:
        return 0

    placeholders = ",".join("?" * len(ids))
    conn.execute("BEGIN")
    try:
        conn.execute(f"DELETE FROM docs_fts WHERE rowid IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM docs_body WHERE id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM docs WHERE id IN ({placeholders})", ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return len(ids)


def delete_standards_product_lines(conn: sqlite3.Connection, product_lines: list[str]) -> int:
    """Delete standards rows and mirrored docs rows for the given standards product lines."""
    if not product_lines:
        return 0

    placeholders = ",".join("?" * len(product_lines))
    standard_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM standards WHERE product_line IN ({placeholders})",
            product_lines,
        ).fetchall()
    ]
    doc_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM docs WHERE product_line IN ({placeholders})",
            product_lines,
        ).fetchall()
    ]
    deleted = len(standard_ids)

    conn.execute("BEGIN")
    try:
        if standard_ids:
            standard_placeholders = ",".join("?" * len(standard_ids))
            conn.execute(
                f"DELETE FROM standards_fts WHERE rowid IN ({standard_placeholders})",
                standard_ids,
            )
            conn.execute(
                f"DELETE FROM standards WHERE id IN ({standard_placeholders})",
                standard_ids,
            )
        if doc_ids:
            doc_placeholders = ",".join("?" * len(doc_ids))
            conn.execute(f"DELETE FROM docs_fts WHERE rowid IN ({doc_placeholders})", doc_ids)
            conn.execute(f"DELETE FROM docs_body WHERE id IN ({doc_placeholders})", doc_ids)
            conn.execute(f"DELETE FROM docs WHERE id IN ({doc_placeholders})", doc_ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return deleted
