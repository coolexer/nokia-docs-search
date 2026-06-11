"""Click CLI entrypoint: nokia-docs <command>"""
import click

from nokia_docs.build import build_db_cmd
from nokia_docs.db import read_build_manifest, validate_database, validate_metadata
from nokia_docs.index import index_cmd
from nokia_docs.pdf_index import index_pdfs, reindex_pdfs
from nokia_docs.rn import index_release_notes, reindex_release_notes
from nokia_docs.standards import index_standards, reindex_standards


@click.group()
def main():
    """Nokia documentation search tools."""
    pass


main.add_command(index_cmd, name="index")
main.add_command(build_db_cmd, name="build-db")


@main.command("index-rn")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="SQLite database path.")
@click.option("--rn-dir", default=".", show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing rn_*.csv and rn_eol.json.")
@click.option("--fail-on-error", is_flag=True,
              help="Exit with an error if any expected RN source is missing or empty.")
def index_rn_cmd(db_path: str, rn_dir: str, fail_on_error: bool):
    """Index Nokia release notes CSV/JSON files."""
    from pathlib import Path
    index_release_notes(Path(db_path), Path(rn_dir), fail_on_error=fail_on_error)


@main.command("reindex-rn")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
@click.option("--rn-dir", default=".", show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing rn_*.csv and rn_eol.json.")
@click.option("--fail-on-error", is_flag=True,
              help="Exit with an error if any expected RN source is missing or empty.")
def reindex_rn_cmd(db_path: str, rn_dir: str, fail_on_error: bool):
    """Remove existing release notes and index them again."""
    from pathlib import Path
    reindex_release_notes(Path(db_path), Path(rn_dir), fail_on_error=fail_on_error)


@main.command("validate-db")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
def validate_db_cmd(db_path: str):
    """Validate a Nokia documentation search database."""
    import sqlite3
    from pathlib import Path

    conn = sqlite3.connect(Path(db_path))
    try:
        metadata = validate_metadata(conn)
        errors = validate_database(conn)
        manifest = read_build_manifest(conn)
    finally:
        conn.close()

    if errors:
        for error in errors:
            click.echo(f"ERROR: {error}")
        raise click.ClickException(f"Database validation failed with {len(errors)} error(s).")

    click.echo("Database validation OK")
    click.echo(f"Schema version: {metadata['schema_version']}")
    if manifest:
        click.echo(f"Build manifest entries: {len(manifest)}")


@main.command("index-pdf")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="SQLite database path.")
@click.option("--pdf-dir", required=True,
              type=click.Path(file_okay=False),
              help="Directory containing Nokia chassis installation guide PDFs.")
@click.option("--fail-on-error", is_flag=True,
              help="Exit with an error if any PDF fails to parse.")
def index_pdf_cmd(db_path: str, pdf_dir: str, fail_on_error: bool):
    """Index Nokia chassis installation guide PDFs."""
    from pathlib import Path
    index_pdfs(Path(db_path), Path(pdf_dir), fail_on_error=fail_on_error)


@main.command("reindex-pdf")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
@click.option("--pdf-dir", required=True,
              type=click.Path(file_okay=False),
              help="Directory containing Nokia chassis installation guide PDFs.")
@click.option("--fail-on-error", is_flag=True,
              help="Exit with an error if any PDF fails to parse.")
def reindex_pdf_cmd(db_path: str, pdf_dir: str, fail_on_error: bool):
    """Remove existing installation guide rows and index PDFs again."""
    from pathlib import Path
    reindex_pdfs(Path(db_path), Path(pdf_dir), fail_on_error=fail_on_error)


@main.command("index-standards")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="SQLite database path.")
@click.option("--standards-file", "standards_files", multiple=True, required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Standards compliance XLSX file. Can be supplied more than once.")
@click.option("--product", default=None,
              help="Optional product override for a single standards file: sros or srlinux.")
def index_standards_cmd(db_path: str, standards_files: tuple[str, ...], product: str | None):
    """Index Nokia standards compliance spreadsheets."""
    from pathlib import Path
    index_standards(Path(db_path), [Path(p) for p in standards_files], product=product)


@main.command("reindex-standards")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
@click.option("--standards-file", "standards_files", multiple=True, required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Standards compliance XLSX file. Can be supplied more than once.")
@click.option("--product", default=None,
              help="Optional product override for a single standards file: sros or srlinux.")
def reindex_standards_cmd(db_path: str, standards_files: tuple[str, ...], product: str | None):
    """Remove existing standards rows and index standards spreadsheets again."""
    from pathlib import Path
    reindex_standards(Path(db_path), [Path(p) for p in standards_files], product=product)


@main.command("serve")
def serve_cmd():
    """Start the MCP server (reads NOKIA_DOCS_DB env var)."""
    from nokia_docs.server import mcp
    mcp.run()
