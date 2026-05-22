import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from nokia_docs.cli import main


def test_build_db_indexes_sources_and_records_manifest(monkeypatch, tmp_path: Path):
    html_root = tmp_path / "html"
    html_path = html_root / "26-3" / "7750-sr" / "books" / "mpls" / "rsvp.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        """<html><head><title>MPLS</title></head><body>
        <div class="wh_topic_content">
          <article id="rsvp"><h1>RSVP</h1><p>RSVP body.</p></article>
        </div>
        </body></html>""",
        encoding="utf-8",
    )

    rn_dir = tmp_path / "rn"
    rn_dir.mkdir()
    (rn_dir / "rn_sros.csv").write_text(
        "title,section,releaseList,platforms,ux-a,ref,number,text\n"
        "context,,,,,,,\n"
        "EVPN route fix,Resolved Issues,26.3.R1,7750 SR,EVPN,PR123,RN123,<p>Resolved EVPN route leak.</p>\n",
        encoding="utf-8",
    )
    (rn_dir / "rn_eol.json").write_text(
        json.dumps([{"title": "Historical BGP fix", "type": "Resolved Issues", "rel": "19.10.R12", "text": "Resolved BGP issue."}]),
        encoding="utf-8",
    )

    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf"
    pdf_path.touch()

    def fake_parse_pdf(_pdf_path: Path):
        return [
            {
                "product_line": "install-guides",
                "book": "7705-sar-ax",
                "rel_path": "install/7705-sar-ax/fake.pdf",
                "page_title": "7705 SAR-Ax Chassis Installation Guide",
                "section_id": "sec-0",
                "section_title": "Grounding",
                "section_path": "7705 SAR-Ax > Grounding",
                "depth": 0,
                "char_len": 16,
                "body": "Grounding details",
            }
        ]

    monkeypatch.setattr("nokia_docs.pdf_index.parse_pdf", fake_parse_pdf)

    db_path = tmp_path / "nokia_docs.db"
    result = CliRunner().invoke(
        main,
        [
            "build-db",
            "--html-root",
            str(html_root),
            "--rn-dir",
            str(rn_dir),
            "--pdf-dir",
            str(pdf_dir),
            "--output",
            str(db_path),
            "--workers",
            "1",
            "--no-strict",
        ],
    )

    assert result.exit_code == 0
    assert "Database validation OK" in result.output
    assert "SHA256" in result.output
    assert db_path.with_name(f"{db_path.name}.sha256").exists()

    conn = sqlite3.connect(db_path)
    try:
        manifest = dict(conn.execute("SELECT key, value FROM build_manifest").fetchall())
        products = dict(conn.execute("SELECT product_line, COUNT(*) FROM docs GROUP BY product_line").fetchall())
    finally:
        conn.close()

    assert manifest["html_source"] == str(html_root.resolve())
    assert manifest["rn_source"] == str(rn_dir.resolve())
    assert manifest["pdf_source"] == str(pdf_dir.resolve())
    assert manifest["artifact_sha256_file"] == f"{db_path.name}.sha256"
    assert products["sros-26-3"] == 1
    assert products["rn-sros"] == 2
    assert products["install-guides"] == 1
