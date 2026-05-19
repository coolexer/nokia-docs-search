"""Drop all install-guides rows from the DB and re-index from PDFs.

Usage:
    python reindex_pdf.py [nokia_docs.db] [pdf_dir]
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "nokia_docs.db")
PDF_DIR = Path(sys.argv[2] if len(sys.argv) > 2 else
               r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide")

# Pre-condition checks before any destructive operation.
if not DB.exists():
    print(f"[!] DB not found: {DB}")
    sys.exit(1)
if not PDF_DIR.exists():
    print(f"[!] PDF directory not found: {PDF_DIR}")
    sys.exit(1)

print(f"DB: {DB}  ({DB.stat().st_size / 1024 / 1024:.1f} MB)")

conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")

# Delete all install-guides rows in a single transaction.
# The per-row FTS delete loop used earlier was both slow (one implicit transaction
# per DELETE) and left the DB in a partial state if interrupted.
try:
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM docs WHERE product_line='install-guides'"
    ).fetchall()]

    if ids:
        conn.execute("BEGIN")
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM docs_fts WHERE rowid IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM docs_body WHERE id IN ({placeholders})", ids)
        conn.execute("DELETE FROM docs WHERE product_line='install-guides'")
        conn.commit()
        print(f"Deleted {len(ids)} install-guides rows")
    else:
        print("No install-guides rows to delete")
finally:
    conn.close()
print(f"After delete: {DB.stat().st_size / 1024 / 1024:.1f} MB")
print()

# Re-index
sys.path.insert(0, str(Path(__file__).parent / "src"))
import index_pdf
index_pdf.DB_PATH = DB
index_pdf.PDF_DIR = PDF_DIR
index_pdf.main()
