import sqlite3
from pathlib import Path

from nokia_docs.db import normalize_fts_text, rebuild_fts
from nokia_docs.index import _insert_chunks, _open_db
from nokia_docs.parse import Chunk
from nokia_docs.search import (
    _sanitize_query,
    get_document,
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
    assert hits[0].match_mode == "strict"


def test_signalling_query_falls_back_to_variant(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("BGP-AD auto-discovery VPLS signalling", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "BGP auto discovery for VPLS"
    assert hits[0].match_mode == "strict"


def test_extra_unmatched_term_returns_no_hits(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs(
            "hierarchical QoS scheduler egress aggregate shaping rate",
            conn,
            top_k=5,
        )
    finally:
        conn.close()

    assert hits == []


def test_short_query_stays_strict(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("boundary clock", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].match_mode == "strict"


def test_search_docs_hits_include_match_mode(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hit = search_docs("boundary clock", conn, top_k=1)[0]
    finally:
        conn.close()

    assert hit.match_mode == "strict"


def test_non_strict_fallback_appends_to_partial_strict_results(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("alpha beta 7250", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert "Alpha beta strict seed" in {hit.section_title for hit in hits}
    assert all(hit.match_mode == "strict" for hit in hits)
    assert len({hit.doc_id for hit in hits}) == len(hits)


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

    assert set(hit.section_title for hit in hits) == {
        "Noisy BGP-AD auto-discovery VPLS signalling",
        "Variant BGP-AD auto-discovery VPLS signaling",
    }
    assert all(hit.match_mode == "strict" for hit in hits)
    assert len({hit.doc_id for hit in hits}) == len(hits)


def test_plan_search_queries_starts_with_strict_candidate():
    candidates = plan_search_queries("boundary clock")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].fts_query == '"boundary clock" OR ("boundary" AND "clock")'
    assert candidates[0].important_terms == ["boundary", "clock"]
    assert all(candidate.match_mode != "soft" for candidate in candidates)


def test_plan_search_queries_relaxes_product_and_class_noise():
    candidates = plan_search_queries("PTP boundary clock G.8273.2 class C class D 7250 IXR-e2")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].important_terms == ["PTP", "boundary", "clock", "G.8273.2"]
    assert "7250" not in candidates[0].fts_query
    assert "IXR-e2" not in candidates[0].fts_query
    assert "*" not in candidates[0].fts_query


def test_plan_search_queries_removes_lowercase_product_noise():
    candidates = plan_search_queries("ixr-e2 boundary clock")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].important_terms == ["boundary", "clock"]
    assert "ixr-e2" not in candidates[0].fts_query.lower()


def test_plan_search_queries_preserves_lowercase_meaningful_short_terms():
    candidates = plan_search_queries("ip routing 7750")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].important_terms == ["ip", "routing"]
    assert '"ip"' in candidates[0].fts_query
    assert '"ip"*' not in candidates[0].fts_query


def test_plan_search_queries_preserves_mixed_quoted_query():
    candidates = plan_search_queries('"boundary clock" protocol')

    assert len(candidates) == 1
    assert candidates[0].match_mode == "strict"
    assert candidates[0].fts_query == '"boundary clock" protocol'
    assert candidates[0].important_terms == ["protocol"]


def test_plan_search_queries_expands_spelling_and_hyphens_in_the_first_query():
    query = plan_search_queries("BGP-AD auto-discovery VPLS signalling")[0].fts_query

    assert '"signaling"' in query
    assert '"signalling"' in query
    assert '"BGP"' in query
    assert '"AD"' in query
    assert '"auto"' in query
    assert '"discovery"' in query
    assert "*" not in query


def test_plan_search_queries_has_no_soft_or():
    candidates = plan_search_queries("hierarchical QoS scheduler egress aggregate rate")

    assert candidates
    assert all(candidate.match_mode != "soft" for candidate in candidates)


def test_single_hyphenated_term_stays_exact():
    assert plan_search_queries("hold-time")[0].fts_query == '"hold-time"'


def test_normalize_fts_text_strips_trailing_period_only():
    assert normalize_fts_text("Configure the clock.") == "Configure the clock"
    assert normalize_fts_text("ITU-T G.8273.2 profile.") == "ITU-T G.8273.2 profile"


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


def test_get_page_sections_returns_bounded_window_around_doc(tmp_path):
    db_path = tmp_path / "bounded-sections.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="md-cli-command-reference",
                rel_path="sros/md-cli-command-reference/service.html",
                page_title="Service commands",
                section_id=f"section-{i}",
                section_title=f"Section {i}",
                section_path=f"configure service section {i}",
                depth=2,
                body=f"Body {i}",
            )
            for i in range(1, 8)
        ],
    )
    conn.commit()
    try:
        result = get_page_sections(4, conn, max_sections=3)
    finally:
        conn.close()

    assert result is not None
    assert result["total_sections"] == 7
    assert result["returned_sections"] == 3
    assert result["truncated"] is True
    assert result["window_start"] == 3
    assert result["window_end"] == 5
    assert [section["doc_id"] for section in result["sections"]] == [3, 4, 5]


def test_get_page_sections_zero_cap_returns_all_sections(tmp_path):
    db_path = tmp_path / "all-sections.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="md-cli-command-reference",
                rel_path="sros/md-cli-command-reference/service.html",
                page_title="Service commands",
                section_id=f"section-{i}",
                section_title=f"Section {i}",
                section_path=f"configure service section {i}",
                depth=2,
                body=f"Body {i}",
            )
            for i in range(1, 8)
        ],
    )
    conn.commit()
    try:
        result = get_page_sections(4, conn, max_sections=0)
    finally:
        conn.close()

    assert result is not None
    assert result["total_sections"] == 7
    assert result["returned_sections"] == 7
    assert result["truncated"] is False
    assert [section["doc_id"] for section in result["sections"]] == list(range(1, 8))


