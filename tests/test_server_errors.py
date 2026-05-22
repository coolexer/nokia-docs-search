import pytest

from nokia_docs import server


def test_search_docs_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        server.search_docs.fn("rsvp")


def test_list_products_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        server.list_products.fn()
