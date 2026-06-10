import sqlite3

import pytest
from click.testing import CliRunner

from nokia_docs import db
from nokia_docs.cli import main
from nokia_docs.server import _validate_database


def test_open_write_db_records_schema_metadata(tmp_path):
    db_path = tmp_path / "nokia_docs.db"

    conn = db.open_write_db(db_path)
    try:
        rows = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    finally:
        conn.close()

    assert rows["schema_version"] == str(db.SCHEMA_VERSION)
    assert rows["app_name"] == "nokia-docs-search"


def test_server_rejects_missing_metadata(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="metadata"):
        _validate_database(db_path)


def test_server_rejects_incompatible_schema_version(tmp_path):
    db_path = tmp_path / "old.db"
    conn = db.open_write_db(db_path)
    try:
        conn.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
            (str(db.SCHEMA_VERSION - 1),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="schema version"):
        _validate_database(db_path)


def test_build_manifest_is_recorded(tmp_path):
    db_path = tmp_path / "nokia_docs.db"
    conn = db.open_write_db(db_path)
    try:
        db.record_build_manifest(
            conn,
            {
                "git_commit": "abc123",
                "html_source": "C:/docs/html",
                "html_files": 12,
            },
        )
        rows = dict(conn.execute("SELECT key, value FROM build_manifest").fetchall())
    finally:
        conn.close()

    assert rows["git_commit"] == "abc123"
    assert rows["html_source"] == "C:/docs/html"
    assert rows["html_files"] == "12"


def test_validate_db_command_reports_ok(tmp_path):
    db_path = tmp_path / "nokia_docs.db"
    conn = db.open_write_db(db_path)
    try:
        conn.commit()
    finally:
        conn.close()

    result = CliRunner().invoke(main, ["validate-db", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Database validation OK" in result.output


def test_validate_db_command_fails_on_body_mismatch(tmp_path):
    db_path = tmp_path / "broken.db"
    conn = db.open_write_db(db_path)
    try:
        conn.execute(
            """INSERT INTO docs
               (product_line, book, rel_path, page_title, section_id,
                section_title, section_path, depth, char_len)
               VALUES ('sros-26-3', 'mpls', 'x.html', 'p', 's', 'title', 'path', 0, 4)"""
        )
        conn.commit()
    finally:
        conn.close()

    result = CliRunner().invoke(main, ["validate-db", "--db", str(db_path)])

    assert result.exit_code != 0
    assert "docs/docs_body row count mismatch" in result.output


def test_open_write_db_creates_standards_tables(tmp_path):
    db_path = tmp_path / "nokia_docs.db"
    conn = db.open_write_db(db_path)
    try:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "standards_sources" in table_names
    assert "standards" in table_names
    assert "standards_fts" in table_names


def test_validate_database_reports_standards_fts_mismatch(tmp_path):
    db_path = tmp_path / "broken-standards.db"
    conn = db.open_write_db(db_path)
    try:
        conn.execute(
            """INSERT INTO standards_sources
               (source_path, source_name, source_sha256, indexed_utc)
               VALUES ('fixture.xlsx', 'fixture.xlsx', 'abc', '2026-06-09T00:00:00+00:00')"""
        )
        source_id = conn.execute("SELECT id FROM standards_sources").fetchone()[0]
        conn.execute(
            """INSERT INTO standards
               (source_id, product_line, platform, release, group_title,
                standard_ref, standard_title, standard_text, support_status,
                sheet_name, row_number)
               VALUES (?, 'sros-standards', '7250 IXR', '26.3.R1', 'BFD',
                       'RFC 5880', 'Bidirectional Forwarding Detection',
                       'RFC 5880, Bidirectional Forwarding Detection (BFD)',
                       'supported', 'SR OS 26.3.R1 Standards', 2)""",
            (source_id,),
        )
        conn.commit()

        errors = db.validate_database(conn)
    finally:
        conn.close()

    assert any("standards/standards_fts row count mismatch" in error for error in errors)
