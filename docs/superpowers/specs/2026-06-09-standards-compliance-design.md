# Standards Compliance Index Design

## Goal

Add Nokia standards-compliance spreadsheets to `nokia-docs-search` so Codex and other MCP clients can answer standards support questions directly from the local SQLite database.

The initial sources are:

- `C:\!Docs\OneDrive - Nokia\Docs\7750\7x50-standards-compliance-20260226-field.xlsx`
- `C:\!Docs\OneDrive - Nokia\Docs\7220\SR_Linux-standards-compliance-20260310-field.xlsx`

## Selected Approach

Use a hybrid model:

1. Store parsed spreadsheet rows in dedicated structured tables for precise filtering by product, platform, release, standards group, and support status.
2. Also insert supported standards into the existing `docs`, `docs_body`, and `docs_fts` search index so existing `search_docs` workflows can find standards by RFC/draft/keyword.
3. Expose dedicated MCP tools for standards-specific queries where users need exact answers rather than document snippets.

This keeps backward compatibility with the current MCP design while adding structured lookup behavior for tender and compliance work.

## Data Model

Add `standards_sources` for source workbook metadata:

- `id`
- `source_path`
- `source_name`
- `source_sha256`
- `indexed_utc`

Add `standards` for normalized standards entries:

- `id`
- `source_id`
- `product_line`, such as `sros-standards` or `srlinux-standards`
- `platform`, such as `7450 ESS / 7750 SR / 7950 XRS / VSR`, `7250 IXR`, `7705 SAR Gen2`, or `SR Linux`
- `release`, such as `26.3.R1` or `26.3.1`
- `group_title`
- `standard_ref`, extracted from the beginning of the standard text when possible, such as `RFC 5880`
- `standard_title`, best-effort title text after the reference
- `standard_text`, original normalized cell text
- `support_status`, usually `supported` or `not_supported`
- `sheet_name`
- `row_number`

Add `standards_fts` for standards search. It should index group, reference, title, standard text, product, platform, and release.

Existing schema validation must continue to accept existing document tables and additionally validate standards tables when present.

Keep the existing `SCHEMA_VERSION` unchanged for this additive change. The new tables are created by `open_write_db` when indexing runs, and existing documentation-only databases should continue to serve `search_docs`, `get_document`, and `list_products`. Standards-specific tools should return an empty result or a clear "standards data is not indexed" response when the tables are absent.

## Parsing

Create a new `standards.py` module.

The parser reads XLSX files with `openpyxl` in read-only, data-only mode. Because `openpyxl` is not currently a package dependency, add it to project dependencies.

Sheet names provide the release:

- SR OS sheets use `SR OS <release> Standards`, for example `SR OS 26.3.R1 Standards`.
- SR Linux sheets use `SR Linux <release> Standards`, for example `SR Linux 26.3.1 Standards`.

The first row is treated as headers. The first column must be the group title. Remaining non-empty columns are platform-specific standards columns. Columns named `Comments` and blank headers are ignored.

For older SR OS sheets with `List of Standards in this Group`, treat the platform as `7450 ESS / 7750 SR / 7950 XRS / VSR`. For SR Linux sheets, treat `SR Linux Standards` as platform `SR Linux`.

Each populated standards cell creates one record:

- Empty cells are ignored.
- Exact `Not Supported` cells create `support_status = not_supported`.
- All other non-empty cells create `support_status = supported`.
- Text is whitespace-normalized but otherwise preserved.

The reference extractor should cover common forms such as `RFC 5880`, `draft-ietf-lsr-...`, `IEEE 802.1Q`, `ITU-T Y.1731`, `3GPP Release 12`, and similar visible prefixes. If no clear reference exists, leave `standard_ref` empty and keep the full text in `standard_text`.

## Indexing Commands

Add CLI commands:

- `nokia-docs index-standards --db nokia_docs.db --standards-file <xlsx> --product sros`
- `nokia-docs reindex-standards --db nokia_docs.db --standards-file <xlsx> --product sros`

Allow multiple `--standards-file` values so SR OS and SR Linux can be indexed in one command. Product is inferred from workbook and sheet names by default. An explicit `--product` is allowed only when a single standards file is supplied, which avoids ambiguous file-to-product pairing.

Extend `build-db` with optional repeated `--standards-file` arguments. In strict release builds, a missing or unparsable standards file should fail the build if it was explicitly supplied.

## MCP Tools

Add `search_standards`:

- `query: str | None`
- `product_line: str | None`
- `platform: str | None`
- `release: str | None`
- `group: str | None`
- `support_status: str | None`
- `top_k: int = 20`

It returns structured rows with source metadata, product, platform, release, group, reference, title/text, status, sheet name, and row number.

Add `list_standards_products`:

- Returns product lines, platforms, release ranges, counts, and source workbook names.

Update MCP instructions so clients know to use `search_standards` for standards compliance questions and `search_docs` for general documentation.

## Product Aliases

Add product aliases and display names:

- `sros-standards`: SR OS standards compliance
- `srlinux-standards`: SR Linux standards compliance

Aliases should include `standards`, `sros standards`, `sr os standards`, `srlinux standards`, and `sr linux standards`.

The existing `sros` and `srlinux` aliases should continue to point to documentation slugs for `search_docs` compatibility. Dedicated standards tools can resolve standards-specific aliases independently if needed.

## Tests

Add unit tests with small generated XLSX fixtures:

- SR OS parser handles multi-platform sheets and `Not Supported`.
- SR Linux parser handles one platform column and blank trailing columns.
- Reindex deletes only standards rows and not documentation/release-note/PDF rows.
- `search_standards` filters by query, product, platform, release, group, and support status.
- `list_standards_products` returns counts and release ranges.
- Existing `search_docs` can find indexed supported standards through the shared docs FTS.

## Rollout

After implementation:

1. Run targeted tests for standards parsing/search.
2. Run the full test suite.
3. Index the two provided workbooks into the local runtime DB.
4. Validate the DB.
5. Smoke-test the MCP search path with examples such as `RFC 5880`, `BGP`, and `Not Supported` for `7250 IXR`.
