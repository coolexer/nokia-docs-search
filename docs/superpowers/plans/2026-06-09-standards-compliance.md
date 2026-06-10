# Standards Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SR OS and SR Linux standards-compliance XLSX data to the Nokia docs MCP as both structured standards search and shared FTS search content.

**Architecture:** Add an additive SQLite schema extension for standards tables, a focused `standards.py` parser/indexer/search module, CLI commands for index/reindex, and MCP tools for standards lookups. Supported standards also get mirrored into `docs`, `docs_body`, and `docs_fts` so existing `search_docs` calls can find them.

**Tech Stack:** Python 3.11+, SQLite FTS5, Click, FastMCP, pytest, openpyxl.

---

## File Structure

- Modify `pyproject.toml`: add `openpyxl>=3.1` dependency.
- Modify `src/nokia_docs/schema.sql`: add `standards_sources`, `standards`, `standards_fts`, and indexes.
- Modify `src/nokia_docs/db.py`: validate optional standards FTS/table consistency and add delete helper for standards product lines.
- Create `src/nokia_docs/standards.py`: parse XLSX files, index rows, reindex rows, search standards, list standards product summaries.
- Modify `src/nokia_docs/products.py`: add display names and standards alias helpers without changing existing `sros`/`srlinux` docs aliases.
- Modify `src/nokia_docs/cli.py`: expose `index-standards` and `reindex-standards`; extend `build-db` with repeated `--standards-file`.
- Modify `src/nokia_docs/build.py`: pass optional standards files into the one-shot build.
- Modify `src/nokia_docs/server.py`: expose `search_standards` and `list_standards_products`; update instructions.
- Modify `README.md`: document standards source support and commands.
- Add `tests/test_standards.py`: parser/index/search/unit coverage with generated XLSX fixtures.
- Modify `tests/test_cli.py`: command visibility coverage.
- Modify `tests/test_db_metadata.py`: optional standards validation coverage.

---

### Task 1: Add Standards Schema And Validation

**Files:**
- Modify: `src/nokia_docs/schema.sql`
- Modify: `src/nokia_docs/db.py`
- Test: `tests/test_db_metadata.py`

- [ ] **Step 1: Write failing validation tests**

Append to `tests/test_db_metadata.py`:

```python
def test_open_write_db_creates_standards_tables(tmp_path):
    db_path = tmp_path / "nokia_docs.db"
    conn = db.open_write_db(db_path)
    try:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "standards_sources" in table_names
    assert "standards" in table_names
    assert "standards_fts" in table_names


def test_validate_database_reports_standards_fts_mismatch(tmp_path):
    db_path = tmp_path / "broken-standards.db"
    conn = db.open_write_db(db_path)
    try:
        conn.execute(
            """INSERT INTO standards_sources
               (source_path, source_name, source_sha256, indexed_utc)
               VALUES ('fixture.xlsx', 'fixture.xlsx', 'abc', '2026-06-09T00:00:00+00:00')"""
        )
        source_id = conn.execute("SELECT id FROM standards_sources").fetchone()[0]
        conn.execute(
            """INSERT INTO standards
               (source_id, product_line, platform, release, group_title,
                standard_ref, standard_title, standard_text, support_status,
                sheet_name, row_number)
               VALUES (?, 'sros-standards', '7250 IXR', '26.3.R1', 'BFD',
                       'RFC 5880', 'Bidirectional Forwarding Detection',
                       'RFC 5880, Bidirectional Forwarding Detection (BFD)',
                       'supported', 'SR OS 26.3.R1 Standards', 2)""",
            (source_id,),
        )
        conn.commit()

        errors = db.validate_database(conn)
    finally:
        conn.close()

    assert "standards/standards_fts row count mismatch" in errors
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_db_metadata.py::test_open_write_db_creates_standards_tables tests/test_db_metadata.py::test_validate_database_reports_standards_fts_mismatch -v
```

Expected: FAIL because the standards tables do not exist yet.

- [ ] **Step 3: Add schema tables**

Append to `src/nokia_docs/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS standards_sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path    TEXT NOT NULL,
    source_name    TEXT NOT NULL,
    source_sha256  TEXT NOT NULL,
    indexed_utc    TEXT NOT NULL,
    UNIQUE(source_path, source_sha256)
);

CREATE TABLE IF NOT EXISTS standards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES standards_sources(id) ON DELETE CASCADE,
    product_line    TEXT NOT NULL,
    platform        TEXT NOT NULL,
    release         TEXT NOT NULL,
    group_title     TEXT NOT NULL,
    standard_ref    TEXT NOT NULL DEFAULT '',
    standard_title  TEXT NOT NULL DEFAULT '',
    standard_text   TEXT NOT NULL,
    support_status  TEXT NOT NULL,
    sheet_name      TEXT NOT NULL,
    row_number      INTEGER NOT NULL,
    UNIQUE(product_line, platform, release, group_title, standard_text, sheet_name, row_number)
);

CREATE INDEX IF NOT EXISTS idx_standards_product ON standards(product_line);
CREATE INDEX IF NOT EXISTS idx_standards_filters
    ON standards(product_line, platform, release, support_status);
CREATE INDEX IF NOT EXISTS idx_standards_ref ON standards(standard_ref);

CREATE VIRTUAL TABLE IF NOT EXISTS standards_fts USING fts5(
    product_line,
    platform,
    release,
    group_title,
    standard_ref,
    standard_title,
    standard_text,
    tokenize = "unicode61 remove_diacritics 2 tokenchars '-_.'"
);
```

