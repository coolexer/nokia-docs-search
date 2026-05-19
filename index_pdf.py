"""Index Nokia chassis installation guide PDFs into nokia_docs.db.

PDFs are de-duplicated automatically (latest issue per document number).
Only the highest-issue revision of each Nokia document number is indexed.

Usage:
    python index_pdf.py [--db path/to/nokia_docs.db] [--pdf-dir path/to/pdfs]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow importing from the src/ package
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nokia_docs.parse_pdf import deduplicate_pdfs, parse_pdf
from index_rn import _open_db, _insert_batch

# ---- Argument parsing -------------------------------------------------------

_DEFAULT_PDF_DIR = Path(r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide")

def _arg(flag: str, default: str) -> str:
    args = sys.argv[1:]
    if flag in args:
        return args[args.index(flag) + 1]
    return default


DB_PATH  = Path(_arg("--db",      "nokia_docs.db"))
PDF_DIR  = Path(_arg("--pdf-dir", str(_DEFAULT_PDF_DIR)))


# ---- Main -------------------------------------------------------------------

def main() -> None:
    pdf_dir = PDF_DIR

    print(f"DB      : {DB_PATH.resolve()}")
    print(f"PDF dir : {pdf_dir.resolve()}")

    if not pdf_dir.exists():
        print(f"[!] PDF directory not found: {pdf_dir}")
        sys.exit(1)

    pdfs = deduplicate_pdfs(pdf_dir)
    print(f"PDFs    : {len(pdfs)} (after de-duplication)")
    print(f"DB size before: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print()

    conn = _open_db(DB_PATH)
    total = 0
    t0 = time.monotonic()

    for i, pdf_path in enumerate(pdfs, 1):
        short = pdf_path.name[:60]
        print(f"[{i:3d}/{len(pdfs)}] {short}...", end=" ", flush=True)
        try:
            records = parse_pdf(pdf_path)
            inserted = _insert_batch(conn, records)
            print(f"{len(records)} sections, {inserted} inserted")
            total += inserted
        except Exception as exc:
            print(f"ERROR: {exc}")

    print(f"\nOptimizing FTS5 index...")
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Total install-guide chunks inserted: {total:,}")
    print(f"DB size after: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