def test_get_page_sections_filters_by_query_before_windowing(tmp_path):
    db_path = tmp_path / "filtered-sections.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="md-cli-command-reference",
                rel_path="sros/md-cli-command-reference/service.html",
                page_title="Service commands",
                section_id="ospf-service",
                section_title="OSPF service",
                section_path="configure service ospf",
                depth=2,
                body="OSPF body",
            ),
            Chunk(
                product_line="sros-26-3",
                book="md-cli-command-reference",
                rel_path="sros/md-cli-command-reference/service.html",
                page_title="Service commands",
                section_id="bgp-service",
                section_title="BGP service",
                section_path="configure service bgp",
                depth=2,
                body="BGP body",
            ),
            Chunk(
                product_line="sros-26-3",
                book="md-cli-command-reference",
                rel_path="sros/md-cli-command-reference/service.html",
                page_title="Service commands",
                section_id="ospf-area",
                section_title="OSPF area",
                section_path="configure router ospf area",
                depth=2,
                body="OSPF area body",
            ),
        ],
    )
    conn.commit()
    try:
        result = get_page_sections(2, conn, max_sections=10, query="ospf")
    finally:
        conn.close()

    assert result is not None
    assert result["total_sections"] == 2
    assert result["returned_sections"] == 2
    assert [section["doc_id"] for section in result["sections"]] == [1, 3]


def test_get_page_sections_returns_none_for_unknown_doc_id(tmp_path):
    conn = _build_db(tmp_path)
    try:
        page = get_page_sections(999999, conn)
    finally:
        conn.close()

    assert page is None


