# Smart Documentation Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `nokia-docs` return useful results for long tender-style documentation queries while preserving exact short-query behavior.

**Architecture:** Add a query-planning layer in `nokia_docs.search` that tries strict FTS first, then relaxed, variant, and soft fallback candidates. Add page navigation through `get_page_sections`, expose it through the MCP server, and include `match_mode` in `search_docs` results so clients can tell exact matches from recall-oriented fallbacks.

**Tech Stack:** Python 3.11+, SQLite FTS5, FastMCP, pytest, ruff.

---

## File Structure

- Modify `src/nokia_docs/search.py`: add query planning helpers, `match_mode` on `Hit`, fallback search execution, page-section retrieval, and richer neighbor metadata.
- Modify `src/nokia_docs/server.py`: expose `match_mode` in `search_docs`, add MCP tool `get_page_sections`, and update instructions.
- Modify `tests/test_search.py`: add planner, fallback, page-section, and neighbor tests using small SQLite fixtures.
- Modify `tests/test_server_errors.py`: add startup-error coverage for `get_page_sections`.
- Optional final verification only: run real DB smoke checks against `C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db`.

This change does not alter the SQLite schema and does not rebuild the documentation corpus.

---

### Task 1: Query Planner Helpers

**Files:**
- Modify: `src/nokia_docs/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write failing planner tests**

Update the existing import in `tests/test_search.py`:

```python
from nokia_docs.search import _sanitize_query, plan_search_queries, search_docs
```

Append these tests to `tests/test_search.py`:

```python

def test_plan_search_queries_starts_with_strict_candidate():
    candidates = plan_search_queries("boundary clock")

    assert candidates[0].match_mode == "strict"
    assert candidates[0].fts_query == '"boundary clock" OR ("boundary"* AND "clock"*)'
    assert candidates[0].important_terms == ["boundary", "clock"]


def test_plan_search_queries_relaxes_product_and_class_noise():
    candidates = plan_search_queries("PTP boundary clock G.8273.2 class C class D 7250 IXR-e2")

    relaxed = [c for c in candidates if c.match_mode == "relaxed"]
    assert relaxed
    assert relaxed[0].important_terms == ["PTP", "boundary", "clock", "G.8273.2"]
    assert "7250" not in relaxed[0].fts_query
    assert "IXR-e2" not in relaxed[0].fts_query


def test_plan_search_queries_adds_spelling_and_punctuation_variants():
    candidates = plan_search_queries("BGP-AD auto-discovery VPLS signalling")

    variant_queries = [c.fts_query for c in candidates if c.match_mode == "variant"]
    joined = "\n".join(variant_queries)
    assert '"signaling"*' in joined
    assert '"BGP"*' in joined
    assert '"AD"*' in joined
    assert '"auto"*' in joined
    assert '"discovery"*' in joined


def test_plan_search_queries_ends_with_soft_candidate_for_long_query():
    candidates = plan_search_queries("hierarchical QoS scheduler egress aggregate rate")

    assert candidates[-1].match_mode == "soft"
    assert " OR " in candidates[-1].fts_query
    assert candidates[-1].important_terms == [
        "hierarchical",
        "QoS",
        "scheduler",
        "egress",
        "aggregate",
        "rate",
    ]
```

- [ ] **Step 2: Run planner tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_plan_search_queries_starts_with_strict_candidate tests/test_search.py::test_plan_search_queries_relaxes_product_and_class_noise tests/test_search.py::test_plan_search_queries_adds_spelling_and_punctuation_variants tests/test_search.py::test_plan_search_queries_ends_with_soft_candidate_for_long_query -q
```

Expected: FAIL with import error for `plan_search_queries`.

- [ ] **Step 3: Add planner dataclass and helpers**

In `src/nokia_docs/search.py`, add the dataclass near `Hit`:

```python
@dataclass(frozen=True)
class SearchCandidate:
    match_mode: str
    fts_query: str
    important_terms: list[str]
```

Add these constants and helpers below `_resolve_product`:

