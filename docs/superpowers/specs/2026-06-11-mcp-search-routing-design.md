# Nokia Docs MCP Search Routing Design

## Goal

Teach the `nokia-docs` MCP server to describe where different Nokia evidence
usually lives, so MCP clients search deeper and more accurately without changing
the underlying FTS index or silently rewriting user queries.

The immediate problems to fix:

- Hardware questions about power, redundancy, fans, PSUs, FRUs, ports, optics,
  airflow, temperature, and environmental limits should point clients toward
  chassis installation guides, hardware guides, specifications, and orderable
  parts.
- Scale, capacity, performance, and numeric-limit questions should be searched
  in normal product docs and also in release notes, especially `new-features`,
  `enhancements`, `resolved-issues`, and `known-issues`.
- Standards questions should route to `search_standards` before generic docs.
- Long tender wording should still be searched, but non-`strict` `match_mode`
  results must be verified with full documents and, when needed, page sections.

## Current State

`src/nokia_docs/server.py` exposes these MCP tools:

- `search_docs`
- `get_document`
- `get_page_sections`
- `list_products`
- `search_standards`
- `list_standards_products`

The current server instructions correctly mention documentation search,
standards search, `get_page_sections`, and `match_mode`, but they do not teach
the client the internal library map:

- chassis installation guides are the right first destination for physical
  platform details;
- release notes can contain scale, capacity, caveats, and changed limits;
- hardware, scale, standards, protocol behavior, and CLI/config evidence need
  different search strategies.

This leads agents to ask broad FTS queries such as `fan redundancy 7250 IXR-e2`
without trying guide-specific terms like `chassis installation`, `fan tray`,
`power supply`, or `specifications`.

## Selected Approach

Update MCP-facing guidance only:

1. Expand the `FastMCP(instructions=...)` text in `src/nokia_docs/server.py`.
2. Expand the `search_docs` docstring with routing examples and verification
   rules.
3. Add regression tests that assert the routing hints remain present.

Do not change `search_docs` ranking, query planning, schema, index format, or
tool signatures in this change.

This keeps the MCP strict: it tells clients where to search, while final
evidence still requires `get_document`, `search_standards`, CLI, or YANG proof.

## Search Routing Rules

### Hardware And Chassis

For requirements about physical platform behavior, client instructions should
say to search with platform/model hints plus these guide terms:

- `chassis installation guide`
- `hardware guide`
- `specifications`
- `orderable parts`
- `power supply`
- `fan tray`
- `airflow`
- `port`
- `optics`
- `MDA`
- `environmental`

Topics covered by this route:

- power input and power consumption;
- PSU or feed redundancy;
- fan redundancy and airflow direction;
- chassis dimensions and weight;
- port counts, port types, line cards, MDAs, and optics;
- environmental limits;
- field-replaceable units.

The MCP should not imply that protocol configuration guides are enough for
these rows.

### Scale, Capacity, And Performance

For routes, MACs, VLANs, services, subscribers, tunnels, queues, telemetry
rates, latency, power draw, and other numeric thresholds:

1. Search exact numeric thresholds and units in product docs.
2. Search the feature name with `scale`, `scaling`, `capacity`, `maximum`,
   `limit`, `profile`, and `resources`.
3. Also search release notes by using RN product lines or books:
   `new-features`, `enhancements`, `resolved-issues`, `known-issues`.
4. Do not infer compliance from nearby or larger platforms unless the fetched
   source explicitly applies to the target platform/release.

Release notes are not final proof by themselves when a stable product guide
contains the exact limit, but they are required search territory for changed
limits, newly introduced scale, and release-specific caveats.

### Standards

For RFC, ITU-T, IEEE, IETF draft, MEF, 3GPP, and protocol-conformance
questions:

1. Use `search_standards` first with standard reference, platform, product, and
   release hints when available.
2. Use `search_docs` after standards search to explain configuration behavior,
   implementation limits, or feature context.
3. Use `list_standards_products` only to discover indexed standards data, not
   as final support proof.

### Protocol And Feature Behavior

For feature behavior, configuration, and operational requirements:

1. Search the tender wording once.
2. Search protocol synonyms, command terms, and exact feature names.
3. Use `get_document` for candidate hits.
4. If a hit points to the right page but a nested subsection is unclear, call
   `get_page_sections(doc_id)` and fetch the exact section with `get_document`.
5. Treat `relaxed`, `variant`, and `soft` `match_mode` hits as leads, not final
   proof.

## MCP Instruction Text Requirements

The `FastMCP` instructions should include concise routing guidance with these
terms present:

- `chassis installation`
- `hardware guide`
- `power`
- `fan`
- `ports`
- `optics`
- `release notes`
- `new-features`
- `enhancements`
- `resolved-issues`
- `known-issues`
- `scale`
- `capacity`
- `search_standards`
- `get_page_sections`
- `match_mode`

The text should remain short enough for every MCP client startup prompt. It
should be directive, not a long SOC workflow.

## `search_docs` Docstring Requirements

The `search_docs` tool docstring should:

- keep existing argument documentation and product aliases;
- mention hardware route examples;
- mention release-notes route examples for scale/capacity;
- state that standards support belongs in `search_standards`;
- state that returned `match_mode` should drive verification depth;
- state that snippets are candidates and full evidence requires
  `get_document`.

## Tests

Add focused tests in `tests/test_server_errors.py` or a new small
`tests/test_server_instructions.py`.

Recommended tests:

```python
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
```

If `FastMCP` does not expose `.instructions` directly, use the actual public or
private attribute already present in the object, and keep the helper local to
the test file.

Also add a docstring-level test only if the instructions test does not cover
`search_docs` guidance. The goal is to prevent future regressions without
coupling tests to exact prose.

## Validation

Implementation validation should run:

```powershell
$env:PYTHONPATH='src'; pytest tests/test_server_errors.py -q
$env:PYTHONPATH='src'; pytest -q
python -m ruff check src tests
```

If a new test file is added, include it in the focused command.

No runtime database rebuild is required. A smoke query can be run manually after
implementation, but the change is instructional and should not affect search
results.

## Non-Goals

- Do not add automatic query expansion in `search_docs`.
- Do not add a new MCP tool in this change.
- Do not alter ranking, FTS schema, parser behavior, or indexed data.
- Do not make SOC-specific language the default MCP instruction text.

## Self-Review

- Spec coverage: hardware/chassis, scale/RN, standards, protocol/page-section,
  `match_mode`, tests, validation, and non-goals are covered.
- Validity check: all referenced tools exist in `src/nokia_docs/server.py`.
- Scope check: this is one focused MCP guidance change, not a search-engine
  rewrite.
- Ambiguity check: instructions are required to guide clients, while final proof
  still comes from existing evidence tools.
