import pytest

from nokia_docs import server


def _callable_tool(tool):
    return getattr(tool, "fn", tool)


def test_search_docs_reply_omits_path_and_score(monkeypatch):
    from nokia_docs.search import Hit

    hit = Hit(
        1,
        "sros-26-3",
        "mpls",
        "RSVP",
        "RSVP interface",
        "MPLS > RSVP",
        "a/b.html",
        "[[RSVP]]",
        1.5,
        "strict",
    )
    monkeypatch.setattr(server, "_get_conn", lambda: object())
    monkeypatch.setattr(server, "_search_docs", lambda **kwargs: [hit])

    rows = _callable_tool(server.search_docs)("rsvp")

    assert set(rows[0]) == {
        "doc_id",
        "product_line",
        "book",
        "page_title",
        "section_title",
        "section_path",
        "snippet",
        "match_mode",
    }


def test_search_docs_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.search_docs)("rsvp")


def test_list_products_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.list_products)()


def test_get_page_sections_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.get_page_sections)(123, max_sections=10, query="ospf")


def test_get_document_raises_startup_errors_with_compact_args(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.get_document)(123, max_chars=100, query="boundary clock")


def test_search_standards_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.search_standards)("RFC 5880")


def test_summarize_standard_support_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.summarize_standard_support)("RFC 5880")


def test_list_standards_products_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.list_standards_products)()