```python
_NOISE_TERMS = {
    "7250", "7750", "7705", "7210", "7450", "7950",
    "IXR", "IXR-e", "IXR-e2", "SR", "SR-1", "SR-2", "VSR",
}

_MEANINGFUL_SHORT_TERMS = {"AD", "AS", "IP", "L2", "L3", "PTP", "BGP", "QoS"}

_VARIANT_REPLACEMENTS = {
    "signalling": ["signaling"],
    "signaling": ["signalling"],
    "BGP-AD": ["BGP AD"],
    "auto-discovery": ["auto discovery"],
    "AS path": ["AS-path"],
    "AS-path": ["AS path"],
    "QoS": ["QOS"],
    "QOS": ["QoS"],
}


def _is_explicit_fts(query: str) -> bool:
    return bool(re.search(r"\b(AND|OR|NOT|NEAR)\b", query)) or any(
        op in query for op in (" + ", "*")
    )


def _query_words(query: str) -> list[str]:
    bare = re.sub(r'"[^"]*"', " ", query.replace('"', " "))
    return [w for w in re.split(r"\s+", bare.strip()) if w]


def _quote_prefix(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"*'


def _and_query(terms: list[str]) -> str:
    return " AND ".join(_quote_prefix(term) for term in terms)


def _or_query(terms: list[str]) -> str:
    return " OR ".join(_quote_prefix(term) for term in terms)


def _strict_query(query: str, terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return _quote_prefix(terms[0])
    phrase = " ".join(terms).replace('"', '""')
    return f'"{phrase}" OR ({_and_query(terms)})'


def _is_release_like(term: str) -> bool:
    return bool(re.fullmatch(r"\d{2}\.\d+(?:\.R\d+)?", term))


def _relaxed_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    skip_next_class_letter = False
    for term in terms:
        normalized = term.strip(",;()[]")
        if skip_next_class_letter and re.fullmatch(r"[A-Za-z]", normalized):
            skip_next_class_letter = False
            continue
        if normalized.lower() == "class":
            skip_next_class_letter = True
            continue
        skip_next_class_letter = False
        if normalized in _NOISE_TERMS or _is_release_like(normalized):
            continue
        if len(normalized) <= 2 and normalized not in _MEANINGFUL_SHORT_TERMS:
            continue
        result.append(normalized)
    return result


def _variant_term_sets(query: str, terms: list[str]) -> list[list[str]]:
    variants: list[list[str]] = []
    for source, replacements in _VARIANT_REPLACEMENTS.items():
        if source in query:
            for replacement in replacements:
                variant_query = query.replace(source, replacement)
                variant_terms = _relaxed_terms(_query_words(variant_query))
                if variant_terms and variant_terms != terms and variant_terms not in variants:
                    variants.append(variant_terms)
    for term in terms:
        if "-" in term:
            expanded = [part for part in term.split("-") if part]
            candidate = [expanded_part for t in terms for expanded_part in (t.split("-") if t == term else [t])]
            if expanded and candidate not in variants:
                variants.append(candidate)
    return variants
```

Add the public planner:

```python
def plan_search_queries(query: str) -> list[SearchCandidate]:
    """Build ordered FTS candidates for strict and fallback documentation search."""
    query = query.strip()
    if not query:
        return []
    if _is_explicit_fts(query) or (query.startswith('"') and query.endswith('"')):
        return [SearchCandidate("strict", query, _query_words(query))]

    terms = _query_words(query)
    candidates: list[SearchCandidate] = []
    strict = _strict_query(query, terms)
    if strict:
        candidates.append(SearchCandidate("strict", strict, terms))

    relaxed_terms = _relaxed_terms(terms)
    if relaxed_terms and relaxed_terms != terms:
        candidates.append(SearchCandidate("relaxed", _strict_query(" ".join(relaxed_terms), relaxed_terms), relaxed_terms))

    for variant_terms in _variant_term_sets(query, relaxed_terms or terms):
        candidates.append(SearchCandidate("variant", _strict_query(" ".join(variant_terms), variant_terms), variant_terms))

    soft_terms = relaxed_terms or terms
    if len(soft_terms) > 1:
        candidates.append(SearchCandidate("soft", _or_query(soft_terms), soft_terms))

    unique: list[SearchCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.match_mode, candidate.fts_query)
        if key not in seen and candidate.fts_query:
            unique.append(candidate)
            seen.add(key)
    return unique
```

