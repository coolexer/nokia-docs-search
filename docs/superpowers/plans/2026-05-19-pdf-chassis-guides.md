# PDF Chassis Installation Guides — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Index Nokia chassis installation guide PDFs into `nokia_docs.db` as a new `install-guides` product line, searchable via the existing MCP server.

**Architecture:** Font-size-based heading detection (bold ≥ 13.5 pt → heading, ≤ 10.5 pt → noise/header-footer, else body) extracts ~90 sections per PDF. A deduplication step keeps only the highest-issue revision of each document number, reducing 160 PDFs to 110. Each PDF becomes ~90 FTS5 chunks under `product_line='install-guides'`, `book=chassis-slug`.

**Tech Stack:** Python 3.11+, PyMuPDF (`fitz`), SQLite FTS5, existing `index_rn.py` DB helpers.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `pymupdf>=1.24` dependency |
| `src/nokia_docs/parse_pdf.py` | **Create** | De-dup logic, PDF → list[dict] section extractor |
| `index_pdf.py` | **Create** | CLI script: walk PDFs, parse, insert into DB |
| `reindex_pdf.py` | **Create** | Drop `install-guides` rows + re-run index_pdf |
| `src/nokia_docs/search.py` | Modify | Add `install-guides` display name + aliases |
| `README.md` | Modify | Add install guide search examples |
| `tests/test_parse_pdf.py` | **Create** | Unit tests for filename parsing + block classification |

**PDF source directory:** `C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide\`

---

## Task 1: Add PyMuPDF dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Edit `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "fastmcp>=2.0",
    "selectolax>=0.3",
    "click>=8.1",
    "pymupdf>=1.24",
]
```

- [ ] **Step 2: Install**

```
pip install -e .
```

Expected: installs without errors, `python -c "import fitz; print(fitz.__version__)"` prints a version.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add pymupdf dependency for PDF chassis guide indexing"
```

---

## Task 2: Filename utilities — de-dup and chassis extraction

**Files:**
- Create: `src/nokia_docs/parse_pdf.py` (filename utilities only, no PDF reading yet)
- Create: `tests/test_parse_pdf.py`

Nokia document filenames follow the pattern:
`3HE{num}{variant}{issue}_V1_{title}.pdf`

The trailing digits on the doc number are the issue/revision (e.g., `3HE19506AAABTQZZA01` = issue 01).
Files without trailing digits (e.g., `3HE10360AAAATQZZA`) are issue 0.
De-dup: group by base (strip trailing digits), keep the file with the highest issue number.

**IMPORTANT:** Do NOT sort filenames lexicographically — `_` (ASCII 95) > `0` (ASCII 48), which causes `TQZZA_V1_...` to sort after `TQZZA02_V1_...`. Sort by parsed integer issue number.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parse_pdf.py`:

```python
"""Unit tests for parse_pdf filename utilities."""
from pathlib import Path
import pytest

# adjust sys.path so the src package is importable from tests/
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nokia_docs.parse_pdf import (
    _doc_base,
    _issue_num,
    _chassis_from_filename,
    _slug,
    deduplicate_pdfs,
)


# ---------- _doc_base ----------

def test_doc_base_strips_trailing_digits():
    assert _doc_base("3HE19506AAABTQZZA01") == "3HE19506AAABTQZZA"

def test_doc_base_no_issue():
    assert _doc_base("3HE10360AAAATQZZA") == "3HE10360AAAATQZZA"

def test_doc_base_two_digit_issue():
    assert _doc_base("3HE16319AAACTQZZA05") == "3HE16319AAACTQZZA"

def test_doc_base_four_digit_issue():
    # edge case: some variants have longer suffixes
    assert _doc_base("3HE17922AAAATQZZA06") == "3HE17922AAAATQZZA"


# ---------- _issue_num ----------

def test_issue_num_with_digits():
    assert _issue_num(Path("3HE19506AAABTQZZA01_V1_foo.pdf")) == 1

def test_issue_num_no_digits():
    assert _issue_num(Path("3HE10360AAAATQZZA_V1_foo.pdf")) == 0

