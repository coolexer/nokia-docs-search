"""Remove old RN entries and re-index with improved body format."""
import sqlite3, sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else 'nokia_docs.db')

print(f'DB: {DB}  ({DB.stat().st_size/1024/1024:.1f} MB)')

conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA synchronous=NORMAL')

# Delete all RN product lines
rn_products = ['rn-sros', 'rn-srl', 'rn-sas', 'rn-eda', 'rn-mag-c']
for pl in rn_products:
    # Get IDs first
    ids = [r[0] for r in conn.execute(
        'SELECT id FROM docs WHERE product_line=?', (pl,)
    ).fetchall()]
    if not ids:
        print(f'  {pl}: 0 rows (nothing to delete)')
        continue

    # Delete from FTS
    for doc_id in ids:
        conn.execute('DELETE FROM docs_fts WHERE rowid=?', (doc_id,))
    # Delete body and docs
    conn.execute(f"DELETE FROM docs_body WHERE id IN ({','.join('?'*len(ids))})", ids)
    conn.execute(f"DELETE FROM docs WHERE product_line=?", (pl,))
    print(f'  Deleted {len(ids)} rows for {pl}')

conn.commit()
print(f'After delete: {DB.stat().st_size/1024/1024:.1f} MB')
print()
conn.close()

# Re-run the indexer
import index_rn
index_rn.DB_PATH = DB
index_rn.main()
