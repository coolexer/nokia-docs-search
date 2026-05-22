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
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from nokia_docs.db import insert_records, open_write_db
from nokia_docs.parse import Chunk, parse_html

log = logging.getLogger(__name__)


@dataclass
class ParseResult:
    chunks: list[Chunk] = field(default_factory=list)
    failed_file: str | None = None
    error: str | None = None


@dataclass
class HtmlIndexReport:
    discovered_files: int = 0
    parsed_files: int = 0
    inserted: int = 0
    parse_failures: list[str] = field(default_factory=list)
    write_failures: int = 0
    elapsed_seconds: float = 0.0
    db_size_mb: float = 0.0

# --------------------------------------------------------------------------- #
# DB helpers                                                                    #
# --------------------------------------------------------------------------- #

def _open_db(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    return open_write_db(db_path, reset=reset)


def _insert_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> int:
    """Insert chunks into docs + docs_fts. Returns number actually inserted."""
    rows = []
    for chunk in chunks:
        row = asdict(chunk)
        row["char_len"] = chunk.char_len
        rows.append(row)
    return insert_records(conn, rows)


# --------------------------------------------------------------------------- #
# Worker: parse one HTML file → list[Chunk]                                    #
# --------------------------------------------------------------------------- #

def _parse_worker(args: tuple[Path, Path]) -> ParseResult:
    html_path, docs_root = args
    try:
        return ParseResult(chunks=parse_html(html_path, docs_root))
    except Exception as exc:
        log.warning("Parse failed for %s: %s", html_path, exc)
        return ParseResult(failed_file=str(html_path), error=str(exc))


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
            n = _insert_chunks(conn, batch)
            total += n
            counters["inserted"] = total
        except sqlite3.Error as exc:
            log.error("Batch flush failed (%d chunks): %s", len(batch), exc)
            counters["write_failures"] = counters.get("write_failures", 0) + len(batch)
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
@click.option("--fail-on-error", is_flag=True,
              help="Exit with an error if any HTML file fails to parse or write.")
def index_cmd(docs_root: str, output: str, reset: bool, workers: int, fail_on_error: bool) -> None:
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
    counters: dict = {"inserted": 0, "write_failures": 0, "done": False}

    writer = threading.Thread(
        target=_writer_thread, args=(conn, write_q, counters), daemon=True
    )
    writer.start()

    t0 = time.monotonic()
    processed = 0
    interrupted = False
    parse_failures: list[str] = []

    try:
        args_iter = ((f, root) for f in html_files)
        pool = None
        if n_workers == 1:
            chunk_iter = (_parse_worker(args) for args in args_iter)
        else:
            pool = multiprocessing.Pool(processes=n_workers)
            chunk_iter = pool.imap_unordered(_parse_worker, args_iter, chunksize=10)
        try:
            for result in chunk_iter:
                if result.failed_file:
                    parse_failures.append(result.failed_file)
                    click.echo(f"Parse failed: {result.failed_file} ({result.error})")
                if result.chunks:
                    write_q.put(result.chunks)
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
        finally:
            if pool is not None:
                pool.close()
                pool.join()
    except KeyboardInterrupt:
        interrupted = True
        click.echo("\nIndex interrupted - flushing and closing DB...")
    finally:
        write_q.put(_SENTINEL)
        writer.join()

    elapsed = time.monotonic() - t0
    total_inserted = counters["inserted"]
    write_failures = counters.get("write_failures", 0)

    if not interrupted:
        click.echo("\nOptimising FTS5 index...")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
        conn.commit()
    conn.close()

    if interrupted:
        raise click.ClickException("Index interrupted before completion.")

    db_mb = db_path.stat().st_size / 1024 / 1024
    report = HtmlIndexReport(
        discovered_files=total_files,
        parsed_files=processed - len(parse_failures),
        inserted=total_inserted,
        parse_failures=parse_failures,
        write_failures=write_failures,
        elapsed_seconds=elapsed,
        db_size_mb=db_mb,
    )
    click.echo("\nIndex summary")
    click.echo(f"  HTML files parsed : {processed:,}")
    click.echo(f"  Chunks inserted   : {total_inserted:,}")
    click.echo(f"  Parse failures    : {len(parse_failures):,}")
    click.echo(f"  Write failures    : {write_failures:,}")
    click.echo(f"  Duration seconds  : {elapsed:.1f}")
    click.echo(f"  DB size           : {db_mb:.1f} MB")
    click.echo(f"  DB path           : {db_path}")

    if fail_on_error and (report.parse_failures or report.write_failures):
        raise click.ClickException(
            f"Failed to index {len(report.parse_failures)} HTML file(s); "
            f"{report.write_failures} chunk(s) failed to write."
        )
