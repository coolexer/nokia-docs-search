# Smart Documentation Search Design

## Goal

Improve `nokia-docs` search ergonomics so long human/tender-style queries return useful results instead of empty sets, while preserving exact/short query behavior that already works well.

Examples that should improve:

- `PTP boundary clock G.8273.2 class C class D 7250 IXR-e2`
- `hierarchical QoS scheduler egress aggregate rate`
- `BGP-AD auto-discovery VPLS signalling`

Short precise queries such as `boundary clock`, `AS path`, `OSPF`, `flexible-algorithm`, `keychain`, and `management-access-filter` should keep their current behavior.

## Current Problem

`search_docs` currently converts plain multi-word input into:

1. an exact phrase, or
2. an `AND` query over every term.

That is good for concise technical phrases, but brittle for long tender wording. Product/model hints, class names, spelling variants, and protocol subfeature wording can force all terms to match inside one indexed section. If one term is absent from the section, SQLite FTS returns no rows even when nearby documentation is relevant.

Also, users sometimes need the page structure rather than a single section snippet. Today `get_document(include_neighbors=True)` returns a small sibling list, but not a usable page tree.

## Selected Approach

Add a smart search layer around the existing FTS index. Do not rebuild the documentation database for this change.

The change has three parts:

1. Add query planning and fallback search modes to `search_docs`.
2. Add page navigation via `get_page_sections`.
3. Improve MCP instructions so clients choose `search_docs`, `search_standards`, and page navigation appropriately.

The existing indexed `docs`, `docs_body`, and `docs_fts` tables remain unchanged.

## Search Modes

Add a small internal query planner that produces ordered candidate FTS queries.

Each returned hit should include a new `match_mode` field. Existing fields stay unchanged.

### Mode 1: `strict`

Current behavior:

- Exact phrase OR prefix `AND` terms.
- Used first for all queries.
- If enough hits are found, return immediately.

Enough means at least `min(top_k, 3)` hits by default.

### Mode 2: `relaxed`

Used when strict search returns too few hits.

This mode removes or lowers the impact of likely context/noise terms:

- Product/model hints: `7250`, `IXR`, `IXR-e2`, `SR`, `SR-1`, `SR-2`, `VSR`, `7750`, `7705`, `7210`.
- Release-looking terms: `26.3`, `24.10.R1`.
- Standalone class letters in timing phrases: `class C`, `class D` becomes optional rather than required.
- Very short standalone words unless they are meaningful technical tokens.

The relaxed query keeps standards/protocol/subfeature terms such as:

- `PTP`, `boundary`, `clock`, `G.8273.2`
- `hierarchical`, `QoS`, `scheduler`, `egress`, `aggregate`, `rate`
- `BGP`, `AD`, `auto-discovery`, `VPLS`, `signaling`

### Mode 3: `variant`

Used when strict/relaxed return too few hits.

This mode expands spelling and punctuation variants:

- `signalling` <-> `signaling`
- `auto-discovery` <-> `auto discovery`
- `BGP-AD` <-> `BGP AD`
- `AS path` <-> `AS-path`
- `QoS` <-> `QOS`
- Hyphenated terms can also be searched as space-separated terms.

Variants should be conservative and deterministic. Keep the synonym list in code, not in the database.

### Mode 4: `soft`

Used as final fallback.

This mode searches important terms with `OR` instead of requiring every term. It then ranks results by:

1. number of important query terms matched in title/path/body snippets,
2. BM25 score,
3. title/path match boost.

Soft results must be marked with `match_mode = "soft"` so downstream clients can phrase answers carefully.

## Query Hints

Parse hints from user text but do not make them hard filters by default.

### Product and platform hints

Detect common hints:

- `7250 IXR`, `IXR-e`, `IXR-e2`
- `7750`, `7450`, `7950`, `VSR`
- `7705 SAR`, `7210 SAS`
- `SR OS`, `SR Linux`

Use hints to boost or to choose fallback product filters only when the user explicitly provides `product_line`.

Do not remove useful terms from standards references. For example, `G.8273.2` must remain searchable.

### Standards references

Recognize terms like:

- `RFC 5880`
- `G.8273.2`
- `IEEE 802.1Q`
- `ITU-T Y.1731`
- `draft-ietf-...`

If a query is primarily about standards support on a platform/release, MCP instructions should encourage `search_standards` rather than only `search_docs`.

## Page Navigation

Add a new search-layer function and MCP tool:

```text
get_page_sections(doc_id: int) -> dict
```

Given a `doc_id`, return every indexed section on the same `rel_path`.

