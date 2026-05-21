from click.testing import CliRunner

from nokia_docs.cli import main


def test_cli_exposes_index_rn_command():
    result = CliRunner().invoke(main, ["index-rn", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia release notes" in result.output


def test_cli_exposes_index_pdf_command():
    result = CliRunner().invoke(main, ["index-pdf", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia chassis installation guide PDFs" in result.output


def test_cli_exposes_reindex_commands():
    result = CliRunner().invoke(main, ["reindex-rn", "--help"])
    assert result.exit_code == 0
    assert "Remove existing release notes" in result.output

    result = CliRunner().invoke(main, ["reindex-pdf", "--help"])
    assert result.exit_code == 0
    assert "Remove existing installation guide rows" in result.output