def test_issue_num_07():
    assert _issue_num(Path("3HE16108AAAATQZZA07_V1_foo.pdf")) == 7


# ---------- _chassis_from_filename ----------

def test_chassis_basic():
    chassis, release = _chassis_from_filename(
        Path("3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf")
    )
    assert chassis == "7705 SAR-Ax"
    assert release == "23.10.R1"

def test_chassis_sr_os_release():
    chassis, release = _chassis_from_filename(
        Path("3HE16319AAACTQZZA05_V1_7750 SR-1s Chassis Installation Guide 20.7.pdf")
    )
    assert chassis == "7750 SR-1s"
    assert release == "20.7"

def test_chassis_srlinux_no_release():
    chassis, release = _chassis_from_filename(
        Path("3HE16108AAAATQZZA07_V1_SR Linux 7220 IXR-D Chassis Installation Guide.pdf")
    )
    assert chassis == "SR Linux 7220 IXR-D"
    assert release == ""

def test_chassis_no_v1_marker():
    chassis, release = _chassis_from_filename(Path("unknown_doc.pdf"))
    assert chassis == "unknown_doc"
    assert release == ""


# ---------- deduplicate_pdfs ----------

def test_deduplicate_keeps_highest_issue(tmp_path):
    """Keeps the file with the highest numeric issue."""
    for name in [
        "3HE16108AAAATQZZA05_V1_foo.pdf",
        "3HE16108AAAATQZZA06_V1_foo.pdf",
        "3HE16108AAAATQZZA07_V1_foo.pdf",
    ]:
        (tmp_path / name).touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
    assert result[0].name == "3HE16108AAAATQZZA07_V1_foo.pdf"

def test_deduplicate_no_issue_vs_with_issue(tmp_path):
    """File with no issue suffix (issue=0) loses to file with issue 02."""
    (tmp_path / "3HE18438AAAATQZZA_V1_foo.pdf").touch()
    (tmp_path / "3HE18438AAAATQZZA02_V1_foo.pdf").touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
    assert result[0].name == "3HE18438AAAATQZZA02_V1_foo.pdf"

def test_deduplicate_distinct_doc_numbers_both_kept(tmp_path):
    """Different doc base numbers → both kept."""
    (tmp_path / "3HE19133AAAATQZZA04_V1_SAR-Hm 22.10.pdf").touch()
    (tmp_path / "3HE21656AAAATQZZA01_V1_SAR-Hm 25.10.pdf").touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 2

def test_deduplicate_single_file(tmp_path):
    """Single file is always kept."""
    (tmp_path / "3HE10360AAAATQZZA_V1_7210 SAS-Mxp.pdf").touch()
    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_parse_pdf.py -v 2>&1 | head -30