Return shape:

```text
doc_id
product_line
book
page_title
rel_path
sections:
  - doc_id
    section_id
    section_title
    section_path
    depth
```

Sort by document order. The current schema does not have an explicit section ordinal, so use `docs.id` order within the same `rel_path`, which matches current insertion order.

This tool is for cases where FTS finds a protocol page but the answer is in a nested subsection.

## Neighbor Improvements

Keep `get_document(include_neighbors=True)` backward compatible.

Improve returned `neighbors` so each item includes:

- `doc_id`
- `section_title`
- `section_path`
- `depth`
- `relation`, one of `parent`, `sibling`, `child`, or `same_page`

If implementing this becomes too invasive, ship `get_page_sections` first and leave deeper neighbor relation classification for a follow-up.

## API Changes

### `search_docs`

Current MCP signature stays:

```text
search_docs(query, product_line?, book?, top_k?)
```

Each hit gains:

```text
match_mode
```

Potential values:

- `strict`
- `relaxed`
- `variant`
- `soft`

No existing response fields are removed.

### `get_page_sections`

New MCP tool:

```text
get_page_sections(doc_id)
```

Use after `search_docs` when the user needs protocol page navigation, nested subsections, or surrounding document structure.

## MCP Instructions

Update server instructions:

- Use `search_docs` for general documentation, release notes, and installation guides.
- Use `search_standards` for standards-compliance questions such as whether a platform/release supports an RFC, ITU-T, IEEE, or draft.
- Use `get_page_sections` after `search_docs` when a result points to the right page but the exact subsection is unclear.
- For long tender phrases, prefer trying `search_docs` as-is first; if `match_mode` is not `strict`, treat results as recall-oriented and verify with `get_document` or `get_page_sections`.

## Tests

Add tests with a small synthetic SQLite fixture rather than relying on the large runtime DB.

### Query planner tests

Test `_sanitize_query` or new planner helpers:

- Short precise queries still generate strict query first.
- Long PTP query produces relaxed candidates retaining `PTP`, `boundary`, `clock`, `G.8273.2` while relaxing platform/class noise.
- `signalling` also generates `signaling`.
- `BGP-AD` also generates `BGP AD` / `BGP` + `AD`.

### Search fallback tests

Create fixture sections where strict search fails but relaxed/variant/soft succeeds:

- `PTP boundary clock G.8273.2 class C class D 7250 IXR-e2`
- `BGP-AD auto-discovery VPLS signalling`
- `hierarchical QoS scheduler egress aggregate rate`

Assertions:

- results are non-empty,
- `match_mode` indicates the fallback used,
- returned title/path is relevant,
- short queries still return `match_mode = "strict"` when strict hits exist.

### Page navigation tests

Fixture with multiple sections sharing `rel_path`.

Assertions:

- `get_page_sections(doc_id)` returns all sections for the page,
- sections include `depth`, `section_id`, `section_title`, and `section_path`,
- ordering follows document id order,
- unknown `doc_id` returns an error-style dict or `None` consistently with existing `get_document` behavior.

### MCP wrapper tests

Add startup-error tests for `get_page_sections`, matching existing server error tests.

Add one direct wrapper test if practical to ensure `match_mode` is included in `search_docs` output.

## Rollout

1. Add planner helpers and tests.
2. Add fallback execution inside `search_docs`.
3. Add `match_mode` to `Hit` and MCP responses.
4. Add `get_page_sections` search function and MCP tool.
5. Update server instructions.
6. Run full test suite.
7. Smoke-test against the real DB:
   - `PTP boundary clock G.8273.2 class C class D 7250 IXR-e2`
   - `hierarchical QoS scheduler egress aggregate rate`
   - `BGP-AD auto-discovery VPLS signalling`
   - `boundary clock`
   - `AS path`

## Non-Goals

- Do not rebuild or reindex the main documentation corpus.
- Do not introduce embeddings or vector search in this change.
- Do not make product/model hints hard filters unless the user explicitly passes `product_line`.
- Do not change the public signature of existing MCP tools.
- Do not remove exact/short query behavior that currently works.

## Open Questions

- Whether to expose `match_mode` only in MCP responses or also in internal dataclasses used by tests. Recommendation: add it to `Hit` with default `strict`.
- Whether soft OR fallback should be enabled for all users immediately or gated by a flag. Recommendation: enable by default, because `match_mode` makes fallback visible.
- Whether `include_neighbors=True` should include full same-page sections or only parent/sibling/child. Recommendation: keep the existing small neighbor list and add `get_page_sections` for full navigation.
