# Nokia Docs Token And Speed Optimization Design

## Goal

Reduce token spend and interactive latency for `nokia-docs` MCP and the
`nokia-soc` skill without weakening evidence quality.

The change should make the common SOC workflow cheaper in three places:

- MCP clients should fetch small, relevant slices of large documents before
  asking for full bodies.
- Page-section navigation should stop returning thousands of sibling sections
  by default.
- Standards and tender-row triage should use compact, structured summaries
  before the agent reads full evidence.

## Current Measurements

These measurements were taken against the local project and real
`nokia_docs.db`.

### Skill Context Size

The `nokia-soc` skill itself is moderate, but its reference JSON files are
large enough that loading them casually is expensive:

- `SKILL.md`: about 11,423 characters, 1,586 words, roughly 2,856 tokens.
- `references/feature_matrix.json`: about 120,039 characters, roughly
  30,010 tokens.
- `references/ref_soc.json`: about 207,108 characters, roughly 51,777 tokens.

The skill should keep progressive disclosure strict: load the main skill, then
load only the reference needed for the current row family.

### Search Timing

Representative local queries:

- `search_docs("7250 IXR-e2 power supply fan redundancy chassis installation specifications", top_k=5)`:
  average about 936 ms, max about 2969 ms, first hit `soft`, first body about
  976 chars, page had 165 sections.
- `search_docs("BGP routes scale maximum 26.3 enhancements", top_k=5)`:
  average about 1289 ms, max about 4237 ms, first hit `soft`, first body about
  443 chars, page had 5 sections.
- `search_docs("PTP boundary clock G.8273.2 class C class D 7250 IXR-e2", top_k=5)`:
  average about 1294 ms, max about 1836 ms, first hit `soft`, first body about
  277 chars, page had 45 sections.
- `search_standards("RFC 5880", top_k=5)`:
  average about 21 ms, max about 64 ms.

The main latency cost is still broad document FTS. Standards lookup is already
fast.

### Document Body Size

The database contains 265,625 documentation body records.

- Average body length: about 728 chars.
- 95th percentile body length: about 2,392 chars.
- Largest body length: 278,044 chars.

The long tail matters. Examples of very large bodies include:

- `7705-sar interface-config port`: about 278k chars.
- `sros clear-monitor-show-tools-commands port`: about 146k chars.
- several command-reference pages above 70k chars.

Default `get_document` behavior currently returns the whole body, which is good
for final verification but wasteful during exploration.

### Page Section Fanout

`get_page_sections` currently returns all sections that share the same page
path. This can explode context on command-reference and data-model pages.

Largest observed page-section fanouts:

- `sros md-cli-command-reference service commands`: 10,346 sections.
- `srlinux data-model-reference network-instance`: 9,459 sections.
- `7705-sar-gen2 service commands`: 5,210 sections.

This is the clearest token-saving opportunity because it does not require
changing search ranking.

## Selected Approach

Implement bounded, metadata-rich retrieval while preserving the existing strict
evidence path.

1. Add bounded `get_page_sections` retrieval with a default cap and explicit
   truncation metadata.
2. Add optional compact/excerpt retrieval to `get_document`; keep full-document
   retrieval as the default.
3. Add a compact standards summary tool instead of changing
   `search_standards`.
4. Add a deterministic SOC workbook classifier script that plans routes and
   first queries before the agent starts row-by-row evidence work.
5. Update MCP and `nokia-soc` instructions so compact calls are used for
   navigation, while full evidence is still fetched when answering compliance.

This approach is intentionally conservative: it avoids schema changes, avoids
new embedding infrastructure, and does not remove strict verification.

## MCP API Changes

### Bounded Page Sections

Change `get_page_sections` to accept optional parameters:

```python
get_page_sections(
    doc_id: int,
    max_sections: int = 200,
    around_doc_id: bool = True,
    query: str | None = None,
) -> dict[str, Any]
```

Behavior:

- Default returns at most 200 sections.
- `max_sections=0` returns all sections for compatibility and deep manual
  inspection.
- `around_doc_id=True` centers the returned window around the selected
  `doc_id` when possible.
- `query` filters section titles and section paths before windowing.
- The response keeps the existing `sections` field and adds:
  `total_sections`, `returned_sections`, `truncated`, `window_start`,
  and `window_end`.

Rationale:

- The default cap prevents accidental 10k-section dumps.
- The explicit override keeps the old behavior available.
- Centering preserves useful neighboring context for nested command pages.

### Compact Document Retrieval

Change `get_document` to accept optional parameters:

```python
get_document(
    doc_id: int,
    include_neighbors: bool = False,
    max_chars: int | None = None,
    query: str | None = None,
    context_chars: int = 1500,
) -> dict[str, Any] | None
```

Behavior:

- Default remains full body retrieval.
- If `query` is provided, return an excerpt around the first query-term or
  phrase match.
