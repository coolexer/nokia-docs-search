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