- [ ] **Step 4: Keep `_sanitize_query` backward compatible**

Replace the body of `_sanitize_query` after the empty-query check with:

```python
    candidates = plan_search_queries(query)
    return candidates[0].fts_query if candidates else ""
```

This keeps existing tests that call `_sanitize_query` working while moving new behavior into `plan_search_queries`.

- [ ] **Step 5: Run planner tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_plan_search_queries_starts_with_strict_candidate tests/test_search.py::test_plan_search_queries_relaxes_product_and_class_noise tests/test_search.py::test_plan_search_queries_adds_spelling_and_punctuation_variants tests/test_search.py::test_plan_search_queries_ends_with_soft_candidate_for_long_query tests/test_search.py::test_sanitize_preserves_prefix_query tests/test_search.py::test_sanitize_preserves_mixed_prefix_query -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/nokia_docs/search.py tests/test_search.py
git commit -m "Add smart search query planner"
```

---

### Task 2: Fallback Execution And Match Mode

**Files:**
- Modify: `src/nokia_docs/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Add fallback fixture and tests**

Replace `_build_db` in `tests/test_search.py` with this richer fixture:

```python
def _build_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = _open_db(db_path, reset=True)
    _insert_chunks(
        conn,
        [
            Chunk(
                product_line="sros-26-3",
                book="mpls",
                rel_path="26-3/books/mpls/rsvp.html",
                page_title="RSVP configuration",
                section_id="rsvp-interface",
                section_title="RSVP interface configuration",
                section_path="MPLS > RSVP > Interface",
                depth=1,
                body="Configure RSVP interfaces and hold-time values.",
            ),
            Chunk(
                product_line="srlinux-26-3",
                book="interfaces",
                rel_path="sr-linux/books/interfaces/interface.html",
                page_title="Interface configuration",
                section_id="ethernet-interface",
                section_title="Ethernet interface",
                section_path="Interfaces > Ethernet",
                depth=1,
                body="Configure ethernet interfaces.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="system-management",
                rel_path="26-3/books/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp-boundary-clock",
                section_title="PTP boundary clock",
                section_path="System management > PTP > Boundary clock",
                depth=2,
                body="PTP boundary clock supports ITU-T G.8273.2 telecom profile behavior.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="system-management",
                rel_path="26-3/books/system/ptp.html",
                page_title="PTP boundary clock",
                section_id="ptp-clock-classes",
                section_title="PTP clock classes",
                section_path="System management > PTP > Clock classes",
                depth=3,
                body="Class C and class D clock behavior is described for timing deployments.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="qos",
                rel_path="26-3/books/qos/schedulers.html",
                page_title="Virtual hierarchical scheduling",
                section_id="virtual-hierarchical-scheduling",
                section_title="Virtual hierarchical scheduling",
                section_path="QoS policies > Scheduler policies > Virtual hierarchical scheduling",
                depth=2,
                body="Hierarchical scheduler policies support egress aggregate rate behavior.",
            ),
            Chunk(
                product_line="sros-26-3",
                book="services",
                rel_path="26-3/books/services/vpls.html",
                page_title="VPLS BGP auto discovery",
                section_id="vpls-bgp-auto-discovery",
                section_title="BGP auto discovery for VPLS",
                section_path="Services > VPLS > BGP auto discovery",
                depth=2,
                body="BGP AD auto discovery VPLS signaling exchanges service membership.",
            ),
        ],
    )
    conn.commit()
    return conn
```

Append these tests:

