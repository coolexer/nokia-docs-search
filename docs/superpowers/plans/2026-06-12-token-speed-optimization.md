# Nokia Docs Token And Speed Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Nokia Docs MCP and Nokia SOC token spend and latency while preserving strict evidence verification.

**Architecture:** Keep existing search behavior intact and add bounded retrieval APIs around large result surfaces. Add compact standards grouping for reconnaissance, then add a deterministic SOC workbook classifier that plans evidence routes without deciding compliance.

**Tech Stack:** Python 3.11+, SQLite FTS5, FastMCP, pytest, ruff, openpyxl.

---

## File Structure

- Modify `src/nokia_docs/search.py`: add bounded page-section retrieval, document excerpt/capping metadata, and keep default full-document behavior intact.
- Modify `src/nokia_docs/server.py`: expose new optional tool parameters, add `summarize_standard_support`, and update MCP instructions.
- Modify `src/nokia_docs/standards.py`: add compact grouped standards summaries backed by existing `search_standards`.
- Modify `tests/test_search.py`: add bounded page-section and compact document retrieval tests using local SQLite fixtures.
- Modify `tests/test_standards.py`: add grouped standards summary tests.
- Modify `tests/test_server_errors.py`: add MCP wrapper startup-error tests for new tool and changed signatures.
- Modify `tests/test_server_instructions.py`: assert compact retrieval and standards summary guidance stays in MCP instructions.
- Create `C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py`: deterministic XLSX route planner for SOC rows.
- Modify `C:\Users\vikharev\.agents\skills\nokia-soc\SKILL.md`: add classifier-first workflow and compact MCP retrieval discipline.

Repository code changes should be committed in small commits. The `nokia-soc`
skill directory is outside this repository; after editing it, record the exact
changed file paths in the final implementation note.

---

### Task 1: Bounded `get_page_sections`

**Files:**
- Modify: `src/nokia_docs/search.py`
- Modify: `src/nokia_docs/server.py`
- Test: `tests/test_search.py`
- Test: `tests/test_server_errors.py`
- Test: `tests/test_server_instructions.py`

- [ ] **Step 1: Write failing search-layer tests**

Add these tests to `tests/test_search.py`. If `_build_db` already exists, reuse
it and insert the rows shown in the test.

```python
def test_get_page_sections_returns_bounded_window_around_doc():
    conn = _build_db(
        [
            {
                "id": i,
                "product_line": "sros",
                "release": "26.3",
                "book": "md-cli-command-reference",
                "section_path": f"configure service section {i}",
                "section_title": f"Section {i}",
                "heading": f"Section {i}",
                "body": f"Body {i}",
                "rel_path": "sros/md-cli-command-reference/service.html",
            }
            for i in range(1, 8)
        ]
    )

    result = get_page_sections(4, conn, max_sections=3)

    assert result["total_sections"] == 7
    assert result["returned_sections"] == 3
    assert result["truncated"] is True
    assert result["window_start"] == 3
    assert result["window_end"] == 5
    assert [section["doc_id"] for section in result["sections"]] == [3, 4, 5]


def test_get_page_sections_zero_cap_returns_all_sections():
    conn = _build_db(
        [
            {
                "id": i,
                "product_line": "sros",
                "release": "26.3",
                "book": "md-cli-command-reference",
                "section_path": f"configure service section {i}",
                "section_title": f"Section {i}",
                "heading": f"Section {i}",
                "body": f"Body {i}",
                "rel_path": "sros/md-cli-command-reference/service.html",
            }
            for i in range(1, 8)
        ]
    )

    result = get_page_sections(4, conn, max_sections=0)

    assert result["total_sections"] == 7
    assert result["returned_sections"] == 7
    assert result["truncated"] is False
    assert [section["doc_id"] for section in result["sections"]] == list(range(1, 8))


def test_get_page_sections_filters_by_query_before_windowing():
    conn = _build_db(
        [
            {
                "id": 1,
                "product_line": "sros",
                "release": "26.3",
                "book": "md-cli-command-reference",
                "section_path": "configure service ospf",
                "section_title": "OSPF service",
                "heading": "OSPF service",
                "body": "OSPF body",
                "rel_path": "sros/md-cli-command-reference/service.html",
            },
            {
                "id": 2,
                "product_line": "sros",
                "release": "26.3",
                "book": "md-cli-command-reference",
                "section_path": "configure service bgp",
                "section_title": "BGP service",
                "heading": "BGP service",
                "body": "BGP body",
                "rel_path": "sros/md-cli-command-reference/service.html",
            },
            {
                "id": 3,
                "product_line": "sros",
                "release": "26.3",
                "book": "md-cli-command-reference",
                "section_path": "configure router ospf area",
                "section_title": "OSPF area",
                "heading": "OSPF area",
                "body": "OSPF area body",
                "rel_path": "sros/md-cli-command-reference/service.html",
            },
        ]
    )

    result = get_page_sections(2, conn, max_sections=10, query="ospf")

    assert result["total_sections"] == 2
    assert result["returned_sections"] == 2
    assert [section["doc_id"] for section in result["sections"]] == [1, 3]
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search.py::test_get_page_sections_returns_bounded_window_around_doc tests/test_search.py::test_get_page_sections_zero_cap_returns_all_sections tests/test_search.py::test_get_page_sections_filters_by_query_before_windowing -q
```

