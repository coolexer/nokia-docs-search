"""Index Nokia chassis installation guide PDFs into the search database."""
from __future__ import annotations

import time
from pathlib import Path

import click

from nokia_docs.db import delete_product_lines, insert_records, open_write_db
from nokia_docs.parse_pdf import deduplicate_pdfs, parse_pdf

DEFAULT_PDF_DIR = Path(r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide")


def index_pdfs(db_path: Path, pdf_dir: Path = DEFAULT_PDF_DIR) -> int:
    """Index deduplicated chassis installation guide PDFs into db_path."""
    db_path = Path(db_path)
    pdf_dir = Path(pdf_dir)
    click.echo(f"DB      : {db_path.resolve()}")
    click.echo(f"PDF dir : {pdf_dir.resolve()}")
    if not pdf_dir.exists():
        raise click.ClickException(f"PDF directory not found: {pdf_dir}")

    pdfs = deduplicate_pdfs(pdf_dir)
    click.echo(f"PDFs    : {len(pdfs)} (after de-duplication)")
    if db_path.exists():
        click.echo(f"DB size before: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
    click.echo()

    conn = open_write_db(db_path)
    total = 0
    t0 = time.monotonic()
    try:
        for i, pdf_path in enumerate(pdfs, 1):
            short = pdf_path.name[:60]
            click.echo(f"[{i:3d}/{len(pdfs)}] {short}...", nl=False)
            try:
                records = parse_pdf(pdf_path)
                inserted = insert_records(conn, records)
                click.echo(f" {len(records)} sections, {inserted} inserted")
                total += inserted
            except Exception as exc:
                click.echo(f" ERROR: {exc}")

        click.echo("\nOptimizing FTS5 index...")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
        conn.commit()
    finally:
        conn.close()

    elapsed = time.monotonic() - t0
    click.echo(f"\nDone in {elapsed:.1f}s")
    click.echo(f"Total install-guide chunks inserted: {total:,}")
    click.echo(f"DB size after: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
    return total


def reindex_pdfs(db_path: Path, pdf_dir: Path = DEFAULT_PDF_DIR) -> int:
    """Remove existing installation guide rows and index PDFs again."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise click.ClickException(f"DB not found: {db_path}")
    conn = open_write_db(db_path)
    try:
        deleted = delete_product_lines(conn, ["install-guides"])
    finally:
        conn.close()
    click.echo(f"Deleted {deleted} existing install-guides rows")
    return index_pdfs(db_path, pdf_dir)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Index Nokia chassis installation guide PDFs.")
    parser.add_argument("--db", default="nokia_docs.db")
    parser.add_argument("--pdf-dir", default=str(DEFAULT_PDF_DIR))
    args = parser.parse_args(argv)
    index_pdfs(Path(args.db), Path(args.pdf_dir))