```python
def test_long_ptp_query_falls_back_to_relaxed(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("PTP boundary clock G.8273.2 class C class D 7250 IXR-e2", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].match_mode in {"relaxed", "soft"}


def test_signalling_query_falls_back_to_variant(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("BGP-AD auto-discovery VPLS signalling", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "BGP auto discovery for VPLS"
    assert hits[0].match_mode in {"variant", "soft"}


def test_qos_query_uses_soft_fallback_when_one_term_is_absent(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs(
            "hierarchical QoS scheduler egress aggregate shaping rate",
            conn,
            top_k=5,
        )
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "Virtual hierarchical scheduling"
    assert hits[0].match_mode == "soft"


def test_short_query_stays_strict(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hits = search_docs("boundary clock", conn, top_k=5)
    finally:
        conn.close()

    assert hits
    assert hits[0].section_title == "PTP boundary clock"
    assert hits[0].match_mode == "strict"
```

- [ ] **Step 2: Run fallback tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_long_ptp_query_falls_back_to_relaxed tests/test_search.py::test_signalling_query_falls_back_to_variant tests/test_search.py::test_qos_query_uses_soft_fallback_when_one_term_is_absent tests/test_search.py::test_short_query_stays_strict -q
```

Expected: FAIL because `Hit` has no `match_mode` and `search_docs` does not use fallback candidates yet.

- [ ] **Step 3: Add match mode to `Hit`**

In `src/nokia_docs/search.py`, add a defaulted field at the end of `Hit`:

```python
    match_mode: str = "strict"
```

- [ ] **Step 4: Extract single-candidate SQL execution**

Add this helper above `search_docs`:

```python
def _run_fts_search(
    conn: sqlite3.Connection,
    fts_query: str,
    product_line: str | None,
    book: str | None,
    top_k: int,
    match_mode: str,
) -> list[Hit]:
    extra_where = ""
    params: list = [fts_query]
    resolved_product = resolve_product(product_line)

    if resolved_product:
        extra_where += " AND d.product_line = ?"
        params.append(resolved_product)
    if book:
        extra_where += " AND d.book = ?"
        params.append(book)

    params.append(top_k)
    sql = f"""
        SELECT
            d.id,
            d.product_line,
            d.book,
            d.page_title,
            d.section_title,
            d.section_path,
            d.rel_path,
            snippet(docs_fts, 3, '[[', ']]', '...', 32) AS snip,
            bm25(docs_fts, {_BM25_WEIGHTS}) AS score
        FROM docs_fts
        JOIN docs d ON docs_fts.rowid = d.id
        WHERE docs_fts MATCH ?
          {extra_where}
        ORDER BY score
        LIMIT ?
    """
    rows = conn.execute(sql, params).fetchall()
    return [
        Hit(
            doc_id=r[0],
            product_line=r[1],
            book=r[2],
            page_title=r[3],
            section_title=r[4],
            section_path=r[5],
            rel_path=r[6],
            snippet=r[7] or "",
            score=-r[8],
            match_mode=match_mode,
        )
        for r in rows
    ]


def _term_present(term: str, text: str) -> bool:
    normalized_term = term.lower().replace("-", " ")
    normalized_text = text.lower().replace("-", " ")
    return normalized_term in normalized_text


def _soft_match_count(hit: Hit, terms: list[str]) -> int:
    haystack = " ".join(
        [
            hit.page_title,
            hit.section_title,
            hit.section_path,
            hit.snippet,
        ]
    )
    return sum(1 for term in terms if _term_present(term, haystack))


def _soft_title_path_count(hit: Hit, terms: list[str]) -> int:
    haystack = " ".join([hit.page_title, hit.section_title, hit.section_path])
    return sum(1 for term in terms if _term_present(term, haystack))


def _rank_soft_hits(hits: list[Hit], terms: list[str]) -> list[Hit]:
    return sorted(
        hits,
        key=lambda hit: (
            -_soft_match_count(hit, terms),
            -_soft_title_path_count(hit, terms),
            -hit.score,
            hit.doc_id,
        ),
    )
