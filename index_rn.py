"""
Index Nokia Release Notes CSV files into the existing nokia_docs.db.

CSV files must be pre-downloaded (run download_all_rn.py first).

Usage:
    python index_rn.py [--db path/to/nokia_docs.db]
"""
from __future__ import annotations
import csv
import io
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser


def _strip_html(text: str) -> str:
    """Strip HTML tags from text; collapse whitespace."""
    if not text or '<' not in text:
        return text
    try:
        tree = LexborHTMLParser(text)
        plain = tree.body.text(deep=True, separator=" ", strip=True) if tree.body else text
    except Exception:
        # Fallback: regex strip
        plain = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', plain).strip()

DB_PATH = Path(sys.argv[sys.argv.index('--db') + 1] if '--db' in sys.argv
               else 'nokia_docs.db')
RN_DIR  = Path('.')  # CSV files in current directory

# ---- Product metadata -------------------------------------------------------

_RN_DISPLAY = {
    'sros':  'Nokia SR OS',
    'srl':   'Nokia SR Linux',
    'sas':   'Nokia 7210 SAS',
    'mag-c': 'Nokia MAG-c',
    'eda':   'Nokia EDA',
}

# ---- Helpers ----------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _build_body(row: dict, product: str) -> str:
    parts: list[str] = []

    title = row.get('title', '').strip()
    if title:
        parts.append(title)
        parts.append('')

    section = row.get('section', '').strip()
    if section:
        parts.append(f'Section: {section}')

    releases = [r.strip() for r in row.get('releaseList', '').split('|') if r.strip()]
    if releases:
        # Store full versions (26.3.R1) + short versions (26.3) for FTS matching
        short = sorted({".".join(r.split(".")[:2]) for r in releases if "." in r})
        extra = [s for s in short if s not in releases]
        release_str = ", ".join(releases)
        if extra:
            release_str += f" ({', '.join(extra)})"
        parts.append(f'Releases: {release_str}')

    platforms = [p.strip() for p in row.get('platforms', '').split('|') if p.strip()]
    if platforms:
        parts.append(f'Platforms: {", ".join(platforms)}')

    ux_a_raw = row.get('ux-a', '').strip()
    if ux_a_raw:
        ux_a_list = [x.strip() for x in ux_a_raw.split('|') if x.strip()]
        parts.append(f'Functional area: {", ".join(ux_a_list)}')

    refs = [r.strip() for r in row.get('ref', '').split('|') if r.strip()]
    if refs:
        parts.append(f'Reference: {" ".join(refs)}')

    number = row.get('number', '').strip()
    if number:
        parts.append(f'RN number: {number}')

    text = _strip_html(row.get('text', ''))
    if text:
        parts.append('')
        parts.append(text)

    return '\n'.join(parts)


def _build_body_eol(entry: dict) -> str:
    parts: list[str] = []

    title = entry.get('title', '').strip()
    if title:
        parts.append(title)
        parts.append('')

    etype = entry.get('type', '').strip()
    if etype:
        parts.append(f'Section: {etype}')

    rel = entry.get('rel', '').strip()
    if rel:
        # Also add short version (e.g. "19.10" for "19.10.R12")
        short = ".".join(rel.split(".")[:2]) if "." in rel else ""
        rel_str = rel if not short or short == rel else f"{rel} ({short})"
        parts.append(f'Releases: {rel_str}')

    ux_a = entry.get('ux-a', '').strip()
    if ux_a:
        parts.append(f'Functional area: {ux_a}')

    ref = entry.get('ref', '').strip()
    if ref:
        parts.append(f'Reference: {ref}')

    text = _strip_html(entry.get('text', ''))
    if text:
        parts.append('')
        parts.append(text)

    return '\n'.join(parts)


# ---- Insertion --------------------------------------------------------------

