# nokia-docs-search

Local full-text search for Nokia documentation, release notes, and chassis
installation guides, exposed as an MCP server for Claude Code, Codex, or any
other MCP client.

The project builds a local SQLite FTS5 database from Nokia documentation exports
and exposes three MCP tools:

- `search_docs` - search sections with BM25 ranking and highlighted snippets
- `get_document` - retrieve full text for a section returned by search
- `list_products` - list indexed product lines, section counts, and books

The database is distributed separately from the source code. It is not committed
to this repository because it can be large and may contain material that should
remain inside the team environment.

## What It Indexes

| Product line | Content |
|---|---|
| `sros-26-3` | Nokia SR OS 26.3 documentation |
| `srlinux-26-3` | Nokia SR Linux 26.3 documentation |
| `7250-ixr` | Nokia 7250 IXR documentation |
| `7705-sar-gen2` | Nokia 7705 SAR Gen2 documentation |
| `7705-sar` | Nokia 7705 SAR documentation |
| `7210-sas` | Nokia 7210 SAS documentation |
| `nsp` | Nokia NSP documentation |
| `rn-sros` | Nokia SR OS release notes, including historical EOL entries |
| `rn-srl` | Nokia SR Linux release notes |
| `rn-sas` | Nokia 7210 SAS release notes |
| `rn-eda` | Nokia EDA release notes |
| `rn-mag-c` | Nokia MAG-c release notes |
| `install-guides` | Nokia chassis installation guide PDFs |

## Install

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

The package installs a CLI command:

```bash
nokia-docs --help
```

## Database Distribution

This repository contains the MCP server, indexers, tests, and documentation.
The generated SQLite database is an external runtime artifact.

Recommended team flow:

1. Build or refresh `nokia_docs.db` in a controlled internal environment.
2. Use strict indexing flags for release builds so partial source failures stop
   the build instead of producing a silently incomplete artifact.
3. Publish the DB through an approved internal artifact channel, such as an
   internal release, SharePoint folder, package registry, or file share.
4. Place the DB on each user's machine and point the MCP server at it with
   `NOKIA_DOCS_DB`.

Generated databases include `metadata` and `build_manifest` tables. The MCP
server validates schema metadata before opening the DB, and `validate-db` checks
basic table consistency before the artifact is distributed.

Do not commit generated database files to GitHub:

- `*.db`
- `*.db-wal`
- `*.db-shm`
- `*.sqlite`
- `*.sqlite3`

## Build The Database

The current release build should finish with approximately 229k searchable
sections when all three source families are present:

| Source | Current build size |
|---|---:|
| WebHelp HTML files | 9,843 files / 182,830 sections |
| Release-note records | 24,956 inserted sections |
| Installation-guide PDFs | 110 PDFs / 21,328 sections |
| Total searchable sections | 229,114 sections |

### Recommended Release Build

Use `build-db` when preparing a DB artifact for colleagues. It runs HTML, release
note, and PDF indexing; validates the finished DB; writes a `.sha256` sidecar;
and records source paths/counts in `build_manifest`.

```bash
nokia-docs build-db \
  --html-root /path/to/nokia-webhelp-root \
  --rn-dir /path/to/release-note-files \
  --pdf-dir /path/to/chassis-installation-guides \
  --output nokia_docs.db \
  --workers 8 \
  --strict
```

Distribute both files:

- `nokia_docs.db`
- `nokia_docs.db.sha256`

Use `--no-strict` only for local experiments with incomplete fixture data.

### Manual Step 1: Index WebHelp HTML Documentation

Point the indexer at a local Nokia WebHelp export. The command walks HTML files,
parses documentation sections, and writes them into a SQLite FTS5 database.

```bash
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset
```

Use strict failure handling for release builds:

```bash
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset --fail-on-error
```

Useful options:

```bash
# Reuse an existing DB and skip duplicate sections
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db

# Control parser worker processes
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --workers 4
```

### Manual Step 2: Index Release Notes

Release notes are expected as CSV/JSON files in a local directory:

- `rn_sros.csv`
- `rn_srl.csv`
- `rn_sas.csv`
- `rn_eda.csv`
- `rn_mag-c.csv`
- `rn_eol.json`

Index them into the same database:

```bash
nokia-docs index-rn --db nokia_docs.db --rn-dir /path/to/release-note-files
```

Use strict failure handling for release builds:

```bash
nokia-docs index-rn --db nokia_docs.db --rn-dir /path/to/release-note-files --fail-on-error
```

To replace existing release-note rows and index them again:

```bash
nokia-docs reindex-rn --db nokia_docs.db --rn-dir /path/to/release-note-files
```