Expected result: failures showing that `get_page_sections` does not accept
`max_sections` or `query`, or does not return the new metadata fields.

- [ ] **Step 3: Implement bounded search-layer retrieval**

In `src/nokia_docs/search.py`, change `get_page_sections` to this signature:

```python
def get_page_sections(
    doc_id: int,
    conn: sqlite3.Connection,
    *,
    max_sections: int = 200,
    around_doc_id: bool = True,
    query: str | None = None,
) -> dict[str, object] | None:
```

Add this helper near the function:

```python
def _section_matches_query(section: dict[str, object], query: str) -> bool:
    terms = [term.casefold() for term in re.findall(r"[A-Za-z0-9_.-]+", query)]
    if not terms:
        return True
    haystack = " ".join(
        str(section.get(field) or "")
        for field in ("section_path", "section_title", "heading")
    ).casefold()
    return all(term in haystack for term in terms)
```

Inside `get_page_sections`, keep the existing page lookup and section list
construction, then apply this logic before returning:

```python
    if query:
        sections = [
            section for section in sections if _section_matches_query(section, query)
        ]

    total_sections = len(sections)
    normalized_max = max(0, max_sections)

    if normalized_max and total_sections > normalized_max:
        selected_index = next(
            (
                index
                for index, section in enumerate(sections)
                if section.get("doc_id") == doc_id
            ),
            0,
        )
        if around_doc_id:
            half_window = normalized_max // 2
            start = max(0, selected_index - half_window)
            end = min(total_sections, start + normalized_max)
            start = max(0, end - normalized_max)
        else:
            start = 0
            end = normalized_max
        returned_sections = sections[start:end]
    else:
        start = 0
        end = total_sections
        returned_sections = sections

    return {
        "doc_id": doc_id,
        "page_title": page_title,
        "rel_path": rel_path,
        "total_sections": total_sections,
        "returned_sections": len(returned_sections),
        "truncated": len(returned_sections) < total_sections,
        "window_start": start + 1 if returned_sections else 0,
        "window_end": end,
        "sections": returned_sections,
    }
```

Use the variable names already present in the existing function for
`page_title`, `rel_path`, and `sections`.

- [ ] **Step 4: Expose the new MCP arguments**

In `src/nokia_docs/server.py`, update the `get_page_sections` tool wrapper to:

```python
@mcp.tool()
def get_page_sections(
    doc_id: int,
    max_sections: int = 200,
    around_doc_id: bool = True,
    query: str | None = None,
) -> dict[str, Any] | None:
    """List sections on the same page as a document.

    Results are capped by default to avoid returning thousands of command
    reference siblings. Use max_sections=0 only when the full page map is
    needed. Provide query to filter section titles and paths before windowing.
    """
    conn = _connect()
    try:
        return search.get_page_sections(
            doc_id,
            conn,
            max_sections=max_sections,
            around_doc_id=around_doc_id,
            query=query,
        )
    finally:
        conn.close()
```

Keep any existing startup-error handling pattern used by neighboring tools.

- [ ] **Step 5: Add server-level regression tests**

Add this test to `tests/test_server_errors.py`:

```python
def test_get_page_sections_closes_connection_on_error(monkeypatch):
    closed = False

    class FakeConnection:
        def close(self):
            nonlocal closed
            closed = True

    def fake_connect():
        return FakeConnection()

    def fake_get_page_sections(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_connect", fake_connect)
    monkeypatch.setattr(server.search, "get_page_sections", fake_get_page_sections)

    with pytest.raises(RuntimeError, match="boom"):
        server.get_page_sections(1, max_sections=10, query="ospf")

    assert closed is True
```

Add these assertions to `tests/test_server_instructions.py`:

```python
def test_mcp_instructions_include_bounded_page_section_guidance():
    instructions = server.mcp.instructions

    for term in [
        "bounded get_page_sections",
        "max_sections=0",
        "full page map",
    ]:
        assert term in instructions
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search.py::test_get_page_sections_returns_bounded_window_around_doc tests/test_search.py::test_get_page_sections_zero_cap_returns_all_sections tests/test_search.py::test_get_page_sections_filters_by_query_before_windowing tests/test_server_errors.py::test_get_page_sections_closes_connection_on_error tests/test_server_instructions.py::test_mcp_instructions_include_bounded_page_section_guidance -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add src/nokia_docs/search.py src/nokia_docs/server.py tests/test_search.py tests/test_server_errors.py tests/test_server_instructions.py
git commit -m "Add bounded page section retrieval"
```

