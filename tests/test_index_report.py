from pathlib import Path

from click.testing import CliRunner

from nokia_docs import index as index_module
from nokia_docs.cli import main


def test_index_command_prints_structured_summary(tmp_path: Path):
    docs_root = tmp_path / "docs"
    html_path = docs_root / "26-3" / "7750-sr" / "books" / "mpls" / "rsvp.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        """<html><head><title>MPLS</title></head><body>
        <div class="wh_topic_content">
          <article id="rsvp"><h1>RSVP</h1><p>RSVP body.</p></article>
        </div>
        </body></html>""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main,
        [
            "index",
            str(docs_root),
            "-o",
            str(tmp_path / "nokia_docs.db"),
            "--reset",
            "--workers",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Index summary" in result.output
    assert "HTML files parsed : 1" in result.output
    assert "Chunks inserted   : 1" in result.output
    assert "Parse failures    : 0" in result.output
    assert "Write failures    : 0" in result.output


def test_index_command_interrupt_exits_nonzero(monkeypatch, tmp_path: Path):
    docs_root = tmp_path / "docs"
    html_path = docs_root / "26-3" / "7750-sr" / "books" / "mpls" / "rsvp.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html></html>", encoding="utf-8")

    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(index_module, "_parse_worker", interrupt)

    result = CliRunner().invoke(
        main,
        [
            "index",
            str(docs_root),
            "-o",
            str(tmp_path / "nokia_docs.db"),
            "--reset",
            "--workers",
            "1",
        ],
    )

    assert result.exit_code != 0
    assert "Index interrupted" in result.output


def test_index_command_fail_on_error_exits_nonzero(monkeypatch, tmp_path: Path):
    docs_root = tmp_path / "docs"
    html_path = docs_root / "26-3" / "7750-sr" / "books" / "mpls" / "rsvp.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(index_module, "parse_html", lambda _path, _root: (_ for _ in ()).throw(ValueError("bad html")))

    result = CliRunner().invoke(
        main,
        [
            "index",
            str(docs_root),
            "-o",
            str(tmp_path / "nokia_docs.db"),
            "--reset",
            "--workers",
            "1",
            "--fail-on-error",
        ],
    )

    assert result.exit_code != 0
    assert "Failed to index 1 HTML file" in result.output
    assert "Parse failures    : 1" in result.output
