import json
import sqlite3
from pathlib import Path

import click
import pytest
from openpyxl import Workbook

from nokia_docs.rn import index_release_notes, load_xlsx_product
from nokia_docs.search import search_docs


def test_index_release_notes_fixture_returns_report_and_searchable_rows(tmp_path: Path):
    rn_dir = tmp_path / "rn"
    rn_dir.mkdir()
    (rn_dir / "rn_sros.csv").write_text(
        "title,section,releaseList,platforms,ux-a,ref,number,text\n"
        "context,,,,,,,\n"
        "EVPN route fix,Resolved Issues,26.3.R1,7750 SR,EVPN,PR123,RN123,<p>Resolved EVPN route leak.</p>\n",
        encoding="utf-8",
    )
    (rn_dir / "rn_eol.json").write_text(
        json.dumps(
            [
                {
                    "title": "Historical BGP fix",
                    "type": "Resolved Issues",
                    "rel": "19.10.R12",
                    "text": "Resolved BGP graceful restart issue.",
                }
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "nokia_docs.db"
    report = index_release_notes(db_path, rn_dir)

    assert report.inserted == 2
    assert report.source_counts["sros"] == 1
    assert report.source_counts["eol"] == 1

    conn = sqlite3.connect(db_path)
    try:
        hits = search_docs("EVPN route leak", conn, product_line="rn-sros")
    finally:
        conn.close()

    assert [h.section_title for h in hits] == ["EVPN route fix"]


def test_index_release_notes_fail_on_error_requires_all_sources(tmp_path: Path):
    rn_dir = tmp_path / "rn"
    rn_dir.mkdir()

    with pytest.raises(click.ClickException, match="Missing release-note source"):
        index_release_notes(tmp_path / "nokia_docs.db", rn_dir, fail_on_error=True)


def _write_rn_workbook(path: Path, title: str = "EVPN over SRv6") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "rn"
    sheet.append(
        ["release", "number", "bullet", "beta", "section", "header", "platforms", "ref", "text"]
    )
    sheet.append(
        [
            "26.3.R2",
            "3.2.1",
            1,
            0,
            "New features",
            title,
            "7750 SR-1se",
            "fid.1234.1",
            "Adds an SRv6 data plane to EVPN.",
        ]
    )
    workbook.save(path)


def test_load_xlsx_product_maps_native_release_note_columns(tmp_path: Path):
    _write_rn_workbook(tmp_path / "release-notes-sros.xlsx")

    records = load_xlsx_product("sros", tmp_path)

    assert len(records) == 1
    assert records[0]["product_line"] == "rn-sros"
    assert records[0]["rel_path"] == "rn/sros/26-3-r2/new-features.html"
    assert records[0]["section_id"] == "3.2.1"
    assert records[0]["section_title"] == "EVPN over SRv6"
    assert "Platforms: 7750 SR-1se" in records[0]["body"]
    assert "Releases: 26.3.R2 (26.3)" in records[0]["body"]


def test_index_release_notes_prefers_xlsx_over_legacy_csv(tmp_path: Path):
    rn_dir = tmp_path / "rn"
    rn_dir.mkdir()
    _write_rn_workbook(rn_dir / "release-notes-sros.xlsx", title="XLSX entry")
    (rn_dir / "rn_sros.csv").write_text(
        "title,section,releaseList,platforms,ux-a,ref,number,text\n"
        "context,,,,,,,\n"
        "CSV entry,Resolved issues,26.3.R1,7750 SR,,,RN1,Legacy row\n",
        encoding="utf-8",
    )

    report = index_release_notes(tmp_path / "nokia_docs.db", rn_dir)

    assert report.inserted == 1
    assert report.source_files["sros"] == "release-notes-sros.xlsx"
    conn = sqlite3.connect(tmp_path / "nokia_docs.db")
    try:
        titles = conn.execute("SELECT section_title FROM docs").fetchall()
    finally:
        conn.close()
    assert titles == [("XLSX entry",)]
