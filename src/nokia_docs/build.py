"""One-shot database build orchestration for release artifacts."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import click

from nokia_docs.db import record_build_manifest, validate_database, validate_metadata
from nokia_docs.index import index_cmd
from nokia_docs.pdf_index import index_pdfs
from nokia_docs.rn import index_release_notes
from nokia_docs.standards import index_standards


def sha256_file(path: Path) -> str:
    """Return the SHA256 hex digest for path."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_db_file(db_path: Path) -> tuple[dict[str, str], list[str]]:
    """Validate a DB file and return metadata plus errors."""
    conn = sqlite3.connect(Path(db_path))
    try:
        metadata = validate_metadata(conn)
        errors = validate_database(conn)
    finally:
        conn.close()
    return metadata, errors


def write_sha256_sidecar(db_path: Path) -> str:
    """Write and return a SHA256 sidecar for the final DB artifact."""
    sidecar = db_path.with_name(f"{db_path.name}.sha256")
    conn = sqlite3.connect(db_path)
    try:
        record_build_manifest(conn, {"artifact_sha256_file": sidecar.name})
    finally:
        conn.close()
    artifact_hash = sha256_file(db_path)
    sidecar.write_text(f"{artifact_hash}  {db_path.name}\n", encoding="utf-8")
    return artifact_hash


@click.command("build-db")
@click.option("--html-root", required=True, type=click.Path(exists=True, file_okay=False),
              help="Root directory containing Nokia WebHelp HTML documentation.")
@click.option("--rn-dir", required=True, type=click.Path(exists=True, file_okay=False),
              help="Directory containing rn_*.csv and rn_eol.json.")
@click.option("--pdf-dir", required=True, type=click.Path(exists=True, file_okay=False),
              help="Directory containing Nokia chassis installation guide PDFs.")
@click.option("-o", "--output", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="Output SQLite database path.")
@click.option("--workers", default=0, type=int,
              help="HTML parser worker processes (default: CPU count).")
@click.option("--strict/--no-strict", default=True, show_default=True,
              help="Fail when any source indexing step reports missing or failed inputs.")
@click.option("--standards-file", "standards_files", multiple=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Optional standards compliance XLSX file. Can be supplied more than once.")
def build_db_cmd(
    html_root: str,
    rn_dir: str,
    pdf_dir: str,
    output: str,
    workers: int,
    strict: bool,
    standards_files: tuple[str, ...],
) -> None:
    """Build a complete Nokia documentation search database artifact."""
    db_path = Path(output).resolve()
    click.echo("Building Nokia documentation search DB")
    click.echo(f"Output   : {db_path}")
    click.echo(f"HTML root: {Path(html_root).resolve()}")
    click.echo(f"RN dir   : {Path(rn_dir).resolve()}")
    click.echo(f"PDF dir  : {Path(pdf_dir).resolve()}")
    click.echo()

    index_cmd.callback(
        docs_root=html_root,
        output=str(db_path),
        reset=True,
        workers=workers,
        fail_on_error=strict,
    )
    index_release_notes(db_path, Path(rn_dir), fail_on_error=strict)
    index_pdfs(db_path, Path(pdf_dir), fail_on_error=strict)
    if standards_files:
        index_standards(db_path, [Path(p) for p in standards_files])

    artifact_hash = write_sha256_sidecar(db_path)
    metadata, errors = validate_db_file(db_path)
    if errors:
        for error in errors:
            click.echo(f"ERROR: {error}")
        raise click.ClickException(f"Database validation failed with {len(errors)} error(s).")

    click.echo("\nDatabase validation OK")
    click.echo(f"Schema version: {metadata['schema_version']}")
    click.echo(f"SHA256: {artifact_hash}")