```

- [ ] **Step 5: Replace `search_docs` execution loop**

Replace `search_docs` body after `top_k = ...` with:

```python
    candidates = plan_search_queries(query)
    if not candidates:
        return []

    enough_hits = min(top_k, 3)
    fallback_rows: list[Hit] = []
    seen_doc_ids: set[int] = set()

    for candidate in candidates:
        try:
            hits = _run_fts_search(
                conn=conn,
                fts_query=candidate.fts_query,
                product_line=product_line,
                book=book,
                top_k=top_k,
                match_mode=candidate.match_mode,
            )
        except sqlite3.OperationalError:
            if candidate.match_mode != "strict":
                continue
            escaped = '"' + query.replace('"', '""') + '"'
            try:
                hits = _run_fts_search(conn, escaped, product_line, book, top_k, "strict")
            except sqlite3.OperationalError:
                hits = []

        if candidate.match_mode == "soft":
            hits = _rank_soft_hits(hits, candidate.important_terms)

        if candidate.match_mode != "soft" and len(hits) >= enough_hits:
            return hits[:top_k]

        for hit in hits:
            if hit.doc_id not in seen_doc_ids:
                fallback_rows.append(hit)
                seen_doc_ids.add(hit.doc_id)
        if fallback_rows and candidate.match_mode != "strict":
            return fallback_rows[:top_k]

    return fallback_rows[:top_k]
```

- [ ] **Step 6: Run fallback tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_long_ptp_query_falls_back_to_relaxed tests/test_search.py::test_signalling_query_falls_back_to_variant tests/test_search.py::test_qos_query_uses_soft_fallback_when_one_term_is_absent tests/test_search.py::test_short_query_stays_strict tests/test_search.py::test_prefix_query_searches_fts_prefix_terms tests/test_search.py::test_prefix_query_can_be_combined_with_product_filter -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/nokia_docs/search.py tests/test_search.py
git commit -m "Add fallback documentation search"
```

---

### Task 3: Page Sections Search Function

**Files:**
- Modify: `src/nokia_docs/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Add page navigation tests**

Append to `tests/test_search.py`:

```python
def test_get_page_sections_returns_same_page_tree(tmp_path):
    conn = _build_db(tmp_path)
    try:
        seed = search_docs("boundary clock", conn, top_k=1)[0]
        page = get_page_sections(seed.doc_id, conn)
    finally:
        conn.close()

    assert page is not None
    assert page["rel_path"] == "26-3/books/system/ptp.html"
    assert [s["section_title"] for s in page["sections"]] == [
        "PTP boundary clock",
        "PTP clock classes",
    ]
    assert page["sections"][0]["section_id"] == "ptp-boundary-clock"
    assert page["sections"][0]["depth"] == 2


def test_get_page_sections_returns_none_for_unknown_doc_id(tmp_path):
    conn = _build_db(tmp_path)
    try:
        page = get_page_sections(999999, conn)
    finally:
        conn.close()

    assert page is None
```

Update imports at the top:

```python
from nokia_docs.search import _sanitize_query, get_page_sections, plan_search_queries, search_docs
```

- [ ] **Step 2: Run page tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_get_page_sections_returns_same_page_tree tests/test_search.py::test_get_page_sections_returns_none_for_unknown_doc_id -q
```

Expected: FAIL because `get_page_sections` is missing.

- [ ] **Step 3: Add `get_page_sections`**

Add this function to `src/nokia_docs/search.py` after `get_document`:

```python
def get_page_sections(doc_id: int, conn: sqlite3.Connection) -> dict | None:
    """Return all indexed sections on the same documentation page as doc_id."""
    row = conn.execute(
        """SELECT id, product_line, book, page_title, rel_path
           FROM docs
           WHERE id = ?""",
        (doc_id,),
    ).fetchone()
    if not row:
        return None

    sections = [
        {
            "doc_id": r[0],
            "section_id": r[1],
            "section_title": r[2],
            "section_path": r[3],
            "depth": r[4],
        }
        for r in conn.execute(
            """SELECT id, section_id, section_title, section_path, depth
               FROM docs
               WHERE rel_path = ?
               ORDER BY id""",
            (row[4],),
        ).fetchall()
    ]

    return {
        "doc_id": row[0],
        "product_line": row[1],
        "book": row[2],
        "page_title": row[3],
        "rel_path": row[4],
        "sections": sections,
    }
```

