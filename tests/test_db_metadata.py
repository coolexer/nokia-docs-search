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
