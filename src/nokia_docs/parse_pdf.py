"""Parse Nokia chassis installation guide PDFs into FTS5-indexable chunks.

Public API:
    deduplicate_pdfs(pdf_dir)   → list[Path]   — latest issue per doc number
    parse_pdf(pdf_path)         → list[dict]   — section chunks for DB insertion
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


def _slug(text: str) -> str:
    """Convert text to slug format (lowercase, alphanumeric + hyphens)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _doc_base(doc_num: str) -> str:
    """Strip trailing issue digits from document number.

    Args:
        doc_num: Document number like "3HE19506AAABTQZZA01"

    Returns:
        Document base without trailing issue digits: "3HE19506AAABTQZZA"
    """
    return re.sub(r"\d+$", "", doc_num)


def _issue_num(pdf_path: Path) -> int:
    """Extract issue number from PDF filename.

    Args:
        pdf_path: Path object with filename like "3HE19506AAABTQZZA01_V1_foo.pdf"

    Returns:
        Issue number as integer (0 if no trailing digits found).
    """
    stem = pdf_path.stem

    # Primary: digits immediately before the _V1_ (or _V2_ etc.) separator.
    match = re.search(r"(\d+)_V\d+_", stem)
    if match:
        return int(match.group(1))

    # Fallback for bare doc-number filenames (no description after doc number):
    # strip trailing digits from the stem itself.
    tail = re.search(r"(\d+)$", stem)
    if tail:
        return int(tail.group(1))

    return 0


def _chassis_from_filename(pdf_path: Path) -> tuple[str, str]:
    """Extract chassis model and release version from PDF filename.

    Args:
        pdf_path: Path object with filename like:
                 "3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf"

    Returns:
        Tuple of (chassis_model, release_version).
        If _V1_ marker not found, returns (filename_stem, "").
    """
    filename = pdf_path.name

    # Look for _V1_ marker
    match = re.search(r"_V1_(.+)$", filename)
    if not match:
        return (pdf_path.stem, "")

    content = match.group(1)

    # Extract chassis model (everything before "Chassis Installation")
    chassis_match = re.match(r"(.+?)\s+Chassis Installation(?:\s+Guide)?\s*(.*)", content)
    if chassis_match:
        chassis = chassis_match.group(1).strip()
        remainder = chassis_match.group(2).strip()

        # Extract release version from remainder
        # Match patterns like "23.10.R1", "20.7", "Release 26", etc.
        # Stop at whitespace or end of string to avoid capturing trailing dots from ".pdf"
        release_match = re.search(r"([\d]+\.[\d]+(?:\.R\d+)?|Release\s+[\d.]+)", remainder)
        if release_match:
            release = release_match.group(1)
        else:
            release = ""

        return (chassis, release)

    # Fallback if pattern doesn't match
    return (pdf_path.stem, "")


def deduplicate_pdfs(pdf_dir: Path) -> list[Path]:
    """Keep only the highest issue version of each document.

    Groups PDFs by document base number (_doc_base) and returns
    the one with the highest issue number (_issue_num) per group.

    Args:
        pdf_dir: Directory path containing PDF files

    Returns:
        List of Path objects for the deduplicated PDFs (highest issue per document).
    """
    pdf_dir = Path(pdf_dir)
    pdfs = list(pdf_dir.glob("*.pdf"))

    # Group by document base.  Split on _V<n>_ (not just _V1_) so that V2/V3
    # filenames are treated consistently with _issue_num() which also uses _V\d+_.
    _vn_re = re.compile(r"_V\d+_")
    groups: dict[str, list[Path]] = {}
    for pdf in pdfs:
        m = _vn_re.search(pdf.name)
        doc_num = pdf.name[:m.start()] if m else pdf.stem
        base = _doc_base(doc_num)
        if base not in groups:
            groups[base] = []
        groups[base].append(pdf)

    # Keep the one with highest issue number per group
    result = []
    for group in groups.values():
        result.append(max(group, key=_issue_num))

    return result


# --------------------------------------------------------------------------- #
# PDF section extractor                                                        #
# --------------------------------------------------------------------------- #

_BODY_MAX_CHARS   = 3000   # body-only cap; full_body (heading + body) may exceed this by heading length
_BOLD_FLAG        = 1 << 4  # PyMuPDF span flags bit for bold
_SKIP_FRONT_PAGES = 5       # cover + legal notice + table of contents (varies 4-7 per guide)

# Fallback thresholds used when auto-detection cannot determine body size.
# Tuned on Nokia 23.10.R1 SAR-Ax PDF (body ~11pt, noise ≤10.5pt).
_HEADING_SIZE_MIN_DEFAULT = 13.5
_NOISE_SIZE_MAX_DEFAULT   = 10.5