Expected result: commit created.

---

### Task 2: Compact `get_document` Retrieval

**Files:**
- Modify: `src/nokia_docs/search.py`
- Modify: `src/nokia_docs/server.py`
- Test: `tests/test_search.py`
- Test: `tests/test_server_errors.py`
- Test: `tests/test_server_instructions.py`

- [ ] **Step 1: Write failing compact document tests**

Add these tests to `tests/test_search.py`:

```python
def test_get_document_caps_body_with_truncation_metadata():
    long_body = "A" * 300
    conn = _build_db(
        [
            {
                "id": 1,
                "product_line": "sros",
                "release": "26.3",
                "book": "configuration",
                "section_path": "configure router",
                "section_title": "Router",
                "heading": "Router",
                "body": long_body,
                "rel_path": "sros/configuration/router.html",
            }
        ]
    )

    document = get_document(1, conn, max_chars=80)

    assert document is not None
    assert document.body == "A" * 80
    assert document.body_chars == 300
    assert document.returned_chars == 80
    assert document.body_truncated is True
    assert document.excerpt_query is None


def test_get_document_query_excerpt_centers_first_match():
    body = "prefix " + ("A" * 120) + " boundary clock " + ("B" * 120)
    conn = _build_db(
        [
            {
                "id": 1,
                "product_line": "sros",
                "release": "26.3",
                "book": "configuration",
                "section_path": "ptp boundary-clock",
                "section_title": "PTP boundary clock",
                "heading": "PTP boundary clock",
                "body": body,
                "rel_path": "sros/configuration/ptp.html",
            }
        ]
    )

    document = get_document(1, conn, query="boundary clock", context_chars=20)

    assert document is not None
    assert "boundary clock" in document.body
    assert len(document.body) <= len("boundary clock") + 40
    assert not document.body.startswith("prefix")
    assert document.body_chars == len(body)
    assert document.returned_chars == len(document.body)
    assert document.body_truncated is True
    assert document.excerpt_query == "boundary clock"


def test_get_document_default_returns_full_body():
    body = "full body " * 100
    conn = _build_db(
        [
            {
                "id": 1,
                "product_line": "sros",
                "release": "26.3",
                "book": "configuration",
                "section_path": "configure system",
                "section_title": "System",
                "heading": "System",
                "body": body,
                "rel_path": "sros/configuration/system.html",
            }
        ]
    )

    document = get_document(1, conn)

    assert document is not None
    assert document.body == body
    assert document.body_chars == len(body)
    assert document.returned_chars == len(body)
    assert document.body_truncated is False
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search.py::test_get_document_caps_body_with_truncation_metadata tests/test_search.py::test_get_document_query_excerpt_centers_first_match tests/test_search.py::test_get_document_default_returns_full_body -q
```

Expected result: failures showing missing `max_chars`, `query`, `context_chars`,
or missing metadata fields.

- [ ] **Step 3: Add document metadata fields**

In `src/nokia_docs/search.py`, extend the `Document` dataclass with defaulted
metadata fields after the existing body field:

```python
    body_chars: int = 0
    returned_chars: int = 0
    body_truncated: bool = False
    excerpt_query: str | None = None
```

When constructing an unmodified document, set:

```python
body_chars=len(body),
returned_chars=len(body),
body_truncated=False,
excerpt_query=None,
```

- [ ] **Step 4: Implement excerpt helper**

Add these helpers near `get_document` in `src/nokia_docs/search.py`:

```python
def _query_needles(query: str) -> list[str]:
    quoted = re.findall(r'"([^"]+)"', query)
    if quoted:
        return [phrase for phrase in quoted if phrase.strip()]
    terms = re.findall(r"[A-Za-z0-9_.-]+", query)
    if len(terms) >= 2:
        return [" ".join(terms), *terms]
    return terms


def _compact_body(
    body: str,
    *,
    query: str | None,
    max_chars: int | None,
    context_chars: int,
) -> tuple[str, int, int, bool, str | None]:
    body_chars = len(body)
    if max_chars is not None:
        max_chars = max(1, max_chars)
    context_chars = max(0, context_chars)

    if query:
        body_folded = body.casefold()
        for needle in _query_needles(query):
            index = body_folded.find(needle.casefold())
            if index >= 0:
                start = max(0, index - context_chars)
                end = min(body_chars, index + len(needle) + context_chars)
                excerpt = body[start:end]
                if max_chars is not None and len(excerpt) > max_chars:
                    match_offset = index - start
                    match_start = max(0, match_offset - (max_chars // 2))
                    match_end = min(len(excerpt), match_start + max_chars)
                    match_start = max(0, match_end - max_chars)
                    excerpt = excerpt[match_start:match_end]
                return excerpt, body_chars, len(excerpt), len(excerpt) < body_chars, query

    if max_chars is not None and body_chars > max_chars:
        excerpt = body[:max_chars]
        return excerpt, body_chars, len(excerpt), True, query

    return body, body_chars, body_chars, False, query if query else None
```

