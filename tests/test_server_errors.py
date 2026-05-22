import pytest

from nokia_docs import server


def _callable_tool(tool):
    return getattr(tool, "fn", tool)


def test_search_docs_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.search_docs)("rsvp")


def test_list_products_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.list_products)()