The old scripts still work as compatibility wrappers:

```bash
python index_rn.py --db nokia_docs.db --rn-dir /path/to/release-note-files
python reindex_rn.py nokia_docs.db --rn-dir /path/to/release-note-files
```

### Manual Step 3: Index Chassis Installation Guide PDFs

The PDF indexer de-duplicates files by Nokia document number and keeps the
highest issue number before parsing.

```bash
nokia-docs index-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
```

Use strict failure handling for release builds:

```bash
nokia-docs index-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides --fail-on-error
```

To replace existing installation-guide rows:

```bash
nokia-docs reindex-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
```

For release builds, combine re-indexing with strict failure handling:

```bash
nokia-docs reindex-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides --fail-on-error
```

Compatibility wrappers:

```bash
python index_pdf.py --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
python reindex_pdf.py nokia_docs.db /path/to/chassis-installation-guides --fail-on-error
```

### Manual Step 4: Validate The Database Artifact

Before distributing a rebuilt database, validate schema metadata and table
consistency:

```bash
nokia-docs validate-db --db nokia_docs.db
```

The command checks schema compatibility plus `docs`, `docs_body`, and `docs_fts`
row consistency.

## Run The MCP Server

The server reads the database path from `NOKIA_DOCS_DB`.

```bash
NOKIA_DOCS_DB=/absolute/path/to/nokia_docs.db nokia-docs serve
```

Windows PowerShell:

```powershell
$env:NOKIA_DOCS_DB = "C:\path\to\nokia_docs.db"
nokia-docs serve
```

## Codex Or Claude Code Configuration

Add an MCP server entry that points to the installed `nokia-docs` command.

```toml
[mcp_servers.nokia-docs]
command = "nokia-docs"
args = ["serve"]

[mcp_servers.nokia-docs.env]
NOKIA_DOCS_DB = "C:\\path\\to\\nokia_docs.db"
```

If your environment needs an absolute command path, use the generated script from
the Python environment, for example:

```toml
[mcp_servers.nokia-docs]
command = "C:\\Python314\\Scripts\\nokia-docs.exe"
args = ["serve"]

[mcp_servers.nokia-docs.env]
NOKIA_DOCS_DB = "C:\\path\\to\\nokia_docs.db"
```

## MCP Tool Reference

### `search_docs`

Search Nokia documentation and release notes using SQLite FTS5/BM25.

```text
search_docs(query, product_line?, book?, top_k?)
```

Parameters:

| Name | Type | Description |
|---|---|---|
| `query` | string | Natural language or FTS5 query. Examples: `rsvp interface`, `"bgp hold-time"`, `rsvp*`, `bgp AND evpn` |
| `product_line` | string | Optional slug or alias, such as `sros`, `srl`, `ixr`, `sar`, `rn-sros`, `install` |
| `book` | string | Optional book or section filter, such as `mpls`, `new-features`, `resolved-issues`, `7750-sr-1s` |
| `top_k` | int | Number of hits, clamped to 1-50 |

### `get_document`

Retrieve full text for a section returned by `search_docs`.

```text
get_document(doc_id, include_neighbors?)
```

Set `include_neighbors=true` when the answer needs nearby sections from the same
page.

### `list_products`

List indexed products with section counts and book names.

```text
list_products()
```

## Search Examples

Documentation:

```text
search_docs("rsvp interface configuration", product_line="sros")
search_docs('"bgp hold-time" configure router', product_line="sros")
search_docs("evpn multi-homing all-active", product_line="srl")
search_docs("isis segment-routing prefix-sid", product_line="ixr")
search_docs("rsvp*", product_line="sros")
```

Release notes:

```text
search_docs("new features 26.3.R1", product_line="rn-sros", book="new-features")
search_docs("bgp route-target memory leak resolved", product_line="rn-sros", book="resolved-issues")
search_docs("known issue evpn type-5", product_line="rn-sros", book="known-issues")
search_docs("grpc path resolved", product_line="rn-srl")
```

Installation guides:

```text
search_docs("protective earth grounding", product_line="install")
search_docs("power supply requirements AC DC", product_line="install", book="7705-sar-ax")
search_docs("rack mount installation", product_line="install-guides")
search_docs("QSFP28 optical transceiver", product_line="chassis")
```

## Product Slugs And Aliases

