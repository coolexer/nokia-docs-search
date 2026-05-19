"""Build SQLite FTS5 index from Nokia WebHelp HTML documentation.

Usage:
    nokia-docs index <docs_root> [-o output.db] [--reset]

The indexer:
- Walks all HTML files under <docs_root>
- Skips Oxygen chrome (index.html, search.html, nav pages without wh_topic_content)
- Extracts article chunks via parse.py
- Inserts into docs + docs_body tables; FTS5 trigger handles docs_fts
- Uses multiprocessing for parsing (CPU-bound), single-threaded SQLite writes
"""
from __future__ import annotations

import logging
import multiprocessing
import queue
import sqlite3
import threading
import time
from pathlib import Path

import click

from nokia_docs.parse import Chunk, parse_html

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# DB helpers                                                                    #
# --------------------------------------------------------------------------- #

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def _open_db(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64 MB
    schema = _SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    return conn


def _insert_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> int:
    """Insert chunks into docs + docs_fts. Returns number actually inserted."""
    inserted = 0
    for c in chunks:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO docs
                   (product_line, book, rel_path, page_title, section_id,
                    section_title, section_path, depth, char_len)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (c.product_line, c.book, c.rel_path, c.page_title,
                 c.section_id, c.section_title, c.section_path,
                 c.depth, c.char_len),
            )
            if cur.lastrowid and cur.rowcount:
                doc_id = cur.lastrowid
                conn.execute(
                    "INSERT OR IGNORE INTO docs_body (id, body) VALUES (?,?)",
                    (doc_id, c.body),
                )
                conn.execute(
                    """INSERT INTO docs_fts(rowid, section_title, page_title, section_path, body)
                       VALUES (?,?,?,?,?)""",
                    (doc_id, c.section_title, c.page_title, c.section_path, c.body),
                )
                inserted += 1
        except sqlite3.Error as e:
            log.warning("Insert failed for %s/%s: %s", c.rel_path, c.section_id, e)
    return inserted


# --------------------------------------------------------------------------- #
# Worker: parse one HTML file → list[Chunk]                                    #
# --------------------------------------------------------------------------- #

def _parse_worker(args: tuple[Path, Path]) -> list[Chunk]:
    html_path, docs_root = args
    try:
        return parse_html(html_path, docs_root)
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Writer thread: receives parsed chunks and writes to DB                       #
# --------------------------------------------------------------------------- #

_BATCH_SIZE = 500
_SENTINEL = None


def _writer_thread(conn: sqlite3.Connection, q: queue.Queue, counters: dict) -> None:
    batch: list[Chunk] = []
    total = 0

    def _flush():
        nonlocal total
        if not batch:
            return
        try:
            conn.execute("BEGIN")
            n = _insert_chunks(conn, batch)
            conn.execute("COMMIT")
            total += n
            counters["inserted"] = total
        except sqlite3.Error as exc:
            log.error("Batch flush failed (%d chunks): %s", len(batch), exc)
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        finally:
            batch.clear()

    while True:
        try:
            item = q.get(timeout=30)
        except queue.Empty:
            # No data in 30 s — flush what we have and keep waiting
            _flush()
            continue
        if item is _SENTINEL:
            _flush()
            break
        if isinstance(item, list):
            batch.extend(item)
            if len(batch) >= _BATCH_SIZE:
                _flush()
        q.task_done()

    counters["done"] = True


# --------------------------------------------------------------------------- #
# CLI command                                                                   #
# --------------------------------------------------------------------------- #

@click.command("index")
@click.argument("docs_root", type=click.Path(exists=True, file_okay=False))
@click.option("-o", "--output", default="nokia_docs.db",
              help="Output SQLite database path (default: nokia_docs.db)")
@click.option("--reset", is_flag=True, default=False,
              help="Delete existing DB and rebuild from scratch")
@click.option("--workers", default=0, type=int,
              help="Parser worker processes (default: CPU count)")
def index_cmd(docs_root: str, output: str, reset: bool, workers: int) -> None:
    """Build or refresh the Nokia documentation FTS5 index."""
    root = Path(docs_root).resolve()
    db_path = Path(output).resolve()

    click.echo(f"Docs root : {root}")
    click.echo(f"Database  : {db_path}")

    # Collect HTML files — skip obvious chrome pages.
    _SKIP_NAMES = {
        "index.html", "search.html", "toc.html",
        "wh-iframe.html", "wh_iframe.html",
    }
    html_files = [
        p for p in root.rglob("*.html")
        if p.name.lower() not in _SKIP_NAMES
        and "oxygen-webhelp" not in str(p)
    ]
    total_files = len(html_files)
    click.echo(f"HTML files: {total_files}")

    conn = _open_db(db_path, reset=reset)

    n_workers = workers or max(1, multiprocessing.cpu_count() - 1)
    click.echo(f"Workers   : {n_workers}\n")

    write_q: queue.Queue = queue.Queue(maxsize=200)
    counters: dict = {"inserted": 0, "done": False}

    writer = threading.Thread(
        target=_writer_thread, args=(conn, write_q, counters), daemon=True
    )
    writer.start()

    t0 = time.monotonic()
    processed = 0

    try:
        with multiprocessing.Pool(processes=n_workers) as pool:
            args_iter = ((f, root) for f in html_files)
            for chunks in pool.imap_unordered(_parse_worker, args_iter, chunksize=10):
                if chunks:
                    write_q.put(chunks)
                processed += 1
                if processed % 50 == 0 or processed == total_files:
                    elapsed = time.monotonic() - t0
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (total_files - processed) / rate if rate > 0 else 0
                    click.echo(
                        f"\r  {processed}/{total_files} files  "
                        f"{counters['inserted']} chunks  "
                        f"{rate:.0f} files/s  ETA {eta:.0f}s      ",
                        nl=(processed == total_files),
                    )
    except KeyboardInterrupt:
        click.echo("\nInterrupted — flushing and closing DB…")
    finally:
        write_q.put(_SENTINEL)
        writer.join()

    elapsed = time.monotonic() - t0
    total_inserted = counters["inserted"]

    click.echo(f"\nOptimising FTS5 index…")
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    db_mb = db_path.stat().st_size / 1024 / 1024
    click.echo(f"\nDone in {elapsed:.1f}s")
    click.echo(f"  Chunks inserted : {total_inserted:,}")
    click.echo(f"  DB size         : {db_mb:.1f} MB")
    click.echo(f"  DB path         : {db_path}")