```

Expected: ImportError or ModuleNotFoundError (file doesn't exist yet).

- [ ] **Step 3: Implement filename utilities in parse_pdf.py**

Create `src/nokia_docs/parse_pdf.py`:

```python
"""Parse Nokia chassis installation guide PDFs into FTS5-indexable chunks.

Public API:
    deduplicate_pdfs(pdf_dir)   → list[Path]   — latest issue per doc number
    parse_pdf(pdf_path)         → list[dict]   — section chunks for DB insertion
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


# --------------------------------------------------------------------------- #
# Filename utilities                                                            #
# --------------------------------------------------------------------------- #

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _doc_base(doc_num: str) -> str:
    """Strip trailing issue digits from a Nokia document number.

    '3HE19506AAABTQZZA01' → '3HE19506AAABTQZZA'
    '3HE10360AAAATQZZA'   → '3HE10360AAAATQZZA'  (no issue suffix)
    """
    return re.sub(r"\d+$", "", doc_num)


def _issue_num(pdf_path: Path) -> int:
    """Parse the numeric issue suffix from a Nokia doc filename.

    '3HE19506AAABTQZZA01_V1_...' → 1
    '3HE10360AAAATQZZA_V1_...'   → 0  (no suffix)
    """
    doc_num = pdf_path.name.split("_V1_")[0] if "_V1_" in pdf_path.name else pdf_path.stem
    m = re.search(r"(\d+)$", doc_num)
    return int(m.group(1)) if m else 0


def _chassis_from_filename(pdf_path: Path) -> tuple[str, str]:
    """Extract chassis model name and software release from a Nokia filename.

    Returns (chassis_name, release_string).

    Examples:
        '3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf'
            → ('7705 SAR-Ax', '23.10.R1')
        '3HE16108AAAATQZZA07_V1_SR Linux 7220 IXR-D Chassis Installation Guide.pdf'
            → ('SR Linux 7220 IXR-D', '')
    """
    name = pdf_path.stem  # strip .pdf
    if "_V1_" not in name:
        return name, ""

    title = name.split("_V1_", 1)[1].strip()

    # Extract chassis name: everything before "Chassis Installation"
    m = re.match(r"^(.*?)\s+Chassis\s+Installation", title, re.IGNORECASE)
    chassis = m.group(1).strip() if m else title

    # Extract release at end: e.g. "23.10.R1", "22.7", "Release 26" → "26"
    rel_m = re.search(
        r"(?:Release\s+)?(\d{2}[\d.]*(?:\.R\d+)?)\s*$", title, re.IGNORECASE
    )
    release = rel_m.group(1) if rel_m else ""

    return chassis, release


def deduplicate_pdfs(pdf_dir: Path) -> list[Path]:
    """Return one PDF per document base number — the one with the highest issue.

    Nokia versioning: '3HE16108AAAATQZZA05', '3HE16108AAAATQZZA06', '3HE16108AAAATQZZA07'
    → keep '3HE16108AAAATQZZA07'.

    IMPORTANT: sort by parsed integer, NOT lexicographically.
    '_' (ASCII 95) > '0' (ASCII 48), so 'TQZZA_V1_' would wrongly beat 'TQZZA02_V1_'
    in a string sort.
    """
    groups: dict[str, list[Path]] = defaultdict(list)
    for pdf in pdf_dir.glob("*.pdf"):
        doc_num = pdf.name.split("_V1_")[0] if "_V1_" in pdf.name else pdf.stem
        base = _doc_base(doc_num)
        groups[base].append(pdf)

    result = []
    for pdfs in groups.values():
        best = max(pdfs, key=_issue_num)
        result.append(best)

    return sorted(result, key=lambda p: p.name)
```

- [ ] **Step 4: Run tests — expect them to pass**

```
pytest tests/test_parse_pdf.py -v
```

Expected: all 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/nokia_docs/parse_pdf.py tests/test_parse_pdf.py
git commit -m "feat: add PDF filename de-dup and chassis name extraction"
```

---

## Task 3: PDF section extractor

**Files:**
- Modify: `src/nokia_docs/parse_pdf.py` — add `parse_pdf()` and helpers
- Modify: `tests/test_parse_pdf.py` — add integration test

**Font hierarchy in Nokia chassis installation guides (from analysis):**

| Size | Bold | Meaning |
|---|---|---|
| ≥ 18.0 | yes | Chapter title (H1) |
| 14.0–17.9 | yes | Section / subsection (H2–H4) |
| ~11.0 | no | Body text |
| ≤ 10.5 | any | Running header / footer → **skip** |

Section number and section title appear as **separate consecutive bold-large blocks**
(e.g. block 1 = `"2.9.1.3"`, block 2 = `"Protective Earth"`). They must be merged.

- [ ] **Step 1: Add integration test to test_parse_pdf.py**

Append to `tests/test_parse_pdf.py`:

```python
# ---------- parse_pdf integration ----------

import os

PDF_DIR = Path(r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide")
SAMPLE_PDF = PDF_DIR / "3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf"


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_returns_chunks():
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    assert len(chunks) > 20, "Expected many sections in a 144-page guide"


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_chunk_structure():
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    required_keys = {
        "product_line", "book", "rel_path", "page_title",
        "section_id", "section_title", "section_path", "depth", "char_len", "body",
    }
    for chunk in chunks:
        assert required_keys == set(chunk.keys()), f"Missing keys: {required_keys - set(chunk.keys())}"
        assert chunk["product_line"] == "install-guides"
        assert chunk["book"]  # non-empty
        assert chunk["section_title"]  # non-empty
        assert chunk["body"]  # non-empty


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_no_html_noise():
    """Running headers / footers should not appear in body."""
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    for chunk in chunks:
        # Copyright footer
        assert "Nokia Confidential" not in chunk["body"]
        # Page-header doc title (repeated on every page)
        assert "SAR-Ax Chassis Installation Guide\n" not in chunk["body"]


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_no_oversized_chunks():
    """No chunk body should exceed 4000 chars."""
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    for chunk in chunks:
        assert chunk["char_len"] <= 4000, (
            f"Oversized chunk '{chunk['section_title']}': {chunk['char_len']} chars"
        )
```

- [ ] **Step 2: Run integration test — expect it to fail (ImportError)**

```
pytest tests/test_parse_pdf.py::test_parse_pdf_returns_chunks -v
```

Expected: ImportError — `parse_pdf` not yet defined.

- [ ] **Step 3: Implement parse_pdf() — append to parse_pdf.py**

Add after the `deduplicate_pdfs` function in `src/nokia_docs/parse_pdf.py`:

```python
# --------------------------------------------------------------------------- #
# PDF section extractor                                                        #
# --------------------------------------------------------------------------- #

import fitz  # PyMuPDF — imported here so filename utilities work without it


_HEADING_SIZE_MIN = 13.5   # bold text above this size = heading
_NOISE_SIZE_MAX   = 10.5   # text at or below this size = running header / footer
_BODY_MAX_CHARS   = 3000   # split longer sections at paragraph boundary


def _block_text(block: dict) -> str:
    """Concatenate all span text in a block, collapsing whitespace."""
    parts = [
        s["text"].strip()
        for line in block["lines"]
        for s in line["spans"]
        if s["text"].strip()
    ]
    return " ".join(parts)


def _is_noise_block(block: dict) -> bool:
    """True if the block is a running page header or footer (all text ≤ noise threshold)."""
    spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
    if not spans:
        return True
    return all(s["size"] <= _NOISE_SIZE_MAX for s in spans)


def _is_heading_block(block: dict) -> bool:
    """True if ALL non-empty spans are bold and above the heading size threshold."""
    spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
    if not spans:
        return False
    return all((s["flags"] & 16) and s["size"] >= _HEADING_SIZE_MIN for s in spans)


def _split_body(text: str, max_chars: int = _BODY_MAX_CHARS) -> list[str]:
    """Split body text at paragraph boundaries if it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]
    paras = text.split("\n")
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paras:
        if current_len + len(para) > max_chars and current:
            parts.append("\n".join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)
    if current:
        parts.append("\n".join(current))
    return parts or [text]


