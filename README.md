# nokia-docs-search

Local full-text search for Nokia documentation, release notes, and chassis
installation guides, exposed as an MCP server for Claude Code, Codex, or any
other MCP client.

The project builds a local SQLite FTS5 database from Nokia documentation exports
and exposes three MCP tools:

- `search_docs` - search sections with BM25 ranking and highlighted snippets
- `get_document` - retrieve full text for a section returned by search
- `list_products` - list indexed product lines, section counts, and books

The database is local. It is not committed to this repository because it can be
large and may contain material that should remain inside the team environment.

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

## Build The Database

### 1. Index WebHelp HTML Documentation

Point the indexer at a local Nokia WebHelp export. The command walks HTML files,
parses documentation sections, and writes them into a SQLite FTS5 database.

```bash
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset
```

Useful options:

```bash
# Reuse an existing DB and skip duplicate sections
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db

# Control parser worker processes
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --workers 4
```

### 2. Index Release Notes

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

To replace existing release-note rows and index them again:

```bash
nokia-docs reindex-rn --db nokia_docs.db --rn-dir /path/to/release-note-files
```

The old scripts still work as compatibility wrappers:

```bash
python index_rn.py --db nokia_docs.db --rn-dir /path/to/release-note-files
python reindex_rn.py nokia_docs.db --rn-dir /path/to/release-note-files
```

### 3. Index Chassis Installation Guide PDFs

The PDF indexer de-duplicates files by Nokia document number and keeps the
highest issue number before parsing.

```bash
nokia-docs index-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
```

To replace existing installation-guide rows:

```bash
nokia-docs reindex-pdf --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
```

Compatibility wrappers:

```bash
python index_pdf.py --db nokia_docs.db --pdf-dir /path/to/chassis-installation-guides
python reindex_pdf.py nokia_docs.db /path/to/chassis-installation-guides
```

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

Core files:

| File | Purpose |
|---|---|
| `src/nokia_docs/cli.py` | CLI entrypoint and command registration |
| `src/nokia_docs/server.py` | FastMCP server and tool definitions |
| `src/nokia_docs/search.py` | Query sanitizing, alias resolution, BM25 search, document retrieval |
| `src/nokia_docs/index.py` | HTML WebHelp indexer |
| `src/nokia_docs/parse.py` | HTML parser for Oxygen WebHelp and NSP HTML |
| `src/nokia_docs/parse_pdf.py` | PDF section extraction and de-duplication helpers |
| `src/nokia_docs/pdf_index.py` | PDF indexing and re-indexing commands |
| `src/nokia_docs/rn.py` | Release-note CSV/JSON indexing and re-indexing commands |
| `src/nokia_docs/db.py` | Shared SQLite schema, insert, and delete helpers |
| `src/nokia_docs/schema.sql` | SQLite tables and FTS5 schema |
| `tests/` | Unit and regression tests |

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
- CLI command registration
- product registry consistency
- HTML and release-note fixture indexing

Run linting for maintained code paths:

```bash
python -m ruff check src tests index_rn.py index_pdf.py reindex_rn.py reindex_pdf.py
```

GitHub Actions runs linting, bytecode compilation, and the full test suite on
push and pull requests.

Some PDF integration tests are skipped unless the local sample PDF path exists.

## Troubleshooting

### `NOKIA_DOCS_DB environment variable is not set`

Set the environment variable before running the server:

```bash
NOKIA_DOCS_DB=/absolute/path/to/nokia_docs.db nokia-docs serve
```

### `Database not found`

Build the database first:

```bash
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset
```

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
