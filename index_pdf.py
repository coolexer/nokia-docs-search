"""Compatibility wrapper for indexing Nokia chassis installation guide PDFs.

Prefer:
    nokia-docs index-pdf --db nokia_docs.db --pdf-dir <pdf_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from nokia_docs.pdf_index import DEFAULT_PDF_DIR, index_pdfs
from nokia_docs.pdf_index import main as _cli_main

DB_PATH = Path("nokia_docs.db")
PDF_DIR = DEFAULT_PDF_DIR


def main(argv: list[str] | None = None) -> None:
    """Run as CLI, or honor DB_PATH/PDF_DIR when imported by legacy callers."""
    if argv is not None:
        _cli_main(argv)
        return
    if Path(sys.argv[0]).resolve() == Path(__file__).resolve():
        _cli_main(sys.argv[1:])
        return
    index_pdfs(DB_PATH, PDF_DIR)


if __name__ == "__main__":
    main()