- [ ] **Step 4: Add standards validation**

In `src/nokia_docs/db.py`, inside `validate_database`, after the docs orphan checks, add:

```python
    standards_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        ).fetchall()
    }
    if {"standards", "standards_fts"}.issubset(standards_tables):
        standards_count = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
        standards_fts_count = conn.execute("SELECT COUNT(*) FROM standards_fts").fetchone()[0]
        if standards_count != standards_fts_count:
            errors.append(
                "standards/standards_fts row count mismatch: "
                f"standards={standards_count}, standards_fts={standards_fts_count}"
            )

        orphan_standards_fts = conn.execute(
            """SELECT COUNT(*)
               FROM standards_fts f
               LEFT JOIN standards s ON s.id = f.rowid
               WHERE s.id IS NULL"""
        ).fetchone()[0]
        if orphan_standards_fts:
            errors.append(f"orphan standards_fts rows: {orphan_standards_fts}")
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```powershell
pytest tests/test_db_metadata.py::test_open_write_db_creates_standards_tables tests/test_db_metadata.py::test_validate_database_reports_standards_fts_mismatch -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/nokia_docs/schema.sql src/nokia_docs/db.py tests/test_db_metadata.py
git commit -m "Add standards database schema"
```

---

### Task 2: Build Standards Parser

**Files:**
- Modify: `pyproject.toml`
- Create: `src/nokia_docs/standards.py`
- Test: `tests/test_standards.py`

- [ ] **Step 1: Add failing parser tests**

Create `tests/test_standards.py`:

```python
from pathlib import Path

import openpyxl

from nokia_docs.standards import parse_standards_workbook