- [ ] **Step 5: Wire compact retrieval into `get_document`**

Change the `get_document` signature:

```python
def get_document(
    doc_id: int,
    conn: sqlite3.Connection,
    *,
    include_neighbors: bool = False,
    max_chars: int | None = None,
    query: str | None = None,
    context_chars: int = 1500,
) -> Document | None:
```

After reading the full body from SQLite, call:

```python
    body, body_chars, returned_chars, body_truncated, excerpt_query = _compact_body(
        body,
        query=query,
        max_chars=max_chars,
        context_chars=context_chars,
    )
```

Pass these fields to the `Document` constructor:

```python
        body=body,
        body_chars=body_chars,
        returned_chars=returned_chars,
        body_truncated=body_truncated,
        excerpt_query=excerpt_query,
```

Do not apply compacting to neighbor metadata; neighbors should remain IDs,
headings, section paths, and relation metadata.

- [ ] **Step 6: Expose compact retrieval through MCP**

In `src/nokia_docs/server.py`, update the tool signature and return body:

```python
@mcp.tool()
def get_document(
    doc_id: int,
    include_neighbors: bool = False,
    max_chars: int | None = None,
    query: str | None = None,
    context_chars: int = 1500,
) -> dict[str, Any] | None:
    """Fetch a document body by ID.

    By default this returns the full body. During navigation, provide query
    and max_chars to return a compact excerpt with truncation metadata. Fetch
    the full body before using a document as final evidence when the excerpt is
    not enough.
    """
    conn = _connect()
    try:
        doc = search.get_document(
            doc_id,
            conn,
            include_neighbors=include_neighbors,
            max_chars=max_chars,
            query=query,
            context_chars=context_chars,
        )
        return asdict(doc) if doc else None
    finally:
        conn.close()
```

Use the existing `asdict` import or the existing conversion helper already in
`server.py`.

- [ ] **Step 7: Add server and instruction tests**

Add this test to `tests/test_server_errors.py`:

```python
def test_get_document_closes_connection_on_compact_error(monkeypatch):
    closed = False

    class FakeConnection:
        def close(self):
            nonlocal closed
            closed = True

    def fake_connect():
        return FakeConnection()

    def fake_get_document(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_connect", fake_connect)
    monkeypatch.setattr(server.search, "get_document", fake_get_document)

    with pytest.raises(RuntimeError, match="boom"):
        server.get_document(1, max_chars=100, query="boundary clock")

    assert closed is True
```

Add this test to `tests/test_server_instructions.py`:

```python
def test_mcp_instructions_include_compact_document_guidance():
    instructions = server.mcp.instructions

    for term in [
        "get_document(query=",
        "max_chars",
        "full body",
        "final evidence",
    ]:
        assert term in instructions
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_search.py::test_get_document_caps_body_with_truncation_metadata tests/test_search.py::test_get_document_query_excerpt_centers_first_match tests/test_search.py::test_get_document_default_returns_full_body tests/test_server_errors.py::test_get_document_closes_connection_on_compact_error tests/test_server_instructions.py::test_mcp_instructions_include_compact_document_guidance -q
```

Expected result: all selected tests pass.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git add src/nokia_docs/search.py src/nokia_docs/server.py tests/test_search.py tests/test_server_errors.py tests/test_server_instructions.py
git commit -m "Add compact document retrieval"
```

Expected result: commit created.

---

### Task 3: Compact Standards Summary Tool

**Files:**
- Modify: `src/nokia_docs/standards.py`
- Modify: `src/nokia_docs/server.py`
- Test: `tests/test_standards.py`
- Test: `tests/test_server_errors.py`
- Test: `tests/test_server_instructions.py`

- [ ] **Step 1: Write failing standards summary tests**

Add this test to `tests/test_standards.py`:

```python
def test_summarize_standard_support_groups_records_compactly(tmp_path):
    sros_workbook = _save_workbook(
        tmp_path / "sros.xlsx",
        "SR OS 26.3.R1 Standards",
        [
            ["Group Title", "7250 IXR Standards"],
            ["Bidirectional Forwarding Detection", "RFC 5880, Bidirectional Forwarding Detection"],
            ["BFD Services", "RFC 5880, Bidirectional Forwarding Detection for services"],
        ],
    )
    srlinux_workbook = _save_workbook(
        tmp_path / "srlinux.xlsx",
        "SR Linux 26.3.1 Standards",
        [
            ["Group Title", "SR Linux Standards"],
            ["Bidirectional Forwarding Detection", "RFC 5880, Bidirectional Forwarding Detection"],
        ],
    )
    db_path = tmp_path / "nokia_docs.db"
    index_standards(db_path, [sros_workbook, srlinux_workbook])

    conn = sqlite3.connect(db_path)
    try:
        summaries = summarize_standard_support(conn, query="RFC 5880", top_k=10)
    finally:
        conn.close()

    sros_summary = next(
        item
        for item in summaries
        if item["product_line"] == "sros-standards" and item["platform"] == "7250 IXR"
    )

    assert len(summaries) == 2
    assert sros_summary["standard_ref"] == "RFC 5880"
    assert sros_summary["standard_title"] == "Bidirectional Forwarding Detection"
    assert sros_summary["release"] == "26.3.R1"
    assert sros_summary["support_status"] == "supported"
    assert sros_summary["num_records"] == 2
    assert sros_summary["source_rows"] == [2, 3]
    assert len(sros_summary["representative_text"]) <= 160
