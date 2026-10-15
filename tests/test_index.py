import logging
from pathlib import Path

from nokia_docs import index as index_module


def test_parse_worker_logs_failed_file(monkeypatch, caplog, tmp_path):
    html_path = tmp_path / "broken.html"
    html_path.write_text("<html></html>", encoding="utf-8")

    def boom(path: Path, root: Path):
        raise ValueError("bad html")

    monkeypatch.setattr(index_module, "parse_html", boom)

    with caplog.at_level(logging.WARNING, logger="nokia_docs.index"):
        result = index_module._parse_worker((html_path, tmp_path, None))

    assert result.chunks == []
    assert result.failed_file == str(html_path)
    assert result.error == "bad html"
    assert "Parse failed" in caplog.text
    assert "broken.html" in caplog.text
    assert "bad html" in caplog.text


def test_parse_worker_applies_product_override(monkeypatch, tmp_path):
    html_path = tmp_path / "feature.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    chunk = type("Chunk", (), {"product_line": "unknown"})()

    monkeypatch.setattr(index_module, "parse_html", lambda path, root: [chunk])

    result = index_module._parse_worker((html_path, tmp_path, "srlinux-26-7"))

    assert result.chunks[0].product_line == "srlinux-26-7"
