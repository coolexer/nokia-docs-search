"""Compatibility wrapper for indexing Nokia release notes.

Prefer:
    nokia-docs index-rn --db nokia_docs.db --rn-dir .
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from nokia_docs.db import insert_records as _insert_batch
from nokia_docs.db import open_write_db as _open_db
from nokia_docs.rn import (
    _build_body,
    _build_body_eol,
    _slug,
    _strip_html,
    index_release_notes,
    load_csv_product,
    load_eol_json,
    main as _cli_main,
)


DB_PATH = Path("nokia_docs.db")
RN_DIR = Path(".")


def main(argv: list[str] | None = None) -> None:
    """Run as CLI, or honor DB_PATH/RN_DIR when imported by legacy callers."""
    if argv is not None:
        _cli_main(argv)
        return
    if Path(sys.argv[0]).resolve() == Path(__file__).resolve():
        _cli_main(sys.argv[1:])
        return
    index_release_notes(DB_PATH, RN_DIR)


if __name__ == "__main__":
    main()