```

Update the import block in `tests/test_standards.py` to include
`summarize_standard_support`.

- [ ] **Step 2: Run the focused standards test and confirm it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standards.py::test_summarize_standard_support_groups_records_compactly -q
```

Expected result: import failure for `summarize_standard_support`.

- [ ] **Step 3: Implement grouped standards summaries**

Add this function to `src/nokia_docs/standards.py`:

```python
def summarize_standard_support(
    conn: sqlite3.Connection,
    *,
    query: str,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    top_k: int = 50,
) -> list[dict[str, object]]:
    records = search_standards(
        conn,
        query=query,
        product_line=product_line,
        platform=platform,
        release=release,
        top_k=min(max(top_k, 1), 100),
    )
    grouped: dict[tuple[str, str, str, str, str], dict[str, object]] = {}

    for record in records:
        standard_key = record.standard_ref or record.standard_text
        key = (
            standard_key,
            record.product_line or "",
            record.release or "",
            record.platform or "",
            record.support_status or "",
        )
        item = grouped.setdefault(
            key,
            {
                "standard_ref": record.standard_ref,
                "standard_title": record.standard_title,
                "product_line": record.product_line,
                "release": record.release,
                "platform": record.platform,
                "support_status": record.support_status,
                "num_records": 0,
                "source_rows": [],
                "representative_text": (record.standard_text or "")[:160],
            },
        )
        item["num_records"] = int(item["num_records"]) + 1
        source_rows = item["source_rows"]
        if isinstance(source_rows, list) and record.row_number not in source_rows:
            source_rows.append(record.row_number)
            source_rows.sort()

    return list(grouped.values())
```

The implementation uses the existing `StandardsHit` fields:
`standard_ref`, `standard_title`, `standard_text`, `product_line`, `platform`,
`release`, `support_status`, and `row_number`.

- [ ] **Step 4: Expose the MCP tool**

Add this tool to `src/nokia_docs/server.py` near `search_standards`:

```python
@mcp.tool()
def summarize_standard_support(
    query: str,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """Return compact grouped standards support summaries.

    Use this for reconnaissance and comparison. Use search_standards for exact
    row-level standards evidence.
    """
    conn = _connect()
    try:
        return standards.summarize_standard_support(
            conn,
            query=query,
            product_line=product_line,
            platform=platform,
            release=release,
            top_k=top_k,
        )
    finally:
        conn.close()
```

- [ ] **Step 5: Add server tests**

Add this test to `tests/test_server_errors.py`:

```python
def test_summarize_standard_support_closes_connection_on_error(monkeypatch):
    closed = False

    class FakeConnection:
        def close(self):
            nonlocal closed
            closed = True

    def fake_connect():
        return FakeConnection()

    def fake_summary(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_connect", fake_connect)
    monkeypatch.setattr(server.standards, "summarize_standard_support", fake_summary)

    with pytest.raises(RuntimeError, match="boom"):
        server.summarize_standard_support("RFC 5880")

    assert closed is True
```

Add this test to `tests/test_server_instructions.py`:

```python
def test_mcp_instructions_include_standards_summary_guidance():
    instructions = server.mcp.instructions

    for term in [
        "summarize_standard_support",
        "compact standards",
        "search_standards",
        "exact standards evidence",
    ]:
        assert term in instructions
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standards.py::test_summarize_standard_support_groups_records_compactly tests/test_server_errors.py::test_summarize_standard_support_closes_connection_on_error tests/test_server_instructions.py::test_mcp_instructions_include_standards_summary_guidance -q
```