_SCHEMA_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS docs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_line   TEXT NOT NULL,
    book           TEXT NOT NULL,
    rel_path       TEXT NOT NULL,
    page_title     TEXT NOT NULL,
    section_id     TEXT NOT NULL,
    section_title  TEXT NOT NULL,
    section_path   TEXT NOT NULL,
    depth          INTEGER NOT NULL DEFAULT 0,
    char_len       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(rel_path, section_id)
);
CREATE TABLE IF NOT EXISTS docs_body (
    id   INTEGER PRIMARY KEY,
    body TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    section_title,
    page_title,
    section_path,
    body,
    tokenize = "unicode61 remove_diacritics 2 tokenchars '-_.'"
);
CREATE INDEX IF NOT EXISTS idx_docs_product ON docs(product_line);
CREATE INDEX IF NOT EXISTS idx_docs_book    ON docs(product_line, book);
"""


def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-32000')
    conn.executescript(_SCHEMA_BOOTSTRAP)
    conn.commit()
    return conn


def _insert_batch(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    conn.execute('BEGIN')
    for r in rows:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO docs
                   (product_line, book, rel_path, page_title, section_id,
                    section_title, section_path, depth, char_len)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (r['product_line'], r['book'], r['rel_path'], r['page_title'],
                 r['section_id'], r['section_title'], r['section_path'],
                 r['depth'], r['char_len']),
            )
            if cur.lastrowid and cur.rowcount:
                conn.execute(
                    'INSERT OR IGNORE INTO docs_body (id, body) VALUES (?,?)',
                    (cur.lastrowid, r['body']),
                )
                conn.execute(
                    """INSERT INTO docs_fts
                       (rowid, section_title, page_title, section_path, body)
                       VALUES (?,?,?,?,?)""",
                    (cur.lastrowid, r['section_title'], r['page_title'],
                     r['section_path'], r['body']),
                )
                inserted += 1
        except sqlite3.Error as e:
            print(f'  Warning: insert failed: {e}')
    conn.execute('COMMIT')
    return inserted


# ---- CSV loader -------------------------------------------------------------

def load_csv_product(product: str) -> list[dict]:
    csv_file = RN_DIR / f'rn_{product}.csv'
    if not csv_file.exists():
        print(f'  [!] {csv_file} not found, skipping')
        return []

    text = csv_file.read_text(encoding='utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    all_rows = list(reader)

    if not all_rows:
        return []

    # First row is context row (metadata)
    data_rows = all_rows[1:]  # skip context row
    display = _RN_DISPLAY.get(product, product)
    product_line = f'rn-{product}'

    records: list[dict] = []
    for idx, row in enumerate(data_rows):
        title = row.get('title', '').strip()
        if not title:
            continue  # skip empty rows

        section = row.get('section', '').strip() or 'General'
        section_slug = _slug(section)

        releases = [r.strip() for r in row.get('releaseList', '').split('|') if r.strip()]
        # Use first release for page grouping
        first_release = releases[0] if releases else 'unknown'
        release_slug = _slug(first_release)

        number = row.get('number', '').strip()
        section_id = number if number else f'rn-{idx+1}'

        rel_path = f'rn/{product}/{release_slug}/{section_slug}.html'
        page_title = f'{display} {first_release} Release Notes'
        # Include release in section_path so FTS ranks "26.3.R1 EVPN" queries better
        section_path = f'{first_release} {section} > {title}'

        body = _build_body(row, product)

        records.append({
            'product_line': product_line,
            'book':         section_slug,
            'rel_path':     rel_path,
            'page_title':   page_title,
            'section_id':   section_id,
            'section_title': title,
            'section_path': section_path,
            'depth':        0,
            'char_len':     len(body),
            'body':         body,
        })

    return records


def load_eol_json() -> list[dict]:
    eol_file = RN_DIR / 'rn_eol.json'
    if not eol_file.exists():
        print('  [!] rn_eol.json not found, skipping')
        return []

    entries = json.loads(eol_file.read_text(encoding='utf-8'))
    records: list[dict] = []

    for idx, entry in enumerate(entries):
        text = entry.get('text', '').strip()
        title = entry.get('title', '').strip()
        if not title and not text:
            continue
        if not title:
            # Use first line of text as title
            title = text.split('\n')[0][:120]

        rel = entry.get('rel', 'historical').strip()
        etype = entry.get('type', 'General').strip()
        section_slug = _slug(etype)
        release_slug = _slug(rel)

        section_id = f'eol-{idx}'
        rel_path = f'rn/sros/{release_slug}/historical-{section_slug}.html'
        page_title = f'Nokia SR OS {rel} Release Notes'
        section_path = f'Historical > {etype} > {title}'

        body = _build_body_eol(entry)

        records.append({
            'product_line': 'rn-sros',
            'book':         section_slug,
            'rel_path':     rel_path,
            'page_title':   page_title,
            'section_id':   section_id,
            'section_title': title,
            'section_path': section_path,
            'depth':        0,
            'char_len':     len(body),
            'body':         body,
        })

    return records


# ---- Main -------------------------------------------------------------------

def main():
    print(f'DB: {DB_PATH.resolve()}')
    print(f'DB size before: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB')
    print()

    conn = _open_db(DB_PATH)

    PRODUCTS = ['sros', 'srl', 'sas', 'mag-c', 'eda']
    total = 0
    t0 = time.monotonic()

    for product in PRODUCTS:
        print(f'Loading {product}...', end=' ', flush=True)
        records = load_csv_product(product)
        print(f'{len(records)} entries...', end=' ', flush=True)
        inserted = _insert_batch(conn, records)
        print(f'inserted {inserted}')
        total += inserted

    # EOL JSON (SR OS historical)
    print(f'Loading rn-eol.json...', end=' ', flush=True)
    eol_records = load_eol_json()
    print(f'{len(eol_records)} entries...', end=' ', flush=True)
    inserted = _insert_batch(conn, eol_records)
    print(f'inserted {inserted}')
    total += inserted

    print(f'\nOptimizing FTS5 index...')
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    elapsed = time.monotonic() - t0
    print(f'\nDone in {elapsed:.1f}s')
    print(f'Total RN records inserted: {total:,}')
    print(f'DB size after: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB')


if __name__ == '__main__':
    main()
