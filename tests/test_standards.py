from pathlib import Path

import openpyxl

from nokia_docs.standards import parse_standards_workbook, split_standard_text


def _save_workbook(path: Path, title: str, rows: list[list[str | None]]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _save_workbook_with_sheets(
    path: Path,
    sheets: list[tuple[str, list[list[str | None]]]],
) -> Path:
    wb = openpyxl.Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)
    for title, rows in sheets:
        ws = wb.create_sheet(title=title)
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


def test_parse_skips_non_standards_sheets(tmp_path: Path):
    workbook = _save_workbook_with_sheets(
        tmp_path / "mixed.xlsx",
        [
            (
                "Cover",
                [
                    ["Group Title", "7250 IXR Standards"],
                    ["Cover metadata", "RFC 0000, Should Not Parse"],
                ],
            ),
            (
                "SR OS 26.3.R1 Standards",
                [
                    ["Group Title", "7250 IXR Standards"],
                    ["Bidirectional Forwarding Detection", "RFC 5880, BFD"],
                ],
            ),
        ],
    )

    records = parse_standards_workbook(workbook)

    assert len(records) == 1
    assert records[0].sheet_name == "SR OS 26.3.R1 Standards"
    assert records[0].release == "26.3.R1"


def test_parse_skips_standards_sheet_without_group_title_header(tmp_path: Path):
    workbook = _save_workbook(
        tmp_path / "bad-header.xlsx",
        "SR OS 26.3.R1 Standards",
        [
            ["Not Group Title", "7250 IXR Standards"],
            ["Bidirectional Forwarding Detection", "RFC 5880, BFD"],
        ],
    )

    records = parse_standards_workbook(workbook)

    assert records == []


def test_split_standard_text_preserves_plausible_reference_prefixes():
    cases = [
        (
            "IEEE 802.1Q, Bridges and Bridged Networks",
            "IEEE 802.1Q",
            "Bridges and Bridged Networks",
        ),
        (
            "IEEE 1588-2008, Precision Clock Synchronization Protocol",
            "IEEE 1588-2008",
            "Precision Clock Synchronization Protocol",
        ),
        (
            "IETF RFC 4364, BGP/MPLS IP VPNs",
            "IETF RFC 4364",
            "BGP/MPLS IP VPNs",
        ),
        (
            "3GPP TS 29.244, Interface between CP and UP",
            "3GPP TS 29.244",
            "Interface between CP and UP",
        ),
        (
            "RFC 5880/RFC 5881, BFD bundle",
            "RFC 5880/RFC 5881",
            "BFD bundle",
        ),
        (
            "RFC 4760, RFC 7606, Multiprotocol Extensions for BGP-4",
            "RFC 4760, RFC 7606",
            "Multiprotocol Extensions for BGP-4",
        ),
        (
            "3GPP Release 12 (ADC rules over Gx interfaces)",
            "3GPP Release 12",
            "ADC rules over Gx interfaces",
        ),
    ]

    for standard_text, expected_ref, expected_title in cases:
        standard_ref, standard_title = split_standard_text(standard_text)

        assert standard_ref == expected_ref
        assert standard_title == expected_title


def test_split_standard_text_extracts_bare_reference_only_cells():
    cases = [
        ("RFC 5880", "RFC 5880", ""),
        ("IETF RFC 4364", "IETF RFC 4364", ""),
        ("ITU-T Y.1731", "ITU-T Y.1731", ""),
        ("3GPP Release 12", "3GPP Release 12", ""),
        ("RFC 5880/RFC 5881", "RFC 5880/RFC 5881", ""),
        ("IEEE 802.1Q", "IEEE 802.1Q", ""),
        ("IEEE 1588-2008", "IEEE 1588-2008", ""),
        ("3GPP TS 29.244", "3GPP TS 29.244", ""),
        ("draft-ietf-lsr-isis-area-proxy", "draft-ietf-lsr-isis-area-proxy", ""),
        ("RFC 4760, RFC 7606", "RFC 4760, RFC 7606", ""),
        ("IETF RFC 4364, RFC 8277", "IETF RFC 4364, RFC 8277", ""),
        ("IEEE 802.1ag-2007", "IEEE 802.1ag-2007", ""),
        ("IEEE 802.1X-2010", "IEEE 802.1X-2010", ""),
    ]

    for standard_text, expected_ref, expected_title in cases:
        standard_ref, standard_title = split_standard_text(standard_text)

        assert standard_ref == expected_ref
        assert standard_title == expected_title
