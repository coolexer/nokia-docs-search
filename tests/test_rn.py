import json
import sqlite3
from pathlib import Path

from nokia_docs.rn import index_release_notes
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
