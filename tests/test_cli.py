from click.testing import CliRunner

from nokia_docs.cli import main


def test_cli_exposes_index_rn_command():
    result = CliRunner().invoke(main, ["index-rn", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia release notes" in result.output


def test_cli_exposes_index_fail_on_error():
    result = CliRunner().invoke(main, ["index", "--help"])
    assert result.exit_code == 0
    assert "--fail-on-error" in result.output


def test_cli_exposes_validate_db_command():
    result = CliRunner().invoke(main, ["validate-db", "--help"])
    assert result.exit_code == 0
    assert "Validate a Nokia documentation search database" in result.output


def test_cli_exposes_build_db_command():
    result = CliRunner().invoke(main, ["build-db", "--help"])
    assert result.exit_code == 0
    assert "Build a complete Nokia documentation search database" in result.output
    assert "--html-root" in result.output
    assert "--rn-dir" in result.output
    assert "--pdf-dir" in result.output
    assert "--strict" in result.output


def test_build_db_accepts_optional_standards_files():
    result = CliRunner().invoke(main, ["build-db", "--help"])
    assert result.exit_code == 0
    assert "--standards-file" in result.output


def test_cli_exposes_index_rn_fail_on_error():
    result = CliRunner().invoke(main, ["index-rn", "--help"])
    assert result.exit_code == 0
    assert "--fail-on-error" in result.output


def test_cli_exposes_index_pdf_command():
    result = CliRunner().invoke(main, ["index-pdf", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia chassis installation guide PDFs" in result.output
    assert "--pdf-dir" in result.output
    assert "--fail-on-error" in result.output
    assert "C:\\!" not in result.output


def test_cli_exposes_reindex_commands():
    result = CliRunner().invoke(main, ["reindex-rn", "--help"])
    assert result.exit_code == 0
    assert "Remove existing release notes" in result.output

    result = CliRunner().invoke(main, ["reindex-pdf", "--help"])
    assert result.exit_code == 0
    assert "Remove existing installation guide rows" in result.output


def test_cli_exposes_standards_commands():
    result = CliRunner().invoke(main, ["index-standards", "--help"])
    assert result.exit_code == 0
    assert "Index Nokia standards compliance spreadsheets" in result.output
    assert "--standards-file" in result.output
    assert "--product" in result.output

    result = CliRunner().invoke(main, ["reindex-standards", "--help"])
    assert result.exit_code == 0
    assert "Remove existing standards rows" in result.output
