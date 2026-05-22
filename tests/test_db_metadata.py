import sqlite3

import pytest

from nokia_docs import db
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
