"""Parse Nokia standards compliance spreadsheets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

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
    match = re.search(
        r"(?:SR OS|SR Linux)\s+([0-9][0-9.]*?(?:\.R\d+)?)\s+Standards",
        sheet_name,
        flags=re.IGNORECASE,
    )
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
    try:
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
