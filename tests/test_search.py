import sqlite3
from pathlib import Path

from nokia_docs.index import _open_db, _insert_chunks
from nokia_docs.parse import Chunk
from nokia_docs.search import _sanitize_query, search_docs


def _build_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="mpls",
                rel_path="26-3/books/mpls/rsvp.html",
                page_title="RSVP configuration",
                section_id="rsvp-interface",
                section_title="RSVP interface configuration",
                section_path="MPLS > RSVP > Interface",
                depth=1,
                body="Configure RSVP interfaces and hold-time values.",
            ),
            Chunk(
                product_line="srlinux-26-3",
                book="interfaces",
                rel_path="sr-linux/books/interfaces/interface.html",
                page_title="Interface configuration",
                section_id="ethernet-interface",
                section_title="Ethernet interface",
                section_path="Interfaces > Ethernet",
                depth=1,
                body="Configure ethernet interfaces.",
            ),
        ],
    )
    conn.commit()
    return conn


def test_sanitize_preserves_prefix_query():
    assert _sanitize_query("rsvp*") == "rsvp*"


def test_sanitize_preserves_mixed_prefix_query():
    assert _sanitize_query("rsvp* interface") == "rsvp* interface"


def test_prefix_query_searches_fts_prefix_terms(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("rsvp*", conn, top_k=5)
    finally:
        conn.close()

    assert [h.section_title for h in hits] == ["RSVP interface configuration"]


def test_prefix_query_can_be_combined_with_product_filter(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("inter*", conn, product_line="sros", top_k=5)
    finally:
        conn.close()

    assert [h.section_title for h in hits] == ["RSVP interface configuration"]