Expected result: all selected tests pass.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
git add src/nokia_docs/standards.py src/nokia_docs/server.py tests/test_standards.py tests/test_server_errors.py tests/test_server_instructions.py
git commit -m "Add compact standards summaries"
```

Expected result: commit created.

---

### Task 4: SOC Workbook Classifier Script

**Files:**
- Create: `C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py`
- Modify: `C:\Users\vikharev\.agents\skills\nokia-soc\SKILL.md`

- [ ] **Step 1: Create classifier script**

Create `C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py`
with this content:

```python
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook


ROUTE_PATTERNS = {
    "standards": [
        r"\bRFC\s*\d+",
        r"\bITU-?T\b",
        r"\bIEEE\b",
        r"\bMEF\b",
        r"\b3GPP\b",
        r"\bIETF\b",
        r"\bG\.\d+",
        r"\bY\.\d+",
    ],
    "hardware": [
        r"\bpower\b",
        r"\bPSU\b",
        r"\bfan\b",
        r"\bairflow\b",
        r"\bport\b",
        r"\boptic",
        r"\bMDA\b",
        r"\bFRU\b",
        r"\btemperature\b",
        r"\benvironmental\b",
        r"\bredundan",
    ],
    "scale": [
        r"\bscale\b",
        r"\bscaling\b",
        r"\bcapacity\b",
        r"\bmaximum\b",
        r"\blimit\b",
        r"\bthroughput\b",
        r"\bperformance\b",
        r"\b\d+\s*(k|m|g|tbps|gbps|mbps|pps|routes|macs|vlans)\b",
    ],
    "sr_linux_api": [
        r"\bgNMI\b",
        r"\bgNOI\b",
        r"\bOpenConfig\b",
        r"\bJSON-RPC\b",
        r"\bSR Linux\b",
        r"\bYANG\b",
    ],
    "sr_os_config": [
        r"\bMD-CLI\b",
        r"\bclassic CLI\b",
        r"\bconfigure\b",
        r"\bshow\b",
        r"\bdebug\b",
        r"\b7750\b",
        r"\b7250\b",
        r"\bSR OS\b",
    ],
    "management": [
        r"\bNETCONF\b",
        r"\bSNMP\b",
        r"\bRADIUS\b",
        r"\bTACACS",
        r"\bSSH\b",
        r"\bTLS\b",
        r"\bmanagement\b",
        r"\blogging\b",
        r"\btelemetry\b",
    ],
    "certification": [
        r"\bcertif",
        r"\bcompliance\b",
        r"\bRoHS\b",
        r"\bCE\b",
        r"\bNEBS\b",
        r"\bETSI\b",
    ],
    "commercial": [
        r"\bwarranty\b",
        r"\bSLA\b",
        r"\bdelivery\b",
        r"\bsupport contract\b",
        r"\btraining\b",
        r"\bprice\b",
    ],
}

HEADER_HINTS = {
    "requirement": ["requirement", "description", "shall", "specification", "compliance item"],
    "response": ["response", "answer", "compliance", "vendor response"],
}