def parse_pdf(pdf_path: Path) -> list[dict]:
    """Extract section chunks from a Nokia chassis installation guide PDF.

    Returns a list of dicts matching the nokia_docs.db schema (docs + docs_body).
    Each dict has keys: product_line, book, rel_path, page_title, section_id,
    section_title, section_path, depth, char_len, body.
    """
    doc = fitz.open(str(pdf_path))
    chassis, release = _chassis_from_filename(pdf_path)
    chassis_slug = _slug(chassis)
    page_title = chassis + (" Chassis Installation Guide" if "Chassis" not in chassis else "")
    if release:
        page_title += f" {release}"
    rel_path = f"install/{chassis_slug}.pdf"

    # ---- Pass 1: collect (kind, text) items from all content pages ----------
    # Skip the first 5 pages: cover, legal notice, table of contents.
    items: list[tuple[str, str]] = []   # ('heading' | 'body', text)

    for page_num, page in enumerate(doc):
        if page_num < 5:
            continue
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:         # not a text block (image, etc.)
                continue
            if _is_noise_block(block):
                continue
            text = _block_text(block)
            if not text:
                continue
            if _is_heading_block(block):
                items.append(("heading", text))
            else:
                items.append(("body", text))

    # ---- Pass 2: merge consecutive heading blocks (section number + title) --
    # Nokia PDFs emit the section number and section title as separate blocks:
    #   heading "2.9.1.3"  +  heading "Protective Earth"  →  "2.9.1.3 Protective Earth"
    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(items):
        kind, text = items[i]
        if (
            kind == "heading"
            and i + 1 < len(items)
            and items[i + 1][0] == "heading"
        ):
            merged.append(("heading", f"{text} {items[i + 1][1]}"))
            i += 2
        else:
            merged.append((kind, text))
            i += 1

    # ---- Pass 3: group into (heading, body_text) sections -------------------
    sections: list[dict] = []
    current_heading = ""
    current_body: list[str] = []

    for kind, text in merged:
        if kind == "heading":
            if current_heading and current_body:
                sections.append({
                    "heading": current_heading,
                    "body": "\n".join(current_body),
                })
            current_heading = text
            current_body = []
        else:
            current_body.append(text)

    if current_heading and current_body:
        sections.append({"heading": current_heading, "body": "\n".join(current_body)})

    # ---- Pass 4: convert to DB records, splitting oversized sections --------
    records: list[dict] = []
    for sec_idx, sec in enumerate(sections):
        body_chunks = _split_body(sec["body"])
        for chunk_idx, chunk_text in enumerate(body_chunks):
            full_body = f"{sec['heading']}\n\n{chunk_text}"
            section_id = (
                f"sec-{sec_idx}-{chunk_idx}" if len(body_chunks) > 1
                else f"sec-{sec_idx}"
            )
            records.append({
                "product_line": "install-guides",
                "book":         chassis_slug,
                "rel_path":     rel_path,
                "page_title":   page_title,
                "section_id":   section_id,
                "section_title": sec["heading"],
                "section_path": f"{chassis} > {sec['heading']}",
                "depth":        0,
                "char_len":     len(full_body),
                "body":         full_body,
            })

    doc.close()
    return records
