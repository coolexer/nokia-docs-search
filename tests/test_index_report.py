from pathlib import Path

from click.testing import CliRunner

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
