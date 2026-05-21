"""Shared SQLite helpers for Nokia documentation indexes."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def open_write_db(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    """Open a writable SQLite database and ensure the search schema exists."""
    db_path = Path(db_path)
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.commit()
    return conn


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