- If `max_chars` is provided without `query`, return the leading slice.
- If no match is found for `query`, return the leading slice and mark the
  response as truncated when the full body is longer.
- Add response metadata: `body_chars`, `returned_chars`, `body_truncated`,
  and `excerpt_query`.

Rationale:

- Full-document retrieval remains available for final proof.
- Exploration can use `query` plus `max_chars` to avoid pulling 100k+ chars
  into model context.
- Metadata lets clients know when they are looking at an excerpt.

### Compact Standards Summary

Add a new MCP tool instead of changing `search_standards`:

```python
summarize_standard_support(
    query: str,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    top_k: int = 50,
) -> list[dict[str, Any]]
```

The tool groups matching standard records by:

- standard reference or standard text;
- product line;
- release;
- platform;
- support status.

Each summary item should include:

- `standard_ref`;
- `standard_title`;
- `product_line`;
- `release`;
- `platform`;
- `support_status`;
- `num_records`;
- `source_rows`;
- `representative_text`, capped to 160 chars.

Rationale:

- `search_standards` remains unchanged for exact evidence.
- SOC workflows can first ask compact questions such as "is RFC 5880 supported
  on this product/release?" without reading repeated workbook text.
- Grouped output is easier to compare across releases and platforms.

## SOC Skill Changes

Add a local classifier script under the skill:

```text
C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py
```

The script should:

- read `.xlsx` workbooks with `openpyxl`;
- detect likely requirement and response columns;
- classify each row into one route:
  `standards`, `hardware`, `scale`, `sr_os_config`, `sr_linux_api`,
  `management`, `certification`, `commercial`, or `general`;
- emit JSON or TSV with `sheet`, `row`, `route`, `confidence`, `signals`,
  `requirement_text`, and `suggested_queries`;
- never decide compliance and never write the workbook.

The skill should use the classifier before large workbook work. The classifier
output is only a route plan. Final SOC answers still require MCP, CLI, YANG,
spreadsheet, or document evidence.

## Instruction Changes

### MCP Instructions

The server instructions should tell clients:

- use `summarize_standard_support` for compact standards reconnaissance;
- use `search_standards` for exact standards evidence;
- use bounded `get_page_sections` first, then explicit `max_sections=0` only
  when a full page map is needed;
- use `get_document(query=..., max_chars=...)` while navigating;
- use full `get_document` for final quoted evidence when the excerpt is not
  enough.

### `nokia-soc` Instructions

The skill should say:

- run the classifier before processing large XLSX files;
- use classifier routes to batch similar rows and reduce repeated MCP calls;
- do not load large reference JSON files unless the current row family needs
  them;
- treat non-`strict` search hits and compact excerpts as leads only;
- record whether evidence came from a full body, excerpt, standards summary,
  or exact standards hit.

## Non-Goals

- Do not add embeddings or a vector database in this change.
- Do not rebuild the documentation database.
- Do not alter FTS ranking or query planning.
- Do not reduce `top_k` defaults globally.
- Do not remove `match_mode`.
- Do not allow standards summaries or excerpts to replace final evidence when
  exact proof is required.

## Risks And Mitigations

- Default-bounding `get_page_sections` can surprise a client that expected the
  full page tree. Mitigation: add `truncated` metadata and `max_sections=0`.
- Query excerpts can miss the decisive sentence when the query uses poor terms.
  Mitigation: default full retrieval remains available, and MCP instructions
  require full verification for final answers.
- Standards grouping can hide row-level nuance. Mitigation: include
  representative source rows and keep `search_standards` unchanged.
- The classifier can route a row incorrectly. Mitigation: emit confidence and
  signals, and make it advisory rather than authoritative.

## Success Criteria

- `get_page_sections` returns no more than 200 sections by default and reports
  the true total count.
- `get_page_sections(max_sections=0)` can still return the full page section
  list.
- `get_document(query=..., max_chars=...)` returns a relevant excerpt and
  truncation metadata.
- Full `get_document(doc_id)` remains behaviorally unchanged.
- `summarize_standard_support("RFC 5880")` returns grouped compact results and
  leaves `search_standards("RFC 5880")` unchanged.
- The SOC classifier routes sample rows for standards, hardware, scale, and
  management requirements with deterministic output.
- Pytest and ruff pass for the repository.

## Validation Commands

Repository validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\nokia-docs.exe validate-db --db .\nokia_docs.db
```

SOC classifier validation:

```powershell
python C:\Users\vikharev\.agents\skills\nokia-soc\scripts\classify_soc_rows.py <sample.xlsx> --json
```

The classifier command should be run against a generated sample workbook during
implementation, not against customer data.

## Self-Review

- The spec addresses token hotspots in the MCP API, standards route, and SOC
  skill workflow.
- The design preserves full evidence paths and does not weaken SOC strictness.
- The proposed API changes are additive except for bounded default
  `get_page_sections`; that behavior has an explicit compatibility override.
- The approach is grounded in observed DB sizes, page-section fanout, and
  measured query timings.