| Aliases | Product line |
|---|---|
| `sros`, `sr os`, `7750` | `sros-26-3` |
| `srl`, `srlinux`, `sr linux` | `srlinux-26-3` |
| `ixr`, `7250`, `7250-ixr` | `7250-ixr` |
| `sar-gen2`, `7705-sar-gen2` | `7705-sar-gen2` |
| `sar`, `7705`, `7705-sar` | `7705-sar` |
| `sas`, `7210`, `7210-sas` | `7210-sas` |
| `nsp` | `nsp` |
| `rn`, `release notes`, `rn-sros`, `rn sros` | `rn-sros` |
| `rn-srl`, `rn srl`, `rn srlinux` | `rn-srl` |
| `rn-sas`, `rn sas` | `rn-sas` |
| `rn-eda`, `rn eda`, `eda` | `rn-eda` |
| `rn-mag-c`, `rn mag-c`, `mag-c` | `rn-mag-c` |
| `install`, `chassis`, `installation`, `install-guides` | `install-guides` |

## Architecture

The project normalizes multiple source formats into one searchable record type:
a documentation section.

```text
HTML WebHelp export -> parse.py      -> docs/docs_body/docs_fts
Release note CSVs   -> rn.py         -> docs/docs_body/docs_fts
Installation PDFs   -> pdf_index.py  -> docs/docs_body/docs_fts
MCP tool call       -> server.py     -> search.py -> SQLite FTS5
```

The important design choice is that the MCP server is read-only. All expensive
or risky work happens before runtime during DB construction. At runtime the MCP
process validates the DB metadata, opens SQLite connections, and serves search
or document lookups.

### Runtime Data Model

Each indexed section is represented once in metadata tables and once in the FTS
index:

| Table | Purpose |
|---|---|
| `docs` | Section metadata: product, book, source path, page title, section title, hierarchy, and character length |
| `docs_body` | Full section body, joined by `docs.id` when `get_document` needs complete text |
| `docs_fts` | SQLite FTS5 virtual table used by `search_docs` with weighted BM25 ranking |
| `metadata` | Schema compatibility values checked by the server and `validate-db` |
| `build_manifest` | Release artifact provenance: source paths, parsed counts, failure counts, and sidecar hash filename |

Search results are intentionally small: `search_docs` returns metadata,
highlighted snippets, and a `doc_id`. The client can then call `get_document`
with that `doc_id` to load the full body only when it is actually needed.

### Source Indexing Pipeline

The release build uses `src/nokia_docs/build.py` as the orchestrator:

1. `index_cmd` creates a fresh DB and indexes WebHelp HTML with `--reset`.
2. `index_release_notes` appends release-note CSV/JSON rows into the same DB.
3. `index_pdfs` appends installation-guide PDF sections into the same DB.
4. `write_sha256_sidecar` writes `nokia_docs.db.sha256`.
5. `validate_db_file` checks schema compatibility and table consistency.

Strict mode is the default for `build-db`. If any source family reports missing
inputs, parse failures, write failures, or failed PDFs, the build stops instead
of producing a partial artifact.

### Search Pipeline

When an MCP client calls `search_docs`:

1. `server.py` receives the FastMCP tool call.
2. `products.py` resolves aliases such as `sros`, `srl`, `ixr`, `rn`, or
   `install` into canonical product slugs.
3. `search.py` sanitizes natural-language text into an FTS5 query. Plain
   multi-word input becomes a phrase query plus prefix-matched terms for better
   recall.
4. SQLite FTS5 searches `docs_fts`, joins to `docs`, applies optional product
   and book filters, and orders by BM25 score.
5. `server.py` serializes dataclass results into MCP-friendly dictionaries.

`get_document` uses the same DB connection but joins `docs` with `docs_body` to
return the full section body. With `include_neighbors=true`, it also returns
nearby sections from the same source page to help an LLM understand context.

### File Map

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata, console script registration, runtime dependencies, and Ruff settings |
| `src/nokia_docs/cli.py` | CLI entrypoint and command registration |
| `src/nokia_docs/build.py` | One-shot release build orchestration, artifact validation, and `.sha256` sidecar generation |
| `src/nokia_docs/server.py` | FastMCP server and tool definitions |
| `src/nokia_docs/search.py` | Query sanitizing, alias resolution, BM25 search, document retrieval |
| `src/nokia_docs/index.py` | HTML WebHelp indexer |
| `src/nokia_docs/parse.py` | HTML parser for Oxygen WebHelp and NSP HTML |
| `src/nokia_docs/parse_pdf.py` | PDF section extraction and de-duplication helpers |
| `src/nokia_docs/pdf_index.py` | PDF indexing and re-indexing commands |
| `src/nokia_docs/rn.py` | Release-note CSV/JSON indexing and re-indexing commands |
| `src/nokia_docs/products.py` | Canonical product registry, display names, and aliases |
| `src/nokia_docs/db.py` | Shared SQLite schema, insert, and delete helpers |
| `src/nokia_docs/schema.sql` | SQLite tables and FTS5 schema |
| `index_pdf.py`, `reindex_pdf.py`, `index_rn.py`, `reindex_rn.py` | Backward-compatible wrappers around package CLI functions |
| `tests/` | Unit and regression tests |
| `.github/workflows/ci.yml` | GitHub Actions lint, compile, and test workflow |

