"""Click CLI entrypoint: nokia-docs <command>"""
import click

from nokia_docs.index import index_cmd
from nokia_docs.pdf_index import DEFAULT_PDF_DIR, index_pdfs, reindex_pdfs
from nokia_docs.rn import index_release_notes, reindex_release_notes


@click.group()
def main():
    """Nokia documentation search tools."""
    pass


main.add_command(index_cmd, name="index")


@main.command("index-rn")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="SQLite database path.")
@click.option("--rn-dir", default=".", show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing rn_*.csv and rn_eol.json.")
def index_rn_cmd(db_path: str, rn_dir: str):
    """Index Nokia release notes CSV/JSON files."""
    from pathlib import Path
    index_release_notes(Path(db_path), Path(rn_dir))


@main.command("reindex-rn")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
@click.option("--rn-dir", default=".", show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing rn_*.csv and rn_eol.json.")
def reindex_rn_cmd(db_path: str, rn_dir: str):
    """Remove existing release notes and index them again."""
    from pathlib import Path
    reindex_release_notes(Path(db_path), Path(rn_dir))


@main.command("index-pdf")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(dir_okay=False),
              help="SQLite database path.")
@click.option("--pdf-dir", default=str(DEFAULT_PDF_DIR), show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing Nokia chassis installation guide PDFs.")
def index_pdf_cmd(db_path: str, pdf_dir: str):
    """Index Nokia chassis installation guide PDFs."""
    from pathlib import Path
    index_pdfs(Path(db_path), Path(pdf_dir))


@main.command("reindex-pdf")
@click.option("--db", "db_path", default="nokia_docs.db", show_default=True,
              type=click.Path(exists=True, dir_okay=False),
              help="SQLite database path.")
@click.option("--pdf-dir", default=str(DEFAULT_PDF_DIR), show_default=True,
              type=click.Path(file_okay=False),
              help="Directory containing Nokia chassis installation guide PDFs.")
def reindex_pdf_cmd(db_path: str, pdf_dir: str):
    """Remove existing installation guide rows and index PDFs again."""
    from pathlib import Path
    reindex_pdfs(Path(db_path), Path(pdf_dir))


@main.command("serve")
def serve_cmd():
    """Start the MCP server (reads NOKIA_DOCS_DB env var)."""
    from nokia_docs.server import mcp
    mcp.run()
