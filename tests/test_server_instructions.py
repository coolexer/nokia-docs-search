import inspect

from nokia_docs import server


def _tool_fn(tool):
    return getattr(tool, "fn", tool)


def test_mcp_instructions_include_search_routing_hints():
    instructions = server.mcp.instructions

    for term in [
        "chassis installation",
        "hardware guide",
        "power",
        "fan",
        "ports",
        "optics",
        "release notes",
        "new-features",
        "enhancements",
        "resolved-issues",
        "known-issues",
        "scale",
        "capacity",
        "search_standards",
        "get_page_sections",
        "match_mode",
    ]:
        assert term in instructions


def test_mcp_instructions_include_bounded_page_section_guidance():
    instructions = server.mcp.instructions

    for term in [
        "bounded get_page_sections",
        "max_sections=0",
        "full page map",
    ]:
        assert term in instructions


def test_mcp_instructions_include_compact_document_guidance():
    instructions = server.mcp.instructions

    for term in [
        "get_document(query=",
        "max_chars",
        "full body",
        "final evidence",
    ]:
        assert term in instructions


def test_mcp_instructions_include_standards_summary_guidance():
    instructions = server.mcp.instructions

    for term in [
        "summarize_standard_support",
        "compact standards",
        "search_standards",
        "exact standards evidence",
    ]:
        assert term in instructions


def test_search_docs_docstring_includes_evidence_routing():
    docstring = inspect.getdoc(_tool_fn(server.search_docs))

    assert docstring is not None
    for term in [
        "chassis installation",
        "hardware guide",
        "release notes",
        "new-features",
        "enhancements",
        "resolved-issues",
        "known-issues",
        "scale",
        "capacity",
        "search_standards",
        "match_mode",
        "get_document",
    ]:
        assert term in docstring