def _save_workbook(path: Path, title: str, rows: list[list[str | None]]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_parse_sros_multiplatform_standards(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "sros.xlsx",
        "SR OS 26.3.R1 Standards",
        [
            [
                "Group Title",
                "7450 ESS, 7750 SR, 7950 XRS, VSR Standards",
                "7250 IXR Standards",
                "7705 SAR Gen 2 Standards",
            ],
            [
                "Bidirectional Forwarding Detection (BFD)",
                "RFC 5880, Bidirectional Forwarding Detection (BFD)",
                "RFC 5880, Bidirectional Forwarding Detection (BFD)",
                "Not Supported",
            ],
        ],
    )

    records = parse_standards_workbook(workbook)

    assert len(records) == 3
    assert records[0].product_line == "sros-standards"
    assert records[0].platform == "7450 ESS / 7750 SR / 7950 XRS / VSR"
    assert records[0].release == "26.3.R1"
    assert records[0].standard_ref == "RFC 5880"
    assert records[0].standard_title == "Bidirectional Forwarding Detection (BFD)"
    assert records[2].platform == "7705 SAR Gen2"
    assert records[2].support_status == "not_supported"


def test_parse_srlinux_ignores_blank_trailing_column(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "srlinux.xlsx",
        "SR Linux 26.3.1 Standards",
        [
            ["Group Title", "SR Linux Standards", ""],
            [
                "Border Gateway Protocol (BGP)",
                "RFC 1997, {BGP Communities Attribute}",
                "",
            ],
        ],
    )

    records = parse_standards_workbook(workbook)

    assert len(records) == 1
    assert records[0].product_line == "srlinux-standards"
    assert records[0].platform == "SR Linux"
    assert records[0].release == "26.3.1"
    assert records[0].standard_ref == "RFC 1997"
    assert records[0].standard_title == "BGP Communities Attribute"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_standards.py::test_parse_sros_multiplatform_standards tests/test_standards.py::test_parse_srlinux_ignores_blank_trailing_column -v
```

Expected: FAIL because `nokia_docs.standards` does not exist.

- [ ] **Step 3: Add dependency**

Modify `pyproject.toml` dependencies:

```toml
dependencies = [
    "fastmcp>=2.0",
    "selectolax>=0.3",
    "click>=8.1",
    "pymupdf>=1.24",
    "openpyxl>=3.1",
]
```

- [ ] **Step 4: Implement parser**

Create `src/nokia_docs/standards.py` with:

```python
"""Index and search Nokia standards compliance spreadsheets."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import click
import openpyxl

from nokia_docs.db import insert_records, open_write_db, record_build_manifest


SROS_STANDARDS = "sros-standards"
SRLINUX_STANDARDS = "srlinux-standards"
STANDARDS_PRODUCT_LINES = [SROS_STANDARDS, SRLINUX_STANDARDS]


@dataclass(frozen=True)
class StandardsRecord:
    product_line: str
    platform: str
    release: str
    group_title: str
    standard_ref: str
    standard_title: str
    standard_text: str
    support_status: str
    sheet_name: str
    row_number: int


@dataclass
class StandardsIndexReport:
    inserted: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    db_size_mb: float = 0.0


@dataclass
class StandardsHit:
    id: int
    product_line: str
    platform: str
    release: str
    group_title: str
    standard_ref: str
    standard_title: str
    standard_text: str
    support_status: str
    source_name: str
    sheet_name: str
    row_number: int
    score: float = 0.0


@dataclass
class StandardsProductInfo:
    product_line: str
    platforms: list[str]
    releases: list[str]
    num_records: int
    source_names: list[str]


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_platform(header: str) -> str:
    text = _normalize_text(header)
    text = re.sub(r"\s+Standards$", "", text, flags=re.IGNORECASE)
    if text == "List of Standards in this Group":
        return "7450 ESS / 7750 SR / 7950 XRS / VSR"
    if text == "7450 ESS, 7750 SR, 7950 XRS, VSR":
        return "7450 ESS / 7750 SR / 7950 XRS / VSR"
    if text == "7705 SAR Gen 2":
        return "7705 SAR Gen2"
    return text


def _infer_product(sheet_name: str, explicit_product: str | None = None) -> str:
    if explicit_product:
        normalized = explicit_product.strip().lower().replace("_", "-")
        if normalized in {"sros", "sr-os", "sr os", "sros-standards"}:
            return SROS_STANDARDS
        if normalized in {"srl", "srlinux", "sr-linux", "sr linux", "srlinux-standards"}:
            return SRLINUX_STANDARDS
    if sheet_name.lower().startswith("sr linux"):
        return SRLINUX_STANDARDS
    return SROS_STANDARDS


def _extract_release(sheet_name: str) -> str:
    match = re.search(r"(?:SR OS|SR Linux)\s+([0-9][0-9.]*?(?:\.R\d+)?)\s+Standards", sheet_name)
    return match.group(1) if match else ""


def split_standard_text(text: str) -> tuple[str, str]:
    normalized = _normalize_text(text).replace("{", "").replace("}", "")
    patterns = [
        r"^(RFC\s+\d+)\s*,?\s*(.*)$",
        r"^((?:draft|RFC|IEEE|ITU-T|MEF|BBF|AF|GR|IETF|ISO|IEC|3GPP)[^,]*?)\s*,?\s*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return "", normalized


def parse_standards_workbook(
    path: Path,
    product: str | None = None,
) -> list[StandardsRecord]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records: list[StandardsRecord] = []
    for sheet in workbook.worksheets:
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if not headers:
            continue
        product_line = _infer_product(sheet.title, product)
        release = _extract_release(sheet.title)
        platform_columns: list[tuple[int, str]] = []
        for idx, header_value in enumerate(headers[1:], start=1):
            header = _normalize_text(header_value)
            if not header or header.lower() == "comments":
                continue
            platform_columns.append((idx, _normalize_platform(header)))

        for row_number, row in enumerate(rows, start=2):
            group_title = _normalize_text(row[0] if row else "")
            if not group_title:
                continue
            for col_idx, platform in platform_columns:
                value = row[col_idx] if col_idx < len(row) else None
                standard_text = _normalize_text(value)
                if not standard_text:
                    continue
                support_status = (
                    "not_supported"
                    if standard_text.lower() == "not supported"
                    else "supported"
                )
                standard_ref, standard_title = split_standard_text(standard_text)
                records.append(
                    StandardsRecord(
                        product_line=product_line,
                        platform=platform,
                        release=release,
                        group_title=group_title,
                        standard_ref=standard_ref,
                        standard_title=standard_title,
                        standard_text=standard_text,
                        support_status=support_status,
                        sheet_name=sheet.title,
                        row_number=row_number,
                    )
                )
    workbook.close()
    return records
```

- [ ] **Step 5: Run parser tests to verify pass**

Run:

```powershell
pytest tests/test_standards.py::test_parse_sros_multiplatform_standards tests/test_standards.py::test_parse_srlinux_ignores_blank_trailing_column -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml src/nokia_docs/standards.py tests/test_standards.py
git commit -m "Add standards workbook parser"
```

---

### Task 3: Index Standards Into Structured Tables And Shared Docs FTS

**Files:**
- Modify: `src/nokia_docs/standards.py`
- Modify: `src/nokia_docs/db.py`
- Test: `tests/test_standards.py`

- [ ] **Step 1: Add failing indexing tests**

Append to `tests/test_standards.py`:

```python
import sqlite3

from nokia_docs.db import open_write_db
from nokia_docs.search import search_docs
from nokia_docs.standards import index_standards, reindex_standards


def test_index_standards_writes_structured_and_docs_fts_rows(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "sros.xlsx",
        "SR OS 26.3.R1 Standards",
        [
            ["Group Title", "7250 IXR Standards", "7705 SAR Gen 2 Standards"],
            [
                "Bidirectional Forwarding Detection (BFD)",
                "RFC 5880, Bidirectional Forwarding Detection (BFD)",
                "Not Supported",
            ],
        ],
    )
    db_path = tmp_path / "nokia_docs.db"

    report = index_standards(db_path, [workbook])

    assert report.inserted == 2
    conn = sqlite3.connect(db_path)
    try:
        standards_count = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
        standards_fts_count = conn.execute("SELECT COUNT(*) FROM standards_fts").fetchone()[0]
        docs_hits = search_docs("RFC 5880", conn, product_line="sros-standards")
    finally:
        conn.close()

    assert standards_count == 2
    assert standards_fts_count == 2
    assert [hit.section_title for hit in docs_hits] == ["RFC 5880"]


def test_reindex_standards_removes_only_standards_rows(tmp_path: Path):
    db_path = tmp_path / "nokia_docs.db"
    conn = open_write_db(db_path)
    try:
        conn.execute(
            """INSERT INTO docs
               (product_line, book, rel_path, page_title, section_id,
                section_title, section_path, depth, char_len)
               VALUES ('sros-26-3', 'mpls', 'doc.html', 'Doc', 'sec', 'Doc section', 'Doc', 0, 4)"""
        )
        doc_id = conn.execute("SELECT id FROM docs WHERE product_line='sros-26-3'").fetchone()[0]
        conn.execute("INSERT INTO docs_body (id, body) VALUES (?, 'body')", (doc_id,))
        conn.execute(
            """INSERT INTO docs_fts(rowid, section_title, page_title, section_path, body)
               VALUES (?, 'Doc section', 'Doc', 'Doc', 'body')""",
            (doc_id,),
        )
        conn.commit()
    finally:
        conn.close()

    workbook = _save_workbook(
        tmp_path / "srlinux.xlsx",
        "SR Linux 26.3.1 Standards",
        [
            ["Group Title", "SR Linux Standards"],
            ["Border Gateway Protocol (BGP)", "RFC 1997, BGP Communities Attribute"],
        ],
    )

    reindex_standards(db_path, [workbook])
    reindex_standards(db_path, [workbook])

    conn = sqlite3.connect(db_path)
    try:
        docs_product_lines = [
            row[0] for row in conn.execute("SELECT product_line FROM docs ORDER BY product_line")
        ]
        standards_count = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    finally:
        conn.close()

    assert "sros-26-3" in docs_product_lines
    assert docs_product_lines.count("srlinux-standards") == 1
    assert standards_count == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_standards.py::test_index_standards_writes_structured_and_docs_fts_rows tests/test_standards.py::test_reindex_standards_removes_only_standards_rows -v
```

Expected: FAIL because indexing functions do not exist yet.

- [ ] **Step 3: Add delete helper**

Add to `src/nokia_docs/db.py`:

```python
def delete_standards_product_lines(conn: sqlite3.Connection, product_lines: list[str]) -> int:
    """Delete standards rows and mirrored docs rows for the given standards product lines."""
    if not product_lines:
        return 0

    standards_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM standards WHERE product_line IN ({','.join('?' * len(product_lines))})",
            product_lines,
        ).fetchall()
    ]
    docs_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM docs WHERE product_line IN ({','.join('?' * len(product_lines))})",
            product_lines,
        ).fetchall()
    ]
    if not standards_ids and not docs_ids:
        return 0

    conn.execute("BEGIN")
    try:
        if standards_ids:
            placeholders = ",".join("?" * len(standards_ids))
            conn.execute(f"DELETE FROM standards_fts WHERE rowid IN ({placeholders})", standards_ids)
            conn.execute(f"DELETE FROM standards WHERE id IN ({placeholders})", standards_ids)
        if docs_ids:
            placeholders = ",".join("?" * len(docs_ids))
            conn.execute(f"DELETE FROM docs_fts WHERE rowid IN ({placeholders})", docs_ids)
            conn.execute(f"DELETE FROM docs_body WHERE id IN ({placeholders})", docs_ids)
            conn.execute(f"DELETE FROM docs WHERE id IN ({placeholders})", docs_ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return len(standards_ids)
```

- [ ] **Step 4: Implement indexing functions**

In `src/nokia_docs/standards.py`, extend imports:

```python
from nokia_docs.db import (
    delete_standards_product_lines,
    insert_records,
    open_write_db,
    record_build_manifest,
)
```

Then add:

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _docs_record(record: StandardsRecord) -> dict:
    title = record.standard_ref or record.standard_title or record.standard_text[:80]
    body = "\n".join(
        [
            record.standard_text,
            "",
            f"Product: {record.product_line}",
            f"Platform: {record.platform}",
            f"Release: {record.release}",
            f"Group: {record.group_title}",
            f"Support status: {record.support_status}",
            f"Source sheet: {record.sheet_name}",
            f"Source row: {record.row_number}",
        ]
    )
    return {
        "product_line": record.product_line,
        "book": "standards-compliance",
        "rel_path": f"standards/{record.product_line}/{record.release}/{record.sheet_name}.xlsx",
        "page_title": f"{record.product_line} {record.release} Standards Compliance",
        "section_id": (
            f"{record.platform}-{record.release}-{record.row_number}-"
            f"{record.standard_ref or record.standard_text}"
        )[:180],
        "section_title": title,
        "section_path": (
            f"{record.release} > {record.platform} > {record.group_title} > "
            f"{title}"
        ),
        "depth": 0,
        "char_len": len(body),
        "body": body,
    }


def _insert_standards_records(
    conn: sqlite3.Connection,
    source_id: int,
    records: list[StandardsRecord],
) -> int:
    inserted = 0
    conn.execute("BEGIN")
    try:
        for record in records:
            cur = conn.execute(
                """INSERT OR IGNORE INTO standards
                   (source_id, product_line, platform, release, group_title,
                    standard_ref, standard_title, standard_text, support_status,
                    sheet_name, row_number)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_id,
                    record.product_line,
                    record.platform,
                    record.release,
                    record.group_title,
                    record.standard_ref,
                    record.standard_title,
                    record.standard_text,
                    record.support_status,
                    record.sheet_name,
                    record.row_number,
                ),
            )
            if cur.lastrowid and cur.rowcount:
                standards_id = cur.lastrowid
                conn.execute(
                    """INSERT INTO standards_fts
                       (rowid, product_line, platform, release, group_title,
                        standard_ref, standard_title, standard_text)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        standards_id,
                        record.product_line,
                        record.platform,
                        record.release,
                        record.group_title,
                        record.standard_ref,
                        record.standard_title,
                        record.standard_text,
                    ),
                )
                inserted += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return inserted


def index_standards(
    db_path: Path,
    standards_files: list[Path],
    product: str | None = None,
) -> StandardsIndexReport:
    if product and len(standards_files) != 1:
        raise click.ClickException("--product can only be used with one --standards-file.")

    db_path = Path(db_path)
    conn = open_write_db(db_path)
    total = 0
    source_counts: dict[str, int] = {}
    t0 = time.monotonic()
    try:
        for standards_file in standards_files:
            path = Path(standards_file)
            digest = sha256_file(path)
            indexed_utc = datetime.now(UTC).isoformat(timespec="seconds")
            conn.execute(
                """INSERT OR IGNORE INTO standards_sources
                   (source_path, source_name, source_sha256, indexed_utc)
                   VALUES (?,?,?,?)""",
                (str(path.resolve()), path.name, digest, indexed_utc),
            )
            source_id = conn.execute(
                "SELECT id FROM standards_sources WHERE source_path=? AND source_sha256=?",
                (str(path.resolve()), digest),
            ).fetchone()[0]
            records = parse_standards_workbook(path, product=product)
            inserted = _insert_standards_records(conn, source_id, records)
            docs_inserted = insert_records(
                conn,
                [r for r in (_docs_record(record) for record in records) if r],
            )
            source_counts[path.name] = inserted
            total += inserted
            click.echo(f"Indexed {path.name}: standards={inserted}, docs={docs_inserted}")

        conn.execute("INSERT INTO standards_fts(standards_fts) VALUES('optimize')")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
        conn.commit()
        record_build_manifest(
            conn,
            {
                "standards_files": len(standards_files),
                "standards_records_inserted": total,
                **{f"standards_{key}_records": value for key, value in source_counts.items()},
            },
        )
    finally:
        conn.close()

    return StandardsIndexReport(
        inserted=total,
        source_counts=source_counts,
        elapsed_seconds=time.monotonic() - t0,
        db_size_mb=db_path.stat().st_size / 1024 / 1024,
    )


def reindex_standards(
    db_path: Path,
    standards_files: list[Path],
    product: str | None = None,
) -> StandardsIndexReport:
    db_path = Path(db_path)
    conn = open_write_db(db_path)
    try:
        deleted = delete_standards_product_lines(conn, STANDARDS_PRODUCT_LINES)
    finally:
        conn.close()
    click.echo(f"Deleted {deleted} existing standards rows")
    return index_standards(db_path, standards_files, product=product)
```

- [ ] **Step 5: Run indexing tests to verify pass**

Run:

```powershell
pytest tests/test_standards.py::test_index_standards_writes_structured_and_docs_fts_rows tests/test_standards.py::test_reindex_standards_removes_only_standards_rows -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/nokia_docs/db.py src/nokia_docs/standards.py tests/test_standards.py
git commit -m "Index standards compliance workbooks"
```

---

### Task 4: Add Structured Standards Search APIs

**Files:**
- Modify: `src/nokia_docs/standards.py`
- Test: `tests/test_standards.py`

- [ ] **Step 1: Add failing search tests**

Append to `tests/test_standards.py`:

```python
from nokia_docs.standards import list_standards_products, search_standards


def test_search_standards_filters_by_status_platform_release_and_group(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "sros.xlsx",
        "SR OS 26.3.R1 Standards",
        [
            ["Group Title", "7250 IXR Standards", "7705 SAR Gen 2 Standards"],
            ["BFD", "RFC 5880, Bidirectional Forwarding Detection", "Not Supported"],
            ["BGP", "RFC 1997, BGP Communities Attribute", "Not Supported"],
        ],
    )
    db_path = tmp_path / "nokia_docs.db"
    index_standards(db_path, [workbook])
    conn = sqlite3.connect(db_path)
    try:
        hits = search_standards(
            conn,
            query="RFC 5880",
            product_line="sros-standards",
            platform="7250",
            release="26.3.R1",
            group="BFD",
            support_status="supported",
        )
    finally:
        conn.close()

    assert len(hits) == 1
    assert hits[0].standard_ref == "RFC 5880"
    assert hits[0].platform == "7250 IXR"


def test_list_standards_products_returns_summary(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "srlinux.xlsx",
        "SR Linux 26.3.1 Standards",
        [
            ["Group Title", "SR Linux Standards"],
            ["BGP", "RFC 1997, BGP Communities Attribute"],
        ],
    )
    db_path = tmp_path / "nokia_docs.db"
    index_standards(db_path, [workbook])
    conn = sqlite3.connect(db_path)
    try:
        products = list_standards_products(conn)
    finally:
        conn.close()

    assert len(products) == 1
    assert products[0].product_line == "srlinux-standards"
    assert products[0].platforms == ["SR Linux"]
    assert products[0].releases == ["26.3.1"]
    assert products[0].num_records == 1
    assert products[0].source_names == ["srlinux.xlsx"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_standards.py::test_search_standards_filters_by_status_platform_release_and_group tests/test_standards.py::test_list_standards_products_returns_summary -v
```

Expected: FAIL because query APIs do not exist yet.

- [ ] **Step 3: Implement search helpers**

Append to `src/nokia_docs/standards.py`:

```python
def _has_standards_tables(conn: sqlite3.Connection) -> bool:
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        ).fetchall()
    }
    return {"standards", "standards_sources", "standards_fts"}.issubset(names)


def _like_param(value: str) -> str:
    return f"%{value.strip()}%"


def _sanitize_fts_query(query: str | None) -> str:
    if not query:
        return ""
    query = query.strip()
    if not query:
        return ""
    if re.search(r"\b(AND|OR|NOT|NEAR)\b", query) or "*" in query:
        return query
    words = [w for w in re.split(r"\s+", query) if w]
    return " AND ".join(f'"{word}"*' for word in words)


def search_standards(
    conn: sqlite3.Connection,
    query: str | None = None,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    group: str | None = None,
    support_status: str | None = None,
    top_k: int = 20,
) -> list[StandardsHit]:
    if not _has_standards_tables(conn):
        return []

    top_k = max(1, min(top_k, 100))
    joins = "JOIN standards_sources src ON src.id = s.source_id"
    where: list[str] = []
    params: list[object] = []
    select_score = "0.0 AS score"
    order = "s.release DESC, s.platform, s.group_title, s.standard_ref"

    fts_query = _sanitize_fts_query(query)
    if fts_query:
        joins = (
            "JOIN standards_fts f ON f.rowid = s.id "
            "JOIN standards_sources src ON src.id = s.source_id"
        )
        where.append("standards_fts MATCH ?")
        params.append(fts_query)
        select_score = "bm25(standards_fts, 1.0, 1.5, 2.0, 3.0, 8.0, 5.0, 3.0) AS score"
        order = "score"

    if product_line:
        where.append("s.product_line = ?")
        params.append(product_line)
    if platform:
        where.append("s.platform LIKE ?")
        params.append(_like_param(platform))
    if release:
        where.append("s.release = ?")
        params.append(release)
    if group:
        where.append("s.group_title LIKE ?")
        params.append(_like_param(group))
    if support_status:
        where.append("s.support_status = ?")
        params.append(support_status)

    sql_where = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(top_k)
    rows = conn.execute(
        f"""SELECT s.id, s.product_line, s.platform, s.release, s.group_title,
                  s.standard_ref, s.standard_title, s.standard_text, s.support_status,
                  src.source_name, s.sheet_name, s.row_number, {select_score}
           FROM standards s
           {joins}
           {sql_where}
           ORDER BY {order}
           LIMIT ?""",
        params,
    ).fetchall()

    return [
        StandardsHit(
            id=row[0],
            product_line=row[1],
            platform=row[2],
            release=row[3],
            group_title=row[4],
            standard_ref=row[5],
            standard_title=row[6],
            standard_text=row[7],
            support_status=row[8],
            source_name=row[9],
            sheet_name=row[10],
            row_number=row[11],
            score=-(row[12] or 0.0),
        )
        for row in rows
    ]


def list_standards_products(conn: sqlite3.Connection) -> list[StandardsProductInfo]:
    if not _has_standards_tables(conn):
        return []

    rows = conn.execute(
        """SELECT product_line, COUNT(*)
           FROM standards
           GROUP BY product_line
           ORDER BY product_line"""
    ).fetchall()
    result: list[StandardsProductInfo] = []
    for product_line, count in rows:
        platforms = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT platform FROM standards WHERE product_line=? ORDER BY platform",
                (product_line,),
            ).fetchall()
        ]
        releases = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT release FROM standards WHERE product_line=? ORDER BY release",
                (product_line,),
            ).fetchall()
        ]
        source_names = [
            row[0]
            for row in conn.execute(
                """SELECT DISTINCT src.source_name
                   FROM standards s
                   JOIN standards_sources src ON src.id = s.source_id
                   WHERE s.product_line=?
                   ORDER BY src.source_name""",
                (product_line,),
            ).fetchall()
        ]
        result.append(
            StandardsProductInfo(
                product_line=product_line,
                platforms=platforms,
                releases=releases,
                num_records=count,
                source_names=source_names,
            )
        )
    return result
```

- [ ] **Step 4: Run search tests to verify pass**

Run:

```powershell
pytest tests/test_standards.py::test_search_standards_filters_by_status_platform_release_and_group tests/test_standards.py::test_list_standards_products_returns_summary -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/nokia_docs/standards.py tests/test_standards.py
git commit -m "Add structured standards search"
```

---

### Task 5: Expose CLI Commands And Build Integration

**Files:**
- Modify: `src/nokia_docs/cli.py`
- Modify: `src/nokia_docs/build.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_cli_exposes_standards_commands():
    result = CliRunner().invoke(main, ["index-standards", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia standards compliance spreadsheets" in result.output
    assert "--standards-file" in result.output
    assert "--product" in result.output

    result = CliRunner().invoke(main, ["reindex-standards", "--help"])
    assert result.exit_code == 0
    assert "Remove existing standards rows" in result.output


def test_build_db_accepts_optional_standards_files():
    result = CliRunner().invoke(main, ["build-db", "--help"])
    assert result.exit_code == 0
    assert "--standards-file" in result.output
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_cli.py::test_cli_exposes_standards_commands tests/test_cli.py::test_build_db_accepts_optional_standards_files -v
```

Expected: FAIL because commands/options do not exist yet.

- [ ] **Step 3: Add CLI commands**

In `src/nokia_docs/cli.py`, add import:

```python
from nokia_docs.standards import index_standards, reindex_standards
```

Add commands:

```python
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
```

- [ ] **Step 4: Extend build command**

In `src/nokia_docs/build.py`, import:

```python
from nokia_docs.standards import index_standards
```

Add click option to `build_db_cmd`:

```python
@click.option("--standards-file", "standards_files", multiple=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Optional standards compliance XLSX file. Can be supplied more than once.")
```

Add parameter `standards_files: tuple[str, ...]`.

After `index_pdfs(...)`, add:

```python
    if standards_files:
        index_standards(db_path, [Path(p) for p in standards_files])
```

- [ ] **Step 5: Run CLI tests to verify pass**

Run:

```powershell
pytest tests/test_cli.py::test_cli_exposes_standards_commands tests/test_cli.py::test_build_db_accepts_optional_standards_files -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/nokia_docs/cli.py src/nokia_docs/build.py tests/test_cli.py
git commit -m "Expose standards indexing commands"
```

---

### Task 6: Expose MCP Tools

**Files:**
- Modify: `src/nokia_docs/server.py`
- Test: `tests/test_server_errors.py`
- Test: `tests/test_standards.py`

- [ ] **Step 1: Add failing server tests**

Append to `tests/test_server_errors.py`:

```python
def test_search_standards_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.search_standards)("RFC 5880")


def test_list_standards_products_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.list_standards_products)()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pytest tests/test_server_errors.py::test_search_standards_raises_startup_errors tests/test_server_errors.py::test_list_standards_products_raises_startup_errors -v
```

Expected: FAIL because MCP tools do not exist.

- [ ] **Step 3: Implement MCP tools**

In `src/nokia_docs/server.py`, import:

```python
from nokia_docs.standards import (
    StandardsHit,
    StandardsProductInfo,
)
from nokia_docs.standards import (
    list_standards_products as _list_standards_products,
)
from nokia_docs.standards import (
    search_standards as _search_standards,
)
```

Update `instructions` to:

```python
        "Nokia documentation and standards search. Use search_docs to find "
        "documentation sections, get_document to read full content, "
        "list_products to see documentation products, search_standards for "
        "standards compliance questions, and list_standards_products to see "
        "indexed standards data."
```

Add tools:

```python
@mcp.tool()
def search_standards(
    query: str | None = None,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    group: str | None = None,
    support_status: str | None = None,
    top_k: int = 20,
) -> list[dict]:
    """Search Nokia standards compliance spreadsheet data.

    Use this for questions like whether SR OS, SR Linux, 7250 IXR, or 7705 SAR
    Gen2 supports a specific RFC, draft, or standards group in a release.
    """
    conn = _get_conn()
    hits: list[StandardsHit] = _search_standards(
        conn=conn,
        query=query,
        product_line=product_line,
        platform=platform,
        release=release,
        group=group,
        support_status=support_status,
        top_k=top_k,
    )
    return [
        {
            "id": h.id,
            "product_line": h.product_line,
            "platform": h.platform,
            "release": h.release,
            "group_title": h.group_title,
            "standard_ref": h.standard_ref,
            "standard_title": h.standard_title,
            "standard_text": h.standard_text,
            "support_status": h.support_status,
            "source_name": h.source_name,
            "sheet_name": h.sheet_name,
            "row_number": h.row_number,
            "score": round(h.score, 4),
        }
        for h in hits
    ]


@mcp.tool()
def list_standards_products() -> list[dict]:
    """List indexed standards-compliance products, platforms, releases, and sources."""
    conn = _get_conn()
    products: list[StandardsProductInfo] = _list_standards_products(conn)
    return [
        {
            "product_line": p.product_line,
            "platforms": p.platforms,
            "releases": p.releases,
            "num_records": p.num_records,
            "source_names": p.source_names,
        }
        for p in products
    ]
```

- [ ] **Step 4: Run server tests to verify pass**

Run:

```powershell
pytest tests/test_server_errors.py::test_search_standards_raises_startup_errors tests/test_server_errors.py::test_list_standards_products_raises_startup_errors -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/nokia_docs/server.py tests/test_server_errors.py
git commit -m "Expose standards MCP tools"
```

---

### Task 7: Product Metadata And Documentation

**Files:**
- Modify: `src/nokia_docs/products.py`
- Modify: `README.md`

- [ ] **Step 1: Update product display metadata**

Add to `PRODUCT_DISPLAY_NAMES` in `src/nokia_docs/products.py`:

```python
    "sros-standards": "Nokia SR OS Standards Compliance",
    "srlinux-standards": "Nokia SR Linux Standards Compliance",
```

Add standards-specific aliases only if needed by `search_standards`; do not repoint existing `sros` or `srlinux`.

- [ ] **Step 2: Update README indexed content table**

In `README.md`, add rows:

```markdown
| `sros-standards` | Nokia SR OS standards compliance spreadsheets |
| `srlinux-standards` | Nokia SR Linux standards compliance spreadsheets |
```

- [ ] **Step 3: Add README commands**

Add section:

```markdown
### Manual Step 4: Index Standards Compliance Spreadsheets

```bash
nokia-docs index-standards \
  --db nokia_docs.db \
  --standards-file /path/to/7x50-standards-compliance.xlsx \
  --standards-file /path/to/SR_Linux-standards-compliance.xlsx
```

To replace existing standards rows:

```bash
nokia-docs reindex-standards \
  --db nokia_docs.db \
  --standards-file /path/to/7x50-standards-compliance.xlsx \
  --standards-file /path/to/SR_Linux-standards-compliance.xlsx
```
```

- [ ] **Step 4: Run lint-relevant tests**

Run:

```powershell
pytest tests/test_cli.py tests/test_standards.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/nokia_docs/products.py README.md
git commit -m "Document standards compliance indexing"
```

---

### Task 8: Index Local Runtime DB And Verify

**Files:**
- Runtime artifact: `C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db`
- Runtime artifact: `C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db.sha256`

- [ ] **Step 1: Run targeted standards tests**

Run:

```powershell
pytest tests/test_standards.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
pytest -q
```

Expected: PASS.

- [ ] **Step 3: Reindex standards into local DB**

Run:

```powershell
nokia-docs reindex-standards `
  --db 'C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db' `
  --standards-file 'C:\!Docs\OneDrive - Nokia\Docs\7750\7x50-standards-compliance-20260226-field.xlsx' `
  --standards-file 'C:\!Docs\OneDrive - Nokia\Docs\7220\SR_Linux-standards-compliance-20260310-field.xlsx'
```

Expected: prints deleted standards row count and indexed row counts for both workbooks.

- [ ] **Step 4: Validate DB**

Run:

```powershell
nokia-docs validate-db --db 'C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db'
```

Expected: `Database validation OK`.

- [ ] **Step 5: Smoke-test structured search**

Run:

```powershell
python - <<'PY'
import sqlite3
from nokia_docs.standards import search_standards, list_standards_products
conn = sqlite3.connect(r"C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db")
try:
    print(list_standards_products(conn))
    print(search_standards(conn, query="RFC 5880", product_line="sros-standards", release="26.3.R1", top_k=3))
    print(search_standards(conn, query="RFC 5880", platform="7705 SAR", support_status="not_supported", top_k=3))
finally:
    conn.close()
PY
```

Expected: product summaries include `sros-standards` and `srlinux-standards`; RFC searches return structured records.

- [ ] **Step 6: Smoke-test shared docs search**

Run:

```powershell
python - <<'PY'
import sqlite3
from nokia_docs.search import search_docs
conn = sqlite3.connect(r"C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db")
try:
    for hit in search_docs("RFC 5880", conn, product_line="sros-standards", top_k=3):
        print(hit.product_line, hit.section_title, hit.section_path)
finally:
    conn.close()
PY
```

Expected: returns standards-compliance hits for supported SR OS rows.

- [ ] **Step 7: Commit final verification docs if needed**

If README or scripts changed during verification:

```powershell
git add README.md src/nokia_docs tests
git commit -m "Verify standards compliance indexing"
```

If only the runtime DB changed, do not commit the DB artifact.

---

## Self-Review

- Spec coverage: schema, parser, indexing, structured search, MCP tools, CLI, build integration, product metadata, tests, documentation, local DB rollout are all covered.
- Placeholder scan: no deferred-work markers are present.
- Type consistency: `StandardsRecord`, `StandardsHit`, and `StandardsProductInfo` are defined before use; CLI and MCP function names match the implementation tasks.
