import sqlite3
from pathlib import Path

from nokia_docs.index import _insert_chunks, _open_db
from nokia_docs.parse import Chunk
from nokia_docs.search import _sanitize_query, plan_search_queries, search_docs


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


def test_plan_search_queries_starts_with_strict_candidate():
    candidates = plan_search_queries("boundary clock")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].fts_query == '"boundary clock" OR ("boundary"* AND "clock"*)'
    assert candidates[0].important_terms == ["boundary", "clock"]


def test_plan_search_queries_relaxes_product_and_class_noise():
    candidates = plan_search_queries("PTP boundary clock G.8273.2 class C class D 7250 IXR-e2")

    relaxed = [c for c in candidates if c.match_mode == "relaxed"]
    assert relaxed
    assert relaxed[0].important_terms == ["PTP", "boundary", "clock", "G.8273.2"]
    assert "7250" not in relaxed[0].fts_query
    assert "IXR-e2" not in relaxed[0].fts_query


def test_plan_search_queries_removes_lowercase_product_noise():
    candidates = plan_search_queries("ixr-e2 boundary clock")

    relaxed = [c for c in candidates if c.match_mode == "relaxed"]
    assert relaxed
    assert relaxed[0].important_terms == ["boundary", "clock"]
    assert "ixr-e2" not in relaxed[0].fts_query.lower()


def test_plan_search_queries_preserves_mixed_quoted_query():
    candidates = plan_search_queries('"boundary clock" protocol')

    assert len(candidates) == 1
    assert candidates[0].match_mode == "strict"
    assert candidates[0].fts_query == '"boundary clock" protocol'
    assert candidates[0].important_terms == ["protocol"]


def test_plan_search_queries_adds_spelling_and_punctuation_variants():
    candidates = plan_search_queries("BGP-AD auto-discovery VPLS signalling")

    variant_queries = [c.fts_query for c in candidates if c.match_mode == "variant"]
    joined = "\n".join(variant_queries)
    assert '"signaling"*' in joined
    assert '"BGP"*' in joined
    assert '"AD"*' in joined
    assert '"auto"*' in joined
    assert '"discovery"*' in joined


def test_plan_search_queries_ends_with_soft_candidate_for_long_query():
    candidates = plan_search_queries("hierarchical QoS scheduler egress aggregate rate")

    assert candidates[-1].match_mode == "soft"
    assert " OR " in candidates[-1].fts_query
    assert candidates[-1].important_terms == [
        "hierarchical",
        "QoS",
        "scheduler",
        "egress",
        "aggregate",
        "rate",
    ]