def test_get_document_neighbors_include_path_and_relation(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hit = search_docs("boundary clock", conn, top_k=1)[0]
        doc = get_document(hit.doc_id, conn, include_neighbors=True)
    finally:
        conn.close()

    assert doc is not None
    assert doc.neighbors
    neighbor = doc.neighbors[0]
    assert set(neighbor) == {"doc_id", "section_title", "section_path", "depth", "relation"}
    assert neighbor["section_title"] == "PTP clock classes"
    assert neighbor["relation"] == "same_page"


def test_get_document_caps_body_with_truncation_metadata(tmp_path):
    db_path = tmp_path / "document-cap.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="configuration",
                rel_path="sros/configuration/router.html",
                page_title="Router",
                section_id="router",
                section_title="Router",
                section_path="configure router",
                depth=1,
                body="A" * 300,
            )
        ],
    )
    conn.commit()
    try:
        document = get_document(1, conn, max_chars=80)
    finally:
        conn.close()

    assert document is not None
    assert document.body == "A" * 80
    assert document.body_chars == 300
    assert document.returned_chars == 80
    assert document.body_truncated is True
    assert document.excerpt_query is None


def test_get_document_query_excerpt_centers_first_match(tmp_path):
    body = "prefix " + ("A" * 120) + " boundary clock " + ("B" * 120)
    db_path = tmp_path / "document-excerpt.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="configuration",
                rel_path="sros/configuration/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp-boundary-clock",
                section_title="PTP boundary clock",
                section_path="ptp boundary-clock",
                depth=2,
                body=body,
            )
        ],
    )
    conn.commit()
    try:
        document = get_document(1, conn, query="boundary clock", context_chars=20)
    finally:
        conn.close()

    assert document is not None
    assert "boundary clock" in document.body
    assert len(document.body) <= len("boundary clock") + 40
    assert not document.body.startswith("prefix")
    assert document.body_chars == len(body)
    assert document.returned_chars == len(document.body)
    assert document.body_truncated is True
    assert document.excerpt_query == "boundary clock"


def test_get_document_default_returns_full_body(tmp_path):
    body = "full body " * 100
    db_path = tmp_path / "document-full.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="configuration",
                rel_path="sros/configuration/system.html",
                page_title="System",
                section_id="system",
                section_title="System",
                section_path="configure system",
                depth=1,
                body=body,
            )
        ],
    )
    conn.commit()
    try:
        document = get_document(1, conn)
    finally:
        conn.close()

    assert document is not None
    assert document.body == body
    assert document.body_chars == len(body)
    assert document.returned_chars == len(body)
    assert document.body_truncated is False


def test_trailing_period_still_matches_exact_term(tmp_path):
    db_path = tmp_path / "period.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="system",
                rel_path="sros/system/timing.html",
                page_title="Timing",
                section_id="timing",
                section_title="Timing section",
                section_path="System > Timing",
                depth=1,
                body="Configure the clock.",
            )
        ],
    )
    conn.commit()
    try:
        hits = search_docs("clock", conn, top_k=5)
    finally:
        conn.close()

    assert [hit.section_title for hit in hits] == ["Timing section"]


def test_body_only_section_is_still_found(tmp_path):
    db_path = tmp_path / "titles.db"
    conn = _open_db(db_path, reset=True)
    chunks = [
        Chunk(
            product_line="sros-26-3",
            book="system",
            rel_path=f"sros/system/note-{i}.html",
            page_title=f"boundary clock note {i}",
            section_id=f"note-{i}",
            section_title=f"boundary clock note {i}",
            section_path=f"System > boundary clock note {i}",
            depth=1,
            body="unrelated text",
        )
        for i in range(3)
    ]
    chunks.append(
        Chunk(
            product_line="sros-26-3",
            book="system",
            rel_path="sros/system/body-only.html",
            page_title="Unrelated",
            section_id="body-only",
            section_title="Unrelated",
            section_path="System > Unrelated",
            depth=1,
            body="boundary clock lives only in the body",
        )
    )
    _insert_chunks(conn, chunks)
    conn.commit()
    try:
        hits = search_docs("boundary clock", conn, top_k=5)
    finally:
        conn.close()

    titles = {hit.section_title for hit in hits}
    assert "Unrelated" in titles
    assert any(title.startswith("boundary clock note") for title in titles)