@dataclass
class ClassifiedRow:
    sheet: str
    row: int
    route: str
    confidence: float
    signals: list[str]
    requirement_text: str
    suggested_queries: list[str]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_header_row(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    best_index = 0
    best_score = -1
    best_columns: dict[str, int] = {}
    for index, row in enumerate(rows[:12]):
        score = 0
        columns: dict[str, int] = {}
        for col_index, value in enumerate(row):
            folded = value.casefold()
            for role, hints in HEADER_HINTS.items():
                if any(hint in folded for hint in hints):
                    score += 1
                    columns.setdefault(role, col_index)
        if score > best_score:
            best_index = index
            best_score = score
            best_columns = columns
    return best_index, best_columns


def _score_routes(text: str) -> tuple[str, float, list[str]]:
    hits: dict[str, list[str]] = {}
    for route, patterns in ROUTE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                hits.setdefault(route, []).append(pattern)
    if not hits:
        return "general", 0.25, []
    ordered = sorted(hits.items(), key=lambda item: (-len(item[1]), item[0]))
    route, signals = ordered[0]
    confidence = min(0.95, 0.45 + (0.15 * len(signals)))
    return route, confidence, signals


def _extract_standard_refs(text: str) -> list[str]:
    refs = re.findall(
        r"\b(?:RFC\s*\d+|IEEE\s+[0-9A-Za-z.\-]+|ITU-?T\s+[A-Z]\.\d+|G\.\d+|Y\.\d+|MEF\s+\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    return sorted({re.sub(r"\s+", " ", ref).strip() for ref in refs})


def _suggest_queries(route: str, text: str, platform: str, release: str) -> list[str]:
    prefix = " ".join(part for part in [platform, release] if part).strip()
    standard_refs = _extract_standard_refs(text)
    if route == "standards" and standard_refs:
        return [f'search_standards query="{ref}" platform="{platform}" release="{release}"'.strip() for ref in standard_refs]
    if route == "hardware":
        return [f"{prefix} chassis installation hardware guide specifications orderable parts {text[:120]}".strip()]
    if route == "scale":
        return [
            f"{prefix} scale scaling capacity maximum limit {text[:120]}".strip(),
            f"{prefix} release notes new-features enhancements resolved-issues known-issues {text[:120]}".strip(),
        ]
    if route in {"sr_os_config", "sr_linux_api", "management"}:
        return [f"{prefix} {text[:160]}".strip()]
    return [text[:180].strip()]


def classify_workbook(path: Path, platform: str = "", release: str = "") -> list[ClassifiedRow]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    results: list[ClassifiedRow] = []
    for sheet in workbook.worksheets:
        rows = [[_cell_text(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        if not rows:
            continue
        header_index, columns = _find_header_row(rows)
        requirement_column = columns.get("requirement", 0)
        for row_offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            if requirement_column >= len(row):
                continue
            requirement_text = row[requirement_column].strip()
            if not requirement_text:
                continue
            route, confidence, signals = _score_routes(requirement_text)
            results.append(
                ClassifiedRow(
                    sheet=sheet.title,
                    row=row_offset,
                    route=route,
                    confidence=round(confidence, 2),
                    signals=signals,
                    requirement_text=requirement_text,
                    suggested_queries=_suggest_queries(route, requirement_text, platform, release),
                )
            )
    return results


def _write_tsv(rows: Iterable[ClassifiedRow]) -> None:
    print("sheet\trow\troute\tconfidence\tsignals\trequirement_text\tsuggested_queries")
    for item in rows:
        print(
            "\t".join(
                [
                    item.sheet,
                    str(item.row),
                    item.route,
                    f"{item.confidence:.2f}",
                    ",".join(item.signals),
                    item.requirement_text.replace("\t", " "),
                    " | ".join(item.suggested_queries).replace("\t", " "),
                ]
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify Nokia SOC workbook rows into evidence routes.")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--platform", default="")
    parser.add_argument("--release", default="")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    rows = classify_workbook(args.workbook, platform=args.platform, release=args.release)
    if args.json_output:
        print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
    else:
        _write_tsv(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Validate the classifier against a generated workbook**

Run this PowerShell command from any directory:

```powershell
@'
import os
from pathlib import Path
from openpyxl import Workbook

path = Path(os.environ["TEMP"]) / "nokia-soc-classifier-sample.xlsx"
wb = Workbook()
ws = wb.active
ws.title = "Requirements"
ws.append(["ID", "Requirement", "Vendor Response"])
ws.append(["1", "The platform shall support RFC 5880 for BFD.", ""])
ws.append(["2", "The chassis shall provide redundant power supplies and fan trays.", ""])
ws.append(["3", "The system shall support at least 1M BGP routes scale.", ""])
ws.append(["4", "The system shall support NETCONF and telemetry management.", ""])
wb.save(path)
print(path)
'@ | .\.venv\Scripts\python.exe -

$sample = Join-Path $env:TEMP 'nokia-soc-classifier-sample.xlsx'
python C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py $sample --platform "7750 SR" --release "26.3" --json
```

Expected result: JSON contains four rows with routes `standards`, `hardware`,
`scale`, and `management`.

- [ ] **Step 3: Update `nokia-soc` skill workflow**

In `C:\Users\vikharev\.agents\skills\nokia-soc\SKILL.md`, add this section
after the initial workbook inspection instructions:

````markdown
### Workbook Route Planning

For large XLSX workbooks, run the local route classifier before row-by-row
evidence work:

```powershell
python C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py "<workbook.xlsx>" --platform "<target platform>" --release "<target release>" --json
```

Use the classifier output to batch rows by route and choose the first evidence
source. The classifier is advisory only: it must not decide compliance, must
not replace MCP evidence, and must not be copied into customer-facing answers.

- `standards`: start with `summarize_standard_support`, then use
  `search_standards` for exact evidence.
- `hardware`: search chassis installation guides, hardware guides,
  specifications, and orderable parts.
- `scale`: search product docs for exact limits, then release notes
  `new-features`, `enhancements`, `resolved-issues`, and `known-issues`.
- `sr_os_config`, `sr_linux_api`, `management`: search exact feature and
  command/API terms, then fetch full evidence.
- `commercial`, `certification`, `general`: use the relevant local reference
  or ask for source material when no Nokia evidence source is available.
````

If the skill already has an equivalent section, merge the bullets and keep the
route names above exactly.

- [ ] **Step 4: Add compact retrieval discipline to the skill**

In `C:\Users\vikharev\.agents\skills\nokia-soc\SKILL.md`, add this paragraph
inside the Nokia Docs MCP discipline section:

```markdown
Use compact MCP calls while navigating: `get_document(query=..., max_chars=...)`
for excerpts and bounded `get_page_sections` for page maps. Use
`get_page_sections(max_sections=0)` only when the bounded result shows
`truncated: true` and the full page map is required. Compact excerpts,
standards summaries, and non-`strict` search hits are leads only; fetch exact
`search_standards` rows or full `get_document` bodies before writing final SOC
evidence.
```

- [ ] **Step 5: Re-run classifier validation**

Run:

```powershell
$sample = Join-Path $env:TEMP 'nokia-soc-classifier-sample.xlsx'
python C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py $sample --platform "7750 SR" --release "26.3" --json
```

Expected result: JSON still contains routes `standards`, `hardware`, `scale`,
and `management`.

No git commit is created for this task because
`C:\Users\vikharev\.agents\skills\nokia-soc` is outside the
`nokia-docs-search` repository.

---

### Task 5: MCP Instruction Polish And Full Verification

**Files:**
- Modify: `src/nokia_docs/server.py`
- Test: `tests/test_server_instructions.py`

- [ ] **Step 1: Update MCP instructions**

In `src/nokia_docs/server.py`, update the `FastMCP(instructions=...)` text so
it includes these exact phrases:

```text
summarize_standard_support
compact standards
search_standards
exact standards evidence
get_document(query=
max_chars
full body
final evidence
bounded get_page_sections
max_sections=0
full page map
```

Keep the existing guidance for `match_mode`, hardware/chassis routing, release
notes, and standards routing.

- [ ] **Step 2: Run instruction tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_server_instructions.py -q
```

Expected result: all instruction tests pass.

- [ ] **Step 3: Run repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected result: all repository tests pass.

- [ ] **Step 4: Run ruff**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

Expected result: exit code 0 with no lint errors.

- [ ] **Step 5: Validate the real database**

Run:

```powershell
.\.venv\Scripts\nokia-docs.exe validate-db --db .\nokia_docs.db
```

Expected result: database validation exits with code 0.

- [ ] **Step 6: Run real DB smoke checks**

Run:

```powershell
@'
from pathlib import Path
import sqlite3

from nokia_docs.search import get_document, get_page_sections, search_docs
from nokia_docs.standards import summarize_standard_support

conn = sqlite3.connect(Path("nokia_docs.db"))
hits = search_docs(
    conn,
    "7250 IXR-e2 power supply fan redundancy chassis installation specifications",
    top_k=5,
)
assert hits, "expected documentation hits"
sections = get_page_sections(hits[0].doc_id, conn)
assert sections is not None
assert sections["returned_sections"] <= 200
assert "total_sections" in sections
doc = get_document(hits[0].doc_id, conn, query="power fan redundancy", max_chars=500)
assert doc is not None
assert doc.returned_chars <= 500
summaries = summarize_standard_support(conn, query="RFC 5880", top_k=20)
assert summaries, "expected standards summary hits"
print(
    {
        "hit_doc_id": hits[0].doc_id,
        "match_mode": hits[0].match_mode,
        "sections_returned": sections["returned_sections"],
        "sections_total": sections["total_sections"],
        "doc_returned_chars": doc.returned_chars,
        "standards_summaries": len(summaries),
    }
)
conn.close()
'@ | .\.venv\Scripts\python.exe -
```

Expected result: the command prints a dictionary and exits with code 0.

- [ ] **Step 7: Commit final repository changes**

Run:

```powershell
git status --short
git add src/nokia_docs/search.py src/nokia_docs/server.py src/nokia_docs/standards.py tests/test_search.py tests/test_standards.py tests/test_server_errors.py tests/test_server_instructions.py
git commit -m "Optimize MCP retrieval token usage"
```

Expected result: commit created for repository code changes.

- [ ] **Step 8: Record final implementation status**

Run:

```powershell
git status --short --branch
```

Expected result: branch is ahead of origin and has no uncommitted repository
changes. Mention the two changed skill files separately:

```text
C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py
C:\Users\vikharev\.agents\skills\nokia-soc\SKILL.md
```

---

## Self-Review

- Spec coverage: bounded page sections, compact document excerpts, compact
  standards summaries, SOC classifier, MCP instructions, skill instructions,
  and verification are covered by tasks.
- Type consistency: `get_page_sections`, `get_document`, and
  `summarize_standard_support` signatures match across search/standards,
  server wrappers, and tests.
- Token discipline: defaults reduce accidental large outputs, and full evidence
  remains available through explicit calls.
- Speed discipline: the plan avoids embeddings, schema rebuilds, and extra FTS
  passes; the classifier reduces repeated route discovery before MCP calls.
- Execution handoff: implement Task 1 through Task 5 in order, committing after
  each repository task that changes code.
