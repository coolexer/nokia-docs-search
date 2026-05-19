# nokia-docs-search

Nokia documentation + release notes — full-text search MCP server for Claude Code.

Indexes Nokia WebHelp HTML documentation and release note CSVs into a local SQLite FTS5
database, then exposes three tools over MCP so Claude can search and retrieve content
without leaving the conversation.

---

## Contents

- [What's indexed](#whats-indexed)
- [Quick start](#quick-start)
- [MCP tools](#mcp-tools)
- [Search examples — documentation](#search-examples--documentation)
- [Search examples — release notes](#search-examples--release-notes)
- [Product line slugs and aliases](#product-line-slugs-and-aliases)
- [Building the index](#building-the-index)
- [Re-indexing release notes](#re-indexing-release-notes)
- [Claude Code integration](#claude-code-integration)

---

## What's indexed

| Product line slug | Description | Sections |
|---|---|---|
| `sros-26-3` | Nokia SR OS 26.3 (7750 SR / 7x50) full docs | ~90 000 |
| `srlinux-26-3` | Nokia SR Linux 26.3 full docs | ~40 000 |
| `7250-ixr` | Nokia 7250 IXR 26.3 R1 docs | ~25 000 |
| `7705-sar-gen2` | Nokia 7705 SAR Gen2 docs | ~15 000 |
| `7705-sar` | Nokia 7705 SAR docs | ~10 000 |
| `7210-sas` | Nokia 7210 SAS 26.3 R1 docs | ~10 000 |
| `nsp` | Nokia NSP docs | ~5 000 |
| `rn-sros` | SR OS release notes (all releases + historical EOL) | ~18 000 |
| `rn-srl` | SR Linux release notes | ~4 300 |
| `rn-sas` | Nokia 7210 SAS release notes | ~1 400 |
| `rn-eda` | Nokia EDA release notes | ~920 |
| `rn-mag-c` | Nokia MAG-c release notes | ~270 |

---

## Quick start

```bash
pip install -e .

# Build the documentation index (point at your local Oxygen WebHelp export)
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db

# Index release notes (CSVs must be downloaded first — see below)
python index_rn.py --db nokia_docs.db

# Start the MCP server
NOKIA_DOCS_DB=/path/to/nokia_docs.db nokia-docs serve
```

---

## MCP tools

### `search_docs`

Full-text search with BM25 scoring. Returns up to 50 hits with snippets.

```
search_docs(query, product_line?, book?, top_k?)
```

| Param | Type | Description |
|---|---|---|
| `query` | str | Natural-language query or FTS5 syntax |
| `product_line` | str? | Filter to one product (slug or alias — see below) |
| `book` | str? | Filter by book/section name (e.g. `mpls`, `new-features`) |
| `top_k` | int | Results to return, 1-50 (default 10) |

### `get_document`

Retrieve full body text of a section by its `doc_id` (from a previous search result).

```
get_document(doc_id, include_neighbors?)
```

### `list_products`

List all product lines in the index with section counts and book names.

```
list_products()
```

---

## Search examples — documentation

```
# Find RSVP-TE interface configuration on SR OS
search_docs("rsvp interface configuration", product_line="sros")

# BGP hold-time parameter with FTS5 phrase
search_docs('"bgp hold-time" configure router', product_line="sros")

# EVPN multi-homing on SR Linux
search_docs("EVPN multi-homing all-active", product_line="srlinux")

# Find the MPLS book on 7750 SR
search_docs("LDP FEC", product_line="sros", book="mpls")

# ISIS Segment Routing on IXR
search_docs("isis segment-routing prefix-sid", product_line="ixr")
```

---

## Search examples — release notes

Release notes are the most actionable part of the database: every fix, new feature,
and known issue is a discrete searchable record with release tag, platform, and
functional area.

### What's new in a specific release

```
# All new features introduced in SR OS 26.3.R1
search_docs("new features 26.3.R1", product_line="rn-sros", book="new-features")

# What changed in SR Linux 24.3
search_docs("24.3 new features", product_line="rn-srl")

# EDA 24.11 highlights
search_docs("24.11", product_line="rn-eda", book="new-features")
```

### Resolved issues — did Nokia fix my bug?

```
# Was a BGP route-target memory leak fixed in SR OS?
search_docs("bgp route-target memory leak resolved", product_line="rn-sros", book="resolved-issues")

# OSPF adjacency flap resolved issues across all releases
search_docs("ospf adjacency flap", product_line="rn-sros", book="resolved-issues")

# SR Linux gRPC path fix
search_docs("grpc path resolved", product_line="rn-srl", book="resolved-issues")
```

### Known issues — what's not fixed yet?

```
# Known issues with EVPN Type-5 on SR OS
search_docs("EVPN type-5 known issue", product_line="rn-sros", book="known-issues")

# IS-IS known limitations on SR Linux
search_docs("isis known", product_line="rn-srl", book="known-issues")

# Open issues on MAG-c
search_docs("known issue", product_line="rn-mag-c", book="known-issues")
```

### Feature by functional area

```
# EVPN changes across all SR OS release notes
search_docs("EVPN", product_line="rn-sros")

# Segment Routing new features on SR OS
search_docs("segment routing new features", product_line="rn-sros", book="new-features")

# BNG/CUPS changes in MAG-c
search_docs("BNG subscriber", product_line="rn-mag-c")

# Timing/PTP updates across SR OS RNs
search_docs("PTP IEEE 1588", product_line="rn-sros")
```

### Cross-release version search

The index stores both the full version (`26.3.R1`) and the short form (`26.3`) in the
body, so both formats match:

```
# Both of these return the same results
search_docs("26.3 EVPN resolved", product_line="rn-sros")
search_docs("26.3.R1 EVPN resolved", product_line="rn-sros")
```

### Historical / EOL releases

EOL SR OS releases (pre-20.x) are stored as `rn-sros` under the `historical` book:

```
# Issues resolved in 19.10.R12
search_docs("19.10.R12 resolved", product_line="rn-sros")

# Historical BGP graceful restart issues
search_docs("graceful restart historical", product_line="rn-sros")
```

### Combining with docs for deep dives

A typical workflow — find a bug in RN, then read the config guide:

```
1. search_docs("isis sr-mpls prefix-sid resolved 26.3", product_line="rn-sros")
   → get doc_id of the resolved-issue entry

2. get_document(doc_id)
   → read the RN entry: fix description, platforms, reference number

3. search_docs("isis segment-routing prefix-sid configure", product_line="sros")
   → find the matching config guide section to apply the fix
```

---

## Product line slugs and aliases

The `product_line` parameter accepts both slugs and human-friendly aliases:

| Alias(es) | Resolves to |
|---|---|
| `sros`, `sr os`, `7750` | `sros-26-3` |
| `srl`, `srlinux`, `sr linux` | `srlinux-26-3` |
| `ixr`, `7250`, `7250-ixr` | `7250-ixr` |
| `sar-gen2`, `7705-sar-gen2` | `7705-sar-gen2` |
| `sar`, `7705`, `7705-sar` | `7705-sar` |
| `sas`, `7210`, `7210-sas` | `7210-sas` |
| `nsp` | `nsp` |
| `rn-sros`, `rn sros`, `rn`, `release notes` | `rn-sros` |
| `rn-srl`, `rn srl`, `rn srlinux` | `rn-srl` |
| `rn-sas`, `rn sas` | `rn-sas` |
| `rn-eda`, `rn eda`, `eda` | `rn-eda` |
| `rn-mag-c`, `rn mag-c`, `mag-c` | `rn-mag-c` |

---

## Building the index

```bash
# Full rebuild (delete existing DB)
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --reset

# Incremental (skip already-indexed files)
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db

# Control parallelism (default: CPU count - 1)
nokia-docs index /path/to/nokia-docs-root -o nokia_docs.db --workers 4
```

---

## Re-indexing release notes

Release notes come from Nokia's internal RN portal as CSV files. Download them
separately, place them alongside `index_rn.py`, then run:

```bash
# First-time index (adds to existing nokia_docs.db)
python index_rn.py --db nokia_docs.db

# Drop and re-index all RN product lines
python reindex_rn.py nokia_docs.db
```

Expected CSV files: `rn_sros.csv`, `rn_srl.csv`, `rn_sas.csv`, `rn_mag-c.csv`,
`rn_eda.csv` and `rn_eol.json` (historical SR OS entries).

---

## Claude Code integration

Add to your `claude_desktop_config.json` (or `.claude/settings.json`):

```json
{
  "mcpServers": {
    "nokia-docs": {
      "command": "nokia-docs",
      "args": ["serve"],
      "env": {
        "NOKIA_DOCS_DB": "/absolute/path/to/nokia_docs.db"
      }
    }
  }
}
```

The server uses thread-local read-only SQLite connections and handles concurrent
tool calls safely.