```

- [ ] **Step 4: Run integration tests**

```
pytest tests/test_parse_pdf.py -v -k "parse_pdf"
```

Expected: all 4 integration tests PASS.

- [ ] **Step 5: Spot-check output quality**

```python
python -c "
from pathlib import Path
from src.nokia_docs.parse_pdf import parse_pdf
chunks = parse_pdf(Path(r'C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide\3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf'))
print(f'Total chunks: {len(chunks)}')
for c in chunks[5:10]:
    print(f'  [{c[\"section_title\"]}] {len(c[\"body\"])} chars')
    print(f'  {c[\"body\"][:120]}')
    print()
"
```

Expected: 70-110 chunks, section titles look like "2.9.1.3 Protective Earth", body contains meaningful installation text.

- [ ] **Step 6: Commit**

```bash
git add src/nokia_docs/parse_pdf.py tests/test_parse_pdf.py
git commit -m "feat: implement PDF section extractor with font-size heading detection"
```

---

## Task 4: index_pdf.py — indexer script

**Files:**
- Create: `index_pdf.py` (project root, next to `index_rn.py`)

This script walks the deduplicated PDFs, calls `parse_pdf()`, and inserts chunks into the DB. It imports `_open_db` and `_insert_batch` from `index_rn.py` (same directory).

- [ ] **Step 1: Write the failing smoke test**

Add to `tests/test_parse_pdf.py`:

```python
# ---------- index_pdf smoke ----------