- [ ] **Step 4: Run page tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_get_page_sections_returns_same_page_tree tests/test_search.py::test_get_page_sections_returns_none_for_unknown_doc_id -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/nokia_docs/search.py tests/test_search.py
git commit -m "Add page section navigation"
```

---

### Task 4: MCP Exposure For Match Mode And Page Sections

**Files:**
- Modify: `src/nokia_docs/server.py`
- Modify: `tests/test_server_errors.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Add server startup-error test**

Append to `tests/test_server_errors.py`:

```python
def test_get_page_sections_raises_startup_errors(monkeypatch):
    monkeypatch.setattr(server, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("DB missing")))

    with pytest.raises(RuntimeError, match="DB missing"):
        _callable_tool(server.get_page_sections)(123)
```

- [ ] **Step 2: Add direct wrapper test for `match_mode`**

Append to `tests/test_search.py`:

```python
def test_search_docs_hits_include_match_mode(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hit = search_docs("boundary clock", conn, top_k=1)[0]
    finally:
        conn.close()

    assert hit.match_mode == "strict"
```

- [ ] **Step 3: Run MCP tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_server_errors.py::test_get_page_sections_raises_startup_errors tests/test_search.py::test_search_docs_hits_include_match_mode -q
```

Expected: server test fails because `server.get_page_sections` is missing. Search hit test passes if Task 2 is complete.

- [ ] **Step 4: Wire server imports**

In `src/nokia_docs/server.py`, add to imports:

```python
from nokia_docs.search import (
    get_page_sections as _get_page_sections,
)
```

- [ ] **Step 5: Include `match_mode` in `search_docs` MCP output**

In the `search_docs` response dict in `src/nokia_docs/server.py`, add:

```python
            "match_mode":    h.match_mode,
```

- [ ] **Step 6: Add MCP tool**

Add this function after `get_document`:

```python
@mcp.tool()
def get_page_sections(doc_id: int) -> dict:
    """List all indexed sections on the same page as a documentation hit."""
    conn = _get_conn()
    page = _get_page_sections(doc_id=doc_id, conn=conn)
    if page is None:
        return {"error": f"Document {doc_id} not found."}
    return page
```

- [ ] **Step 7: Update MCP instructions**

Replace the `instructions` string with:

```python
    instructions=(
        "Nokia documentation and standards search. Use search_docs to find "
        "documentation sections, release notes, and installation guides. Use "
        "get_document to read full content. Use get_page_sections when a hit "
        "points to the right page but nested protocol sections are unclear. "
        "Use list_products to see documentation products. Use search_standards "
        "for standards compliance questions about RFC, ITU-T, IEEE, draft, "
        "platform, or release support, and list_standards_products to see "
        "indexed standards data. search_docs returns match_mode; non-strict "
        "matches should be verified with get_document or get_page_sections."
    ),
```

- [ ] **Step 8: Run server tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_server_errors.py tests/test_search.py::test_search_docs_hits_include_match_mode -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/nokia_docs/server.py tests/test_server_errors.py tests/test_search.py
git commit -m "Expose smart search navigation in MCP"
```

---

### Task 5: Neighbor Metadata Polish

**Files:**
- Modify: `src/nokia_docs/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Add neighbor metadata test**

Append to `tests/test_search.py`:

```python
def test_get_document_neighbors_include_path_and_relation(tmp_path):
    conn = _build_db(tmp_path)
    try:
        hit = search_docs("boundary clock", conn, top_k=1)[0]
        doc = get_document(hit.doc_id, conn, include_neighbors=True)
    finally:
        conn.close()

    assert doc is not None
    assert doc.neighbors
    neighbor = doc.neighbors[0]
    assert set(neighbor) == {"doc_id", "section_title", "section_path", "depth", "relation"}
    assert neighbor["section_title"] == "PTP clock classes"
    assert neighbor["relation"] == "same_page"
