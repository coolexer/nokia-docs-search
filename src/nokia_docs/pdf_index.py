"""Index Nokia chassis installation guide PDFs into the search database."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import click

from nokia_docs.db import delete_product_lines, insert_records, open_write_db
from nokia_docs.parse_pdf import deduplicate_pdfs, parse_pdf

DEFAULT_PDF_DIR = None


@dataclass
class PdfIndexReport:
    discovered_files: int = 0
    parsed_files: int = 0
    inserted: int = 0
    failed_files: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    db_size_mb: float = 0.0


def index_pdfs(
    db_path: Path,
    pdf_dir: Path | None = DEFAULT_PDF_DIR,
    fail_on_error: bool = False,
) -> PdfIndexReport:
    """Index deduplicated chassis installation guide PDFs into db_path."""
    db_path = Path(db_path)
    if pdf_dir is None:
        raise click.ClickException("PDF directory is required. Pass --pdf-dir <path>.")
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
    parsed = 0
    failed_files: list[str] = []
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
                parsed += 1
            except Exception as exc:
                failed_files.append(str(pdf_path))
                click.echo(f" ERROR: {exc}")

        click.echo("\nOptimizing FTS5 index...")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
        conn.commit()
    finally:
        conn.close()

    elapsed = time.monotonic() - t0
    if failed_files:
        click.echo(f"Failed PDFs: {len(failed_files)}")
    click.echo(f"\nDone in {elapsed:.1f}s")
    click.echo(f"Total install-guide chunks inserted: {total:,}")
    click.echo(f"DB size after: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
    report = PdfIndexReport(
        discovered_files=len(pdfs),
        parsed_files=parsed,
        inserted=total,
        failed_files=failed_files,
        elapsed_seconds=elapsed,
        db_size_mb=db_path.stat().st_size / 1024 / 1024,
    )
    if fail_on_error and failed_files:
        raise click.ClickException(f"Failed to index {len(failed_files)} PDF file(s).")
    return report


def reindex_pdfs(
    db_path: Path,
    pdf_dir: Path | None = DEFAULT_PDF_DIR,
    fail_on_error: bool = False,
) -> PdfIndexReport:
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
    return index_pdfs(db_path, pdf_dir, fail_on_error=fail_on_error)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Index Nokia chassis installation guide PDFs.")
    parser.add_argument("--db", default="nokia_docs.db")
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)
    index_pdfs(Path(args.db), Path(args.pdf_dir), fail_on_error=args.fail_on_error)
