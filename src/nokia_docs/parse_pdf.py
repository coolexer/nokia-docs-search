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

    # Group by document base (doc number is the part before _V1_)
    groups = {}
    for pdf in pdfs:
        doc_num = pdf.name.split("_V1_")[0] if "_V1_" in pdf.name else pdf.stem
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
    """True if the block is a running page header or footer (all text <= noise threshold)."""
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
    import fitz  # deferred so filename utilities work without PyMuPDF installed

    chassis, release = _chassis_from_filename(pdf_path)
    chassis_slug = _slug(chassis)
    page_title = chassis
    if "Chassis" not in chassis:
        page_title += " Chassis Installation Guide"
    if release:
        page_title += f" {release}"
    rel_path = f"install/{chassis_slug}.pdf"

    doc = fitz.open(str(pdf_path))
    try:
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