def _detect_thresholds(doc: "fitz.Document") -> tuple[float, float]:
    """Auto-detect heading_min and noise_max from the PDF's font-size distribution.

    Strategy:
      1. Sample the first 20 content pages (after front matter).
      2. The most common *non-bold* font size above 8 pt is body text.
      3. noise_max  = body_size - 0.5   (half a point below body; filters running
         headers/footers while preserving body text even at 10 pt).
      4. heading_min = body_size + 2.0  (bold text clearly larger than body).

    This makes the parser self-calibrating across Nokia guides with different
    typographic conventions (e.g. SAR-Ax body ~11 pt vs IXR-D2L body ~10 pt).
    """
    from collections import Counter
    size_counts: Counter[float] = Counter()
    start = _SKIP_FRONT_PAGES
    end   = min(start + 20, len(doc))
    for page_num in range(start, end):
        for block in doc[page_num].get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for s in line["spans"]:
                    if not s["text"].strip():
                        continue
                    if s["flags"] & _BOLD_FLAG:
                        continue   # bold spans are headings/noise, not body
                    sz = round(s["size"], 1)
                    if sz > 8.0:   # ignore tiny diagram labels / footnotes
                        size_counts[sz] += 1

    if not size_counts:
        return _HEADING_SIZE_MIN_DEFAULT, _NOISE_SIZE_MAX_DEFAULT

    body_size   = size_counts.most_common(1)[0][0]
    noise_max   = round(body_size - 0.5, 1)
    heading_min = round(body_size + 2.0, 1)
    return heading_min, noise_max


def _block_text(block: dict) -> str:
    """Concatenate all span text in a block, collapsing whitespace."""
    parts = [
        s["text"].strip()
        for line in block["lines"]
        for s in line["spans"]
        if s["text"].strip()
    ]
    return " ".join(parts)


def _is_noise_block(block: dict, noise_max: float) -> bool:
    """True if the block is a running page header or footer (all text <= noise threshold)."""
    spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
    if not spans:
        return True
    return all(s["size"] <= noise_max for s in spans)


def _is_heading_block(block: dict, heading_min: float) -> bool:
    """True if ALL non-empty spans are bold and above the heading size threshold."""
    spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
    if not spans:
        return False
    return all((s["flags"] & _BOLD_FLAG) and s["size"] >= heading_min for s in spans)


def _split_body(text: str, max_chars: int = _BODY_MAX_CHARS) -> list[str]:
    """Split body text at paragraph boundaries if it exceeds max_chars.

    A single paragraph that is itself larger than max_chars is hard-sliced
    at max_chars to guarantee no chunk body exceeds the cap.
    """
    if len(text) <= max_chars:
        return [text]
    paras = text.split("\n")
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paras:
        # Flush current accumulator if adding this paragraph would exceed cap.
        if current_len + len(para) > max_chars and current:
            parts.append("\n".join(current))
            current = []
            current_len = 0
        # Hard-slice oversized single paragraphs that exceed the cap on their own.
        if len(para) > max_chars:
            for start in range(0, len(para), max_chars):
                parts.append(para[start:start + max_chars])
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
    import fitz  # deferred so filename utilities work without PyMuPDF installed

    chassis, release = _chassis_from_filename(pdf_path)
    chassis_slug = _slug(chassis)
    page_title = chassis
    if "Chassis" not in chassis:
        page_title += " Chassis Installation Guide"
    if release:
        page_title += f" {release}"

    # Include the doc-number prefix in rel_path to avoid collisions between
    # different Nokia document numbers that cover the same chassis model
    # (e.g. multiple release versions, or SR Linux vs SONiC variants).
    m = re.search(r"_V\d+_", pdf_path.name)
    doc_key = pdf_path.name[:m.start()].lower() if m else pdf_path.stem.lower()
    rel_path = f"install/{chassis_slug}/{doc_key}.pdf"

    doc = fitz.open(str(pdf_path))
    try:
        # Auto-detect font-size thresholds for this specific PDF.
        # Nokia guides vary: SAR-Ax body ~11 pt, IXR-D2L body ~10 pt.
        heading_min, noise_max = _detect_thresholds(doc)

        # ---- Pass 1: collect (kind, text) items from all content pages ----------
        # Skip front matter (cover, legal notice, TOC). _SKIP_FRONT_PAGES is tuned
        # for Nokia install guides and may need adjustment for unusually short guides.
        items: list[tuple[str, str]] = []   # ('heading' | 'body', text)

        for page_num, page in enumerate(doc):
            if page_num < _SKIP_FRONT_PAGES:
                continue
            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 0:         # not a text block (image, etc.)
                    continue
                if _is_noise_block(block, noise_max):
                    continue
                text = _block_text(block)
                if not text:
                    continue
                if _is_heading_block(block, heading_min):
                    items.append(("heading", text))
                else:
                    items.append(("body", text))

        # ---- Pass 2: merge consecutive heading blocks (section number + title) --
        # Nokia PDFs emit the section number and section title as separate blocks:
        #   heading "2.9.1.3"  +  heading "Protective Earth"  ->  "2.9.1.3 Protective Earth"
        # THREE or more consecutive heading blocks (chapter + section + title) are
        # all merged into a single heading string.
        merged: list[tuple[str, str]] = []
        i = 0
        while i < len(items):
            kind, text = items[i]
            if kind == "heading":
                heading_parts = [text]
                while i + 1 < len(items) and items[i + 1][0] == "heading":
                    i += 1
                    heading_parts.append(items[i][1])
                merged.append(("heading", " ".join(heading_parts)))
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

        return records

    finally:
        doc.close()