def test_inferred_product_uses_newest_indexed_release(tmp_path):
    db_path = tmp_path / "newest.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="7250-ixr",
                book="hardware",
                rel_path="ixr/hardware/fan.html",
                page_title="Fan tray redundancy",
                section_id="fan-old",
                section_title="Fan tray redundancy",
                section_path="Hardware > Fan tray",
                depth=1,
                body="old fan tray",
            ),
            Chunk(
                product_line="7250-ixr-26-7",
                book="hardware",
                rel_path="ixr-26-7/hardware/fan.html",
                page_title="Fan tray redundancy",
                section_id="fan-new",
                section_title="Fan tray redundancy",
                section_path="Hardware > Fan tray",
                depth=1,
                body="new fan tray",
            ),
        ],
    )
    conn.commit()
    try:
        hits = search_docs("7250 IXR fan tray", conn, top_k=5)
    finally:
        conn.close()

    assert [hit.product_line for hit in hits] == ["7250-ixr-26-7"]


def test_inferred_product_falls_back_when_platform_misses(tmp_path):
    db_path = tmp_path / "fallback-product.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="7250-ixr-26-7",
                book="hardware",
                rel_path="ixr/hardware/power.html",
                page_title="Power supply",
                section_id="power",
                section_title="Power supply",
                section_path="Hardware > Power",
                depth=1,
                body="Fans and power supplies.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="system",
                rel_path="sros/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp",
                section_title="PTP boundary clock",
                section_path="System > PTP",
                depth=1,
                body="PTP boundary clock supports G.8273.2.",
            ),
        ],
    )
    conn.commit()
    try:
        hits = search_docs("PTP boundary clock G.8273.2 7250 IXR", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].product_line == "sros-26-3"


def test_explicit_product_does_not_widen(tmp_path):
    db_path = tmp_path / "explicit.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="7250-ixr",
                book="hardware",
                rel_path="ixr/hardware/power.html",
                page_title="Power supply",
                section_id="power",
                section_title="Power supply",
                section_path="Hardware > Power",
                depth=1,
                body="Power supply details.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="system",
                rel_path="sros/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp",
                section_title="PTP boundary clock",
                section_path="System > PTP",
                depth=1,
                body="PTP boundary clock.",
            ),
        ],
    )
    conn.commit()
    try:
        hits = search_docs("boundary clock", conn, product_line="7250-ixr", top_k=5)
    finally:
        conn.close()

    assert hits == []


def test_get_page_sections_defaults_to_forty(tmp_path):
    db_path = tmp_path / "forty.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="commands",
                rel_path="sros/commands/service.html",
                page_title="Service commands",
                section_id=f"section-{i}",
                section_title=f"Section {i}",
                section_path=f"configure service section {i}",
                depth=2,
                body=f"Body {i}",
            )
            for i in range(1, 51)
        ],
    )
    conn.commit()
    try:
        result = get_page_sections(25, conn)
    finally:
        conn.close()

    assert result is not None
    assert result["total_sections"] == 50
    assert result["returned_sections"] == 40
    assert result["truncated"] is True
    assert any(section["doc_id"] == 25 for section in result["sections"])


def test_rebuild_fts_strips_trailing_periods(tmp_path):
    db_path = tmp_path / "rebuild.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="system",
                rel_path="sros/system/timing.html",
                page_title="Timing",
                section_id="timing",
                section_title="Timing section",
                section_path="System > Timing",
                depth=1,
                body="Configure the clock.",
            )
        ],
    )
    conn.commit()
    conn.execute("DELETE FROM docs_fts")
    conn.execute(
        """INSERT INTO docs_fts(rowid, section_title, page_title, section_path, body)
           VALUES (1, 'Timing section', 'Timing', 'System > Timing', 'Configure the clock.')"""
    )
    conn.commit()
    assert search_docs("clock", conn, top_k=5) == []
    assert rebuild_fts(conn) == 1
    hits = search_docs("clock", conn, top_k=5)
    conn.close()

    assert [hit.section_title for hit in hits] == ["Timing section"]
