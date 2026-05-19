"""Unit tests for parse_pdf filename utilities."""
from pathlib import Path
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nokia_docs.parse_pdf import (
    _doc_base,
    _issue_num,
    _chassis_from_filename,
    _slug,
    deduplicate_pdfs,
)


# ---------- _doc_base ----------

def test_doc_base_strips_trailing_digits():
    assert _doc_base("3HE19506AAABTQZZA01") == "3HE19506AAABTQZZA"

def test_doc_base_no_issue():
    assert _doc_base("3HE10360AAAATQZZA") == "3HE10360AAAATQZZA"

def test_doc_base_two_digit_issue():
    assert _doc_base("3HE16319AAACTQZZA05") == "3HE16319AAACTQZZA"

def test_doc_base_four_digit_issue():
    assert _doc_base("3HE17922AAAATQZZA06") == "3HE17922AAAATQZZA"


# ---------- _issue_num ----------

def test_issue_num_with_digits():
    assert _issue_num(Path("3HE19506AAABTQZZA01_V1_foo.pdf")) == 1

def test_issue_num_no_digits():
    assert _issue_num(Path("3HE10360AAAATQZZA_V1_foo.pdf")) == 0

def test_issue_num_07():
    assert _issue_num(Path("3HE16108AAAATQZZA07_V1_foo.pdf")) == 7


# ---------- _chassis_from_filename ----------

def test_chassis_basic():
    chassis, release = _chassis_from_filename(
        Path("3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf")
    )
    assert chassis == "7705 SAR-Ax"
    assert release == "23.10.R1"

def test_chassis_sr_os_release():
    chassis, release = _chassis_from_filename(
        Path("3HE16319AAACTQZZA05_V1_7750 SR-1s Chassis Installation Guide 20.7.pdf")
    )
    assert chassis == "7750 SR-1s"
    assert release == "20.7"

def test_chassis_srlinux_no_release():
    chassis, release = _chassis_from_filename(
        Path("3HE16108AAAATQZZA07_V1_SR Linux 7220 IXR-D Chassis Installation Guide.pdf")
    )
    assert chassis == "SR Linux 7220 IXR-D"
    assert release == ""

def test_chassis_no_v1_marker():
    chassis, release = _chassis_from_filename(Path("unknown_doc.pdf"))
    assert chassis == "unknown_doc"
    assert release == ""


# ---------- deduplicate_pdfs ----------

def test_deduplicate_keeps_highest_issue(tmp_path):
    for name in [
        "3HE16108AAAATQZZA05_V1_foo.pdf",
        "3HE16108AAAATQZZA06_V1_foo.pdf",
        "3HE16108AAAATQZZA07_V1_foo.pdf",
    ]:
        (tmp_path / name).touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
    assert result[0].name == "3HE16108AAAATQZZA07_V1_foo.pdf"

def test_deduplicate_no_issue_vs_with_issue(tmp_path):
    """File with no issue suffix (issue=0) loses to file with issue 02."""
    (tmp_path / "3HE18438AAAATQZZA_V1_foo.pdf").touch()
    (tmp_path / "3HE18438AAAATQZZA02_V1_foo.pdf").touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
    assert result[0].name == "3HE18438AAAATQZZA02_V1_foo.pdf"

def test_deduplicate_distinct_doc_numbers_both_kept(tmp_path):
    (tmp_path / "3HE19133AAAATQZZA04_V1_SAR-Hm 22.10.pdf").touch()
    (tmp_path / "3HE21656AAAATQZZA01_V1_SAR-Hm 25.10.pdf").touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 2

def test_deduplicate_single_file(tmp_path):
    (tmp_path / "3HE10360AAAATQZZA_V1_7210 SAS-Mxp.pdf").touch()
    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1


# ---------- parse_pdf integration ----------

SAMPLE_PDF = Path(r"C:\!Docs\OneDrive - Nokia\Docs\chassis installation guide\3HE19506AAABTQZZA01_V1_7705 SAR-Ax Chassis Installation Guide 23.10.R1.pdf")


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_returns_chunks():
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    assert len(chunks) > 20, "Expected many sections in a 144-page guide"


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_chunk_structure():
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    required_keys = {
        "product_line", "book", "rel_path", "page_title",
        "section_id", "section_title", "section_path", "depth", "char_len", "body",
    }
    for chunk in chunks:
        assert required_keys == set(chunk.keys()), f"Missing keys: {required_keys - set(chunk.keys())}"
        assert chunk["product_line"] == "install-guides"
        assert chunk["book"]
        assert chunk["section_title"]
        assert chunk["body"]


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_no_noise():
    """Running headers / footers should not appear in body."""
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    for chunk in chunks:
        assert "Nokia Confidential" not in chunk["body"]


@pytest.mark.skipif(
    not SAMPLE_PDF.exists(),
    reason="Nokia PDF not available in test environment",
)
def test_parse_pdf_no_oversized_chunks():
    """No chunk body should exceed 4000 chars."""
    from nokia_docs.parse_pdf import parse_pdf
    chunks = parse_pdf(SAMPLE_PDF)
    for chunk in chunks:
        assert chunk["char_len"] <= 4000, (
            f"Oversized chunk '{chunk['section_title']}': {chunk['char_len']} chars"
        )


# ---------- index_pdf smoke ----------

def test_index_pdf_script_is_importable():
    """index_pdf.py must be importable without side-effects."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "index_pdf",
        Path(__file__).parent.parent / "index_pdf.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")


# ---------- search aliases ----------

def test_install_guides_alias_resolves():
    from nokia_docs.search import _resolve_product
    assert _resolve_product("install") == "install-guides"
    assert _resolve_product("chassis") == "install-guides"
    assert _resolve_product("install guide") == "install-guides"
    assert _resolve_product("install guides") == "install-guides"
    assert _resolve_product("installation") == "install-guides"
    assert _resolve_product("chassis guide") == "install-guides"
    assert _resolve_product("install-guides") == "install-guides"


# ---------- deduplicate_pdfs — non-_V1_ fallback ----------

def test_deduplicate_no_v1_marker_groups_by_doc_base(tmp_path):
    """Files without _V1_ marker are grouped by doc base (trailing digits stripped).

    Real Nokia PDFs always carry the _V1_ separator. This test covers the bare
    doc-number-only fallback shape (e.g. an archived download named just by
    document number, no description appended).
    """
    (tmp_path / "3HE10360AAAATQZZA.pdf").touch()
    (tmp_path / "3HE10360AAAATQZZA02.pdf").touch()

    result = deduplicate_pdfs(tmp_path)
    assert len(result) == 1
    assert result[0].name == "3HE10360AAAATQZZA02.pdf"