### Module Responsibilities

`cli.py` is intentionally thin. It wires Click commands together and delegates
real work to modules that can also be tested directly.

`db.py` owns all schema-sensitive operations. Indexers do not write raw SQL for
the common insert path; they pass normalized records to `insert_records`, which
keeps `docs`, `docs_body`, and `docs_fts` synchronized in one transaction.

`index.py` and `parse.py` handle WebHelp. `index.py` discovers HTML files,
parallelizes parsing, reports progress, records failures, and performs FTS
optimization. `parse.py` turns each HTML page into normalized section records.

`rn.py` treats release notes as structured data. It reads expected `rn_*.csv`
and `rn_eol.json` files, maps product/version/category metadata into normalized
records, and can replace only release-note product lines during re-indexing.

`parse_pdf.py` contains PDF-specific parsing rules, title cleanup, chunking, and
document-number/issue extraction. `pdf_index.py` owns the DB write flow and
keeps only the newest issue for duplicate installation-guide PDFs.

`search.py` is the retrieval layer. It hides SQLite details from the MCP server
and returns typed `Hit`, `Document`, and `ProductInfo` objects.

`server.py` is the only MCP-facing layer. It validates `NOKIA_DOCS_DB`, checks
schema metadata, keeps per-thread read-only SQLite connections, and exposes the
three tools: `search_docs`, `get_document`, and `list_products`.

### Extending The Index

To add a new product or source family:

1. Add the canonical product slug, display name, and aliases in `products.py`.
2. Normalize source content into records with the same fields used by
   `insert_records`.
3. Add or update a targeted indexer module for that source type.
4. Record useful counts in `build_manifest` during release builds.
5. Add tests for parser behavior, indexing behavior, and search/filter behavior.

This keeps the MCP contract stable even as new Nokia document families are
added behind it.

The MCP server opens read-only SQLite connections with one connection per thread.
This keeps concurrent tool calls safe while avoiding any write access during
interactive search.

## Testing

Run the full test suite:

```bash
python -m pytest
```

The tests cover:

- PDF filename parsing and de-duplication
- PDF chunk splitting limits
- search alias resolution
- FTS prefix query behavior
- parser failure logging
- database metadata and schema-version validation
- CLI command registration
- product registry consistency
- HTML and release-note fixture indexing

Run linting for maintained code paths:

```bash
python -m ruff check .
```

GitHub Actions runs linting, bytecode compilation, and the full test suite on
push and pull requests.

Some PDF integration tests are skipped unless `NOKIA_DOCS_SAMPLE_PDF` points to
a local sample PDF.

## Troubleshooting

### `NOKIA_DOCS_DB environment variable is not set`

Set the environment variable before running the server:

```bash
NOKIA_DOCS_DB=/absolute/path/to/nokia_docs.db nokia-docs serve
```

### `Database not found`

Download the separately distributed database artifact, or build the database
locally:

```bash
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset
```

### `Database schema version ... is not compatible`

The MCP server found an old or manually created database without compatible
metadata. Rebuild or download a current DB artifact.

### `docs/docs_body row count mismatch`

The database failed artifact validation. Rebuild it with strict indexing flags
and run `nokia-docs validate-db --db nokia_docs.db` again before distributing it.

### Search returns too many unrelated hits

Use a product filter:

```text
search_docs("rsvp interface", product_line="sros")
```

Or use exact phrases:

```text
search_docs('"bgp hold-time"', product_line="sros")
```

### Search returns no hits

Try broader terms, remove the `book` filter, or use `list_products()` to confirm
that the expected product line is indexed.

### Prefix search

FTS5 prefix syntax is supported:

```text
search_docs("rsvp*", product_line="sros")
```

### Rebuilding only one source type

Use the targeted re-index commands:

```bash
nokia-docs reindex-rn --db nokia_docs.db --rn-dir /path/to/release-note-files
nokia-docs reindex-pdf --db nokia_docs.db --pdf-dir /path/to/pdfs
```

## Repository Hygiene

The repository intentionally ignores generated and local data:

- SQLite databases: `*.db`, `*.db-wal`, `*.db-shm`
- Python caches and build metadata
- downloaded release-note CSV/JSON/HTML files
- generated WebHelp helper JavaScript files

Commit source code, tests, and documentation. Keep the generated search database
local or distribute it through an internal approved channel.