```

Update imports:

```python
from nokia_docs.search import _sanitize_query, get_document, get_page_sections, plan_search_queries, search_docs
```

- [ ] **Step 2: Run neighbor test to verify failure**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_get_document_neighbors_include_path_and_relation -q
```

Expected: FAIL because existing neighbor dicts do not include `section_path` or `relation`.

- [ ] **Step 3: Update neighbor query**

In `get_document`, replace the include-neighbors block with:

```python
    if include_neighbors:
        siblings = conn.execute(
            """SELECT d.id, d.section_title, d.section_path, d.depth
               FROM docs d
               WHERE d.rel_path = ? AND d.id != ?
               ORDER BY d.id
               LIMIT 10""",
            (doc.rel_path, doc_id),
        ).fetchall()
        doc.neighbors = [
            {
                "doc_id": r[0],
                "section_title": r[1],
                "section_path": r[2],
                "depth": r[3],
                "relation": "same_page",
            }
            for r in siblings
        ]
```

This keeps backward-compatible fields and adds `section_path` plus a conservative relation.

- [ ] **Step 4: Run neighbor test**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py::test_get_document_neighbors_include_path_and_relation -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/nokia_docs/search.py tests/test_search.py
git commit -m "Add document neighbor metadata"
```

---

### Task 6: Final Verification And Real DB Smoke

**Files:**
- No source changes expected.
- Runtime DB used for smoke: `C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db`

- [ ] **Step 1: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_search.py tests/test_server_errors.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```powershell
$env:PYTHONPATH='src'; pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run ruff**

Run:

```powershell
$env:PYTHONPATH='src'; python -m ruff check src tests
```

Expected: `All checks passed!`

- [ ] **Step 4: Smoke-test long queries against real DB**

Run:

```powershell
$env:PYTHONPATH='src'; @'
import sqlite3
from nokia_docs.search import search_docs

queries = [
    "PTP boundary clock G.8273.2 class C class D 7250 IXR-e2",
    "hierarchical QoS scheduler egress aggregate rate",
    "BGP-AD auto-discovery VPLS signalling",
    "boundary clock",
    "AS path",
]

conn = sqlite3.connect(r"C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db")
try:
    for query in queries:
        hits = search_docs(query, conn, top_k=5)
        print(query)
        print([(h.match_mode, h.product_line, h.book, h.section_title) for h in hits[:3]])
finally:
    conn.close()
'@ | python -
```

Expected:

- Each long query returns at least one hit.
- Short `boundary clock` and `AS path` still return hits.
- At least one long query shows non-`strict` `match_mode`, proving fallback is visible.

- [ ] **Step 5: Smoke-test page sections**

Run:

```powershell
$env:PYTHONPATH='src'; @'
import sqlite3
from nokia_docs.search import get_page_sections, search_docs

conn = sqlite3.connect(r"C:\Users\vikharev\Downloads\nokia-docs-search\nokia_docs.db")
try:
    hit = search_docs("BGP auto discovery VPLS", conn, top_k=1)[0]
    page = get_page_sections(hit.doc_id, conn)
    print(hit.doc_id, hit.section_title, len(page["sections"]) if page else 0)
finally:
    conn.close()
'@ | python -
```

Expected: prints a positive section count.

- [ ] **Step 6: Commit final verification docs if any changed**

If no files changed, do not commit. If a small README or instruction tweak was needed during verification:

```powershell
git add README.md src/nokia_docs/server.py
git commit -m "Polish smart search documentation"
```

---

## Self-Review

- Spec coverage: smart fallback modes, query hints, `match_mode`, `get_page_sections`, MCP instructions, neighbor metadata, tests, and real DB smoke checks are covered.
- Deferred-work marker scan: no deferred-work markers are present.
- Type consistency: `SearchCandidate.match_mode`, `Hit.match_mode`, `get_page_sections`, and server wrapper names are consistent across tasks.
