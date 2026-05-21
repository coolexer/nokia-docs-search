"""Compatibility wrapper for re-indexing Nokia chassis installation guide PDFs.

Prefer:
    nokia-docs reindex-pdf --db nokia_docs.db --pdf-dir <pdf_dir>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from nokia_docs.pdf_index import reindex_pdfs


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove old install-guide rows and re-index PDFs.")
    parser.add_argument("db", nargs="?", default="nokia_docs.db")
    parser.add_argument("pdf_dir")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()
    reindex_pdfs(Path(args.db), Path(args.pdf_dir), fail_on_error=args.fail_on_error)


if __name__ == "__main__":
    main()
