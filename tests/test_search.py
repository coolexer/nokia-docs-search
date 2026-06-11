import sqlite3
from pathlib import Path

from nokia_docs.index import _insert_chunks, _open_db
from nokia_docs.parse import Chunk
from nokia_docs.search import (
    _sanitize_query,
    _term_present,
    get_page_sections,
    plan_search_queries,
    search_docs,
)


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
            Chunk(
                product_line="sros-26-3",
                book="system-management",
                rel_path="26-3/books/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp-boundary-clock",
                section_title="PTP boundary clock",
                section_path="System management > PTP > Boundary clock",
                depth=2,
                body="PTP boundary clock supports ITU-T G.8273.2 telecom profile behavior.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="system-management",
                rel_path="26-3/books/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp-clock-classes",
                section_title="PTP clock classes",
                section_path="System management > PTP > Clock classes",
                depth=3,
                body="Class C and class D clock behavior is described for timing deployments.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="qos",
                rel_path="26-3/books/qos/schedulers.html",
                page_title="Virtual hierarchical scheduling",
                section_id="virtual-hierarchical-scheduling",
                section_title="Virtual hierarchical scheduling",
                section_path="QoS policies > Scheduler policies > Virtual hierarchical scheduling",
                depth=2,
                body="Hierarchical scheduler policies support egress aggregate rate behavior.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="services",
                rel_path="26-3/books/services/vpls.html",
                page_title="VPLS BGP auto discovery",
                section_id="vpls-bgp-auto-discovery",
                section_title="BGP auto discovery for VPLS",
                section_path="Services > VPLS > BGP auto discovery",
                depth=2,
                body="BGP AD auto discovery VPLS signaling exchanges service membership.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="fallback",
                rel_path="26-3/books/fallback/alpha.html",
                page_title="Alpha beta strict seed",
                section_id="alpha-beta-strict",
                section_title="Alpha beta strict seed",
                section_path="Fallback > Alpha beta strict seed",
                depth=2,
                body="Alpha beta 7250 appears only in this strict seed section.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="fallback",
                rel_path="26-3/books/fallback/alpha.html",
                page_title="Alpha beta relaxed one",
                section_id="alpha-beta-relaxed-one",
                section_title="Alpha beta relaxed one",
                section_path="Fallback > Alpha beta relaxed one",
                depth=2,
                body="Alpha beta relaxed result one.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="fallback",
                rel_path="26-3/books/fallback/alpha.html",
                page_title="Alpha beta relaxed two",
                section_id="alpha-beta-relaxed-two",
                section_title="Alpha beta relaxed two",
                section_path="Fallback > Alpha beta relaxed two",
                depth=2,
                body="Alpha beta relaxed result two.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="fallback",
                rel_path="26-3/books/fallback/alpha.html",
                page_title="Alpha beta relaxed three",
                section_id="alpha-beta-relaxed-three",
                section_title="Alpha beta relaxed three",
                section_path="Fallback > Alpha beta relaxed three",
                depth=2,
                body="Alpha beta relaxed result three.",
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


def test_long_ptp_query_falls_back_to_relaxed(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs(
            "PTP boundary clock G.8273.2 class C class D 7250 IXR-e2",
            conn,
            top_k=5,
        )
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].match_mode in {"relaxed", "soft"}


def test_signalling_query_falls_back_to_variant(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("BGP-AD auto-discovery VPLS signalling", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "BGP auto discovery for VPLS"
    assert hits[0].match_mode in {"variant", "soft"}


def test_qos_query_uses_soft_fallback_when_one_term_is_absent(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs(
            "hierarchical QoS scheduler egress aggregate shaping rate",
            conn,
            top_k=5,
        )
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "Virtual hierarchical scheduling"
    assert hits[0].match_mode == "soft"


def test_short_query_stays_strict(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("boundary clock", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].match_mode == "strict"


def test_non_strict_fallback_appends_to_partial_strict_results(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("alpha beta 7250", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "Alpha beta strict seed"
    assert hits[0].match_mode == "strict"
    assert len({hit.doc_id for hit in hits}) == len(hits)
    assert any(hit.match_mode == "relaxed" for hit in hits[1:])


def test_duplicate_only_relaxed_candidate_continues_to_variant(tmp_path):
    db_path = tmp_path / "duplicate-relaxed.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="services",
                rel_path="26-3/books/services/noisy-signalling.html",
                page_title="Noisy BGP-AD auto-discovery VPLS signalling",
                section_id="noisy-signalling",
                section_title="Noisy BGP-AD auto-discovery VPLS signalling",
                section_path="Services > VPLS > Noisy signalling",
                depth=2,
                body="BGP-AD auto-discovery VPLS signalling 7250.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="services",
                rel_path="26-3/books/services/variant-signaling.html",
                page_title="Variant BGP-AD auto-discovery VPLS signaling",
                section_id="variant-signaling",
                section_title="Variant BGP-AD auto-discovery VPLS signaling",
                section_path="Services > VPLS > Variant signaling",
                depth=2,
                body="BGP-AD auto-discovery VPLS signaling.",
            ),
        ],
    )
    conn.commit()
    try:
        hits = search_docs("BGP-AD auto-discovery VPLS signalling 7250", conn, top_k=5)
    finally:
        conn.close()

    assert [hit.section_title for hit in hits] == [
        "Noisy BGP-AD auto-discovery VPLS signalling",
        "Variant BGP-AD auto-discovery VPLS signaling",
    ]
    assert [hit.match_mode for hit in hits] == ["strict", "variant"]
    assert len({hit.doc_id for hit in hits}) == len(hits)


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


def test_plan_search_queries_preserves_lowercase_meaningful_short_terms():
    candidates = plan_search_queries("ip routing 7750")

    relaxed = [c for c in candidates if c.match_mode == "relaxed"]
    assert relaxed
    assert relaxed[0].important_terms == ["ip", "routing"]
    assert '"ip"*' in relaxed[0].fts_query


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


def test_soft_term_matching_uses_boundaries():
    assert _term_present("as", "AS path")
    assert _term_present("ad", "BGP AD auto discovery")
    assert not _term_present("as", "class behavior")
    assert not _term_present("ip", "membership")


def test_get_page_sections_returns_same_page_tree(tmp_path):
    conn = _build_db(tmp_path)
    try:
        seed = search_docs("boundary clock", conn, top_k=1)[0]
        page = get_page_sections(seed.doc_id, conn)
    finally:
        conn.close()

    assert page is not None
    assert page["rel_path"] == "26-3/books/system/ptp.html"
    assert [s["section_title"] for s in page["sections"]] == [
        "PTP boundary clock",
        "PTP clock classes",
    ]
    assert page["sections"][0]["section_id"] == "ptp-boundary-clock"
    assert page["sections"][0]["depth"] == 2


def test_get_page_sections_returns_none_for_unknown_doc_id(tmp_path):
    conn = _build_db(tmp_path)
    try:
        page = get_page_sections(999999, conn)
    finally:
        conn.close()

    assert page is None