def test_index_pdf_script_is_importable():
    """index_pdf.py must be importable without side-effects."""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "index_pdf",
        Path(__file__).parent.parent / "index_pdf.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # Should not raise; main() must not auto-execute on import
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_parse_pdf.py::test_index_pdf_script_is_importable -v
```

Expected: ModuleNotFoundError — `index_pdf.py` does not exist yet.

- [ ] **Step 3: Create index_pdf.py**

Create `index_pdf.py` in the project root:

```python
"""Index Nokia chassis installation guide PDFs into nokia_docs.db.

PDFs must be pre-downloaded in the directory given by --pdf-dir (default: current dir).
Only the latest issue of each document number is indexed (de-duplicated automatically).

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

# Reuse DB helpers from index_rn.py (same directory, pure functions)
from index_rn import _open_db, _insert_batch

# ---- Argument parsing -------------------------------------------------------

_args = sys.argv[1:]

def _arg(flag: str, default: str) -> str:
    if flag in _args:
        return _args[_args.index(flag) + 1]
    return default

DB_PATH  = Path(_arg("--db", "nokia_docs.db"))
PDF_DIR  = Path(_arg("--pdf-dir", str(Path(__file__).parent /
                                     r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide"
                                     if False else ".")))

# ---- Main -------------------------------------------------------------------

def main() -> None:
    # Allow caller to override PDF_DIR at module level
    global PDF_DIR
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
```

- [ ] **Step 4: Run the importable test**

```
pytest tests/test_parse_pdf.py::test_index_pdf_script_is_importable -v
```

Expected: PASS.

- [ ] **Step 5: Dry-run against 3 PDFs**

```
python index_pdf.py --db nokia_docs.db --pdf-dir "C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide"
```

Watch the first 3 PDF lines. Expected output format:
```
[  1/110] 3HE10360AAAATQZZA_V1_7210 SAS-Mxp Chassis Installat... 67 sections, 67 inserted
[  2/110] 3HE10722AAAATQZZA_V1_7210 SAS-S 110GE Chassis Instal... 54 sections, 54 inserted
...
Done in Xs
Total install-guide chunks inserted: ~10,000
```

- [ ] **Step 6: Commit**

```bash
git add index_pdf.py tests/test_parse_pdf.py
git commit -m "feat: add index_pdf.py CLI script for chassis guide PDFs"
```

---

## Task 5: reindex_pdf.py — drop and re-index

**Files:**
- Create: `reindex_pdf.py` (project root)

Same pattern as `reindex_rn.py`. Useful when re-running after changes to the parser.

- [ ] **Step 1: Create reindex_pdf.py**

```python
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

print(f"DB: {DB}  ({DB.stat().st_size / 1024 / 1024:.1f} MB)")

conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")

# Delete all install-guides rows
ids = [r[0] for r in conn.execute(
    "SELECT id FROM docs WHERE product_line='install-guides'"
).fetchall()]

if ids:
    for doc_id in ids:
        conn.execute("DELETE FROM docs_fts WHERE rowid=?", (doc_id,))
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM docs_body WHERE id IN ({placeholders})", ids)
    conn.execute("DELETE FROM docs WHERE product_line='install-guides'")
    print(f"Deleted {len(ids)} install-guides rows")
else:
    print("No install-guides rows to delete")

conn.commit()
conn.close()
print(f"After delete: {DB.stat().st_size / 1024 / 1024:.1f} MB")
print()

# Re-index
import index_pdf
index_pdf.DB_PATH = DB
index_pdf.PDF_DIR = PDF_DIR
index_pdf.main()
```

- [ ] **Step 2: Verify it runs without error (even with 0 rows to delete)**

```
python reindex_pdf.py nokia_docs.db "C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide"
```

Expected: completes without exception. If install-guides was already indexed in Task 4, it drops and re-inserts. DB size should grow by ~15-25 MB.

- [ ] **Step 3: Commit**

```bash
git add reindex_pdf.py
git commit -m "feat: add reindex_pdf.py helper for re-indexing install guides"
```

---

## Task 6: search.py — aliases and display names

**Files:**
- Modify: `src/nokia_docs/search.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_parse_pdf.py`:

```python
def test_install_guides_alias_resolves():
    from nokia_docs.search import _resolve_product
    assert _resolve_product("install") == "install-guides"
    assert _resolve_product("chassis") == "install-guides"
    assert _resolve_product("install guide") == "install-guides"
    assert _resolve_product("installation") == "install-guides"
    assert _resolve_product("install-guides") == "install-guides"
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_parse_pdf.py::test_install_guides_alias_resolves -v
```

Expected: AssertionError — aliases not yet defined.

- [ ] **Step 3: Add aliases to search.py**

In `src/nokia_docs/search.py`, in the `_ALIASES` dict, add after the Release Notes block:

```python
    # Installation Guides
    "install":          "install-guides",
    "install guide":    "install-guides",
    "install guides":   "install-guides",
    "installation":     "install-guides",
    "chassis":          "install-guides",
    "chassis guide":    "install-guides",
    "install-guides":   "install-guides",
```

In `_DISPLAY_NAMES`, add:

```python
    "install-guides":   "Nokia Chassis Installation Guides",
```

- [ ] **Step 4: Run test to confirm pass**

```
pytest tests/test_parse_pdf.py::test_install_guides_alias_resolves -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/nokia_docs/search.py tests/test_parse_pdf.py
git commit -m "feat: add install-guides product line aliases and display name"
```

---

## Task 7: README — install guide search examples

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add install-guides to the Contents table and What's indexed**

In `README.md`, add a row to the "What's indexed" table:

```markdown
| `install-guides` | Nokia chassis installation guides (all platforms) | ~10 000 |
```

- [ ] **Step 2: Add search examples section**

Add after the "Search examples — release notes" section:

```markdown
## Search examples — installation guides

Installation guides contain site preparation, physical installation procedures,
power and grounding requirements, cabling, and initial power-on steps.

### Find installation procedure for a specific chassis

\```
# Power requirements for 7750 SR-1s
search_docs("power requirements AC DC", product_line="install", book="7750-sr-1s")

# Grounding the 7705 SAR-Ax
search_docs("chassis ground protective earth", product_line="install", book="7705-sar-ax")

# Rack mounting the 7250 IXR-X
search_docs("rack mounting rails", product_line="install", book="7250-ixr-x")
\```

### Find across all chassis

\```
# Which chassis have -48V DC input?
search_docs("DC power -48V input", product_line="install-guides")

# Optical transceiver installation across all chassis
search_docs("SFP transceiver install remove", product_line="install-guides")

# Environmental operating temperature specs
search_docs("operating temperature humidity", product_line="install-guides")
\```

### Discover available books (chassis slugs)

\```python
# Via MCP
list_products()  # shows install-guides with all chassis as books

# Or: filter by chassis family
search_docs("fan tray replacement", product_line="install", book="7705-sar-18")
\```

### Available product_line alias: `install`, `chassis`, `installation`, `install-guides`
```

- [ ] **Step 3: Also update the Product line slugs table**

Add a row to the aliases table:

```markdown
| `install`, `chassis`, `installation`, `install-guides` | `install-guides` |
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add chassis installation guide search examples to README"
```

---

## Self-Review

### Spec coverage
- [x] De-duplicate 160 PDFs → 110 (Task 2)
- [x] Extract sections with font-based headings (Task 3)
- [x] Insert into existing nokia_docs.db (Task 4)
- [x] Re-index helper (Task 5)
- [x] MCP server search aliases (Task 6)
- [x] README (Task 7)

### Edge cases handled
- [x] `_` > `0` in ASCII — issue sorting is numeric, not lexicographic
- [x] Files with no issue suffix (issue = 0)
- [x] First 5 pages skipped (cover, legal, TOC)
- [x] Running headers/footers filtered (size ≤ 10.5)
- [x] Consecutive heading blocks merged (section number + section title)
- [x] Oversized sections split at paragraph boundary (≤ 3000 chars)
- [x] PDFs that fail to parse logged and skipped (try/except in index_pdf.py)
- [x] `doc.close()` called after parsing to free file handles

### Type consistency
- `parse_pdf()` returns `list[dict]` — matches `_insert_batch(conn, rows: list[dict])` in index_rn.py ✓
- `deduplicate_pdfs()` returns `list[Path]` — consumed by `index_pdf.py` loop ✓
- `_chassis_from_filename()` returns `tuple[str, str]` — used inside `parse_pdf()` ✓

### Placeholder scan
None found — all code blocks are complete.
