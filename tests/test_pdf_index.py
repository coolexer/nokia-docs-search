from pathlib import Path

import click
import pytest

from nokia_docs import pdf_index


def test_pdf_index_requires_explicit_pdf_dir():
    assert pdf_index.DEFAULT_PDF_DIR is None

    with pytest.raises(click.ClickException, match="PDF directory is required"):
        pdf_index.index_pdfs(Path("nokia_docs.db"))


def test_pdf_index_report_tracks_failed_files(monkeypatch, tmp_path: Path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf"
    pdf_path.touch()

    monkeypatch.setattr(pdf_index, "deduplicate_pdfs", lambda _pdf_dir: [pdf_path])

    def fail_parse(_pdf_path: Path):
        raise RuntimeError("cannot parse")

    monkeypatch.setattr(pdf_index, "parse_pdf", fail_parse)

    report = pdf_index.index_pdfs(tmp_path / "nokia_docs.db", pdf_dir)

    assert report.parsed_files == 0
    assert report.failed_files == [str(pdf_path)]
    assert report.inserted == 0


def test_pdf_index_fail_on_error_raises(monkeypatch, tmp_path: Path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf"
    pdf_path.touch()

    monkeypatch.setattr(pdf_index, "deduplicate_pdfs", lambda _pdf_dir: [pdf_path])
    monkeypatch.setattr(pdf_index, "parse_pdf", lambda _pdf_path: (_ for _ in ()).throw(RuntimeError("cannot parse")))

    with pytest.raises(click.ClickException, match="Failed to index 1 PDF"):
        pdf_index.index_pdfs(tmp_path / "nokia_docs.db", pdf_dir, fail_on_error=True)
