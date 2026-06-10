"""Parse Nokia standards compliance spreadsheets."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import click
import openpyxl

from nokia_docs.db import (
    delete_standards_product_lines,
    insert_records,
    open_write_db,
    record_build_manifest,
)

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
        if normalized in {"sros", "sr-os", "sr os", SROS_STANDARDS}:
            return SROS_STANDARDS
        if normalized in {"srl", "srlinux", "sr-linux", "sr linux", SRLINUX_STANDARDS}:
            return SRLINUX_STANDARDS
    if sheet_name.lower().startswith("sr linux"):
        return SRLINUX_STANDARDS
    return SROS_STANDARDS


def _extract_release(sheet_name: str) -> str:
    match = re.fullmatch(
        r"(?:SR OS|SR Linux)\s+([0-9][0-9.]*?(?:\.R\d+)?)\s+Standards",
        sheet_name,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def split_standard_text(text: str) -> tuple[str, str]:
    normalized = _normalize_text(text).replace("{", "").replace("}", "")
    parenthesized_title = re.match(r"^(3GPP\s+Release\s+\d+)\s+\((.*)\)$", normalized)
    if parenthesized_title:
        return parenthesized_title.group(1).strip(), parenthesized_title.group(2).strip()

    compound_rfc_list = re.match(
        r"^((?:IETF\s+)?RFC\s+\d+(?:\s*,\s*RFC\s+\d+)+)(?:\s*,\s*(.*))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if compound_rfc_list:
        return compound_rfc_list.group(1).strip(), (compound_rfc_list.group(2) or "").strip()

    patterns = [
        r"^(RFC\s+\d+(?:\s*,\s*RFC\s+\d+)*)\s*,\s*(.*)$",
        r"^(RFC\s+\d+(?:\s*/\s*RFC\s+\d+)*)\s*,\s*(.*)$",
        r"^(IETF\s+RFC\s+\d+(?:\s*/\s*RFC\s+\d+)*)\s*,\s*(.*)$",
        r"^(IEEE\s+\d+(?:\.[A-Za-z0-9]+)*(?:-\d+)?[A-Za-z]*)\s*,\s*(.*)$",
        r"^(3GPP\s+TS\s+\d+(?:\.\d+)*)\s*,\s*(.*)$",
        r"^((?:draft|RFC|ITU-T|MEF|BBF|AF|GR|IETF|ISO|IEC|3GPP)[^,]+)\s*,\s*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    bare_reference_patterns = [
        r"^RFC\s+\d+(?:\s*/\s*RFC\s+\d+)*$",
        r"^IETF\s+RFC\s+\d+(?:\s*/\s*RFC\s+\d+)*$",
        r"^IEEE\s+\d+(?:\.[A-Za-z0-9]+)*(?:-\d+)?[A-Za-z]*$",
        r"^ITU-T\s+[A-Z]\.\d+(?:\.\d+)*$",
        r"^3GPP\s+TS\s+\d+(?:\.\d+)*$",
        r"^3GPP\s+Release\s+\d+$",
        r"^draft-[A-Za-z0-9][A-Za-z0-9._-]*$",
    ]
    for pattern in bare_reference_patterns:
        if re.match(pattern, normalized, flags=re.IGNORECASE):
            return normalized, ""
    return "", normalized


def parse_standards_workbook(
    path: Path,
    product: str | None = None,
) -> list[StandardsRecord]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records: list[StandardsRecord] = []
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows, None)
            if not headers:
                continue
            release = _extract_release(sheet.title)
            if not release:
                continue
            if _normalize_text(headers[0] if headers else "") != "Group Title":
                continue
            product_line = _infer_product(sheet.title, product)
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
                        "not_supported" if standard_text == "Not Supported" else "supported"
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
    finally:
        workbook.close()
    return records


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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
    section_slug = _slug(title) or "standard"
    platform_slug = _slug(record.platform) or "platform"
    section_id = f"{platform_slug}-{record.row_number}-{section_slug}"
    return {
        "product_line": record.product_line,
        "book": "standards-compliance",
        "rel_path": f"standards/{record.product_line}/{record.release}/{record.sheet_name}.xlsx",
        "page_title": f"{record.product_line} {record.release} Standards Compliance",
        "section_id": section_id,
        "section_title": title,
        "section_path": f"{record.release} > {record.group_title} > {record.platform} > {title}",
        "depth": 0,
        "char_len": len(body),
        "body": body,
    }


def _insert_standards_records(
    conn,
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
                standard_id = cur.lastrowid
                conn.execute(
                    """INSERT INTO standards_fts
                       (rowid, product_line, platform, release, group_title,
                        standard_ref, standard_title, standard_text)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        standard_id,
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


def _standards_source_id(conn, source_path: Path, source_sha256: str) -> int:
    indexed_utc = datetime.now(UTC).isoformat(timespec="seconds")
    resolved_path = str(source_path.resolve())
    conn.execute(
        """INSERT OR IGNORE INTO standards_sources
           (source_path, source_name, source_sha256, indexed_utc)
           VALUES (?,?,?,?)""",
        (resolved_path, source_path.name, source_sha256, indexed_utc),
    )
    row = conn.execute(
        """SELECT id FROM standards_sources
           WHERE source_path = ? AND source_sha256 = ?""",
        (resolved_path, source_sha256),
    ).fetchone()
    conn.commit()
    return int(row[0])


def index_standards(
    db_path: Path,
    standards_files: list[Path],
    product: str | None = None,
) -> StandardsIndexReport:
    """Index standards compliance workbooks into structured and shared docs tables."""
    if product and len(standards_files) > 1:
        raise click.ClickException("--product can only be used with one standards workbook.")

    db_path = Path(db_path)
    files = [Path(path) for path in standards_files]
    conn = open_write_db(db_path)
    total = 0
    source_counts: dict[str, int] = {}
    t0 = time.monotonic()
    try:
        for workbook in files:
            source_id = _standards_source_id(conn, workbook, sha256_file(workbook))
            records = parse_standards_workbook(workbook, product=product)
            source_counts[workbook.name] = len(records)
            total += _insert_standards_records(conn, source_id, records)
            supported_docs = [
                _docs_record(record)
                for record in records
                if record.support_status == "supported"
            ]
            insert_records(conn, supported_docs)

        conn.execute("INSERT INTO standards_fts(standards_fts) VALUES('optimize')")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
        conn.commit()
        record_build_manifest(
            conn,
            {
                "standards_files": len(files),
                "standards_records_inserted": total,
                **{f"standards_{key}_records": value for key, value in source_counts.items()},
            },
        )
    finally:
        conn.close()

    elapsed = time.monotonic() - t0
    return StandardsIndexReport(
        inserted=total,
        source_counts=source_counts,
        elapsed_seconds=elapsed,
        db_size_mb=db_path.stat().st_size / 1024 / 1024 if db_path.exists() else 0.0,
    )


def reindex_standards(
    db_path: Path,
    standards_files: list[Path],
    product: str | None = None,
) -> StandardsIndexReport:
    """Remove existing standards rows and index them again."""
    db_path = Path(db_path)
    if product:
        product_lines = [_infer_product("", product)]
    else:
        product_lines = STANDARDS_PRODUCT_LINES
    conn = open_write_db(db_path)
    try:
        delete_standards_product_lines(conn, product_lines)
    finally:
        conn.close()
    return index_standards(db_path, standards_files, product=product)
