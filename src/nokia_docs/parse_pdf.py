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
    # Extract filename without extension
    stem = pdf_path.stem

    # Find digits before _V1_ marker
    match = re.search(r"(\d+)_V1_", stem)
    if match:
        return int(match.group(1))
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
