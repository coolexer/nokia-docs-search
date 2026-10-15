---
name: nokia-docs-search
description: >
  Use when the user asks anything about Nokia SR OS, 7250 IXR, 7705 SAR, or 7210 SAS:
  configuration, CLI commands, protocols (BGP, MPLS, RSVP, ISIS, OSPF, EVPN, VPN, QoS,
  OAM, security, interfaces, services, routing, multicast, BFD, LDP, SR-MPLS, SRv6,
  VPRN, VPLS, Epipe, IES, LAG, port configuration, MD-CLI, show commands).
  This skill requires the nokia-docs MCP server to be running.
---

# Nokia Documentation Search

You have access to a local Nokia documentation index via the `nokia-docs` MCP server.

## Available Tools

- **`search_docs(query, product_line?, book?, top_k?)`** — full-text BM25 search
- **`get_document(doc_id, include_neighbors?)`** — read full text of a section
- **`list_products()`** — see what product lines are indexed

## Product Line Slugs

| Slug | Product |
|------|---------|
| `sros-26-3` | Nokia SR OS 26.3 (7750 SR, 7210, 7x50 shared) |
| `7250-ixr` | Nokia 7250 IXR 26.3 R1 |
| `7705-sar-gen2` | Nokia 7705 SAR Gen2 |
| `7705-sar` | Nokia 7705 SAR |
| `7210-sas` | Nokia 7210 SAS 26.3 R1 |

Aliases also work: `sros`, `7750`, `ixr`, `sar`, `sas`.

## How to Answer Nokia Questions

### Step 1 — Search
```
search_docs("rsvp interface configuration", product_line="sros-26-3", top_k=5)
```

For MD-CLI specific questions, include `"md-cli"` or `configure` in the query.

### Step 2 — Read an excerpt
When a snippet is not enough:
```
get_document(doc_id=1234, query="rsvp interface", max_chars=4000)
```
Fetch the full body only when `body_truncated` is true and the excerpt does not contain the answer. Use `get_page_sections` when the page is right but the subsection is unclear. The default window is 40 sections. `max_sections=0` returns the full page map.

### Step 3 — Synthesise answer
Use ONLY content from the retrieved documentation. Do not mix in training knowledge about Nokia CLI.

## Query Tips

- **Hyphenated CLI tokens** are indexed as single tokens: search `hold-time` not `hold time`
- **Phrase search**: `"bgp group configuration"` for exact phrase
- **FTS5 operators**: `bgp AND "hold-time" NOT vpn`
- **Prefix**: `rsvp*` matches rsvp, rsvp-te, rsvp-session, etc.
- **Multiple searches**: If first search returns weak results, try different terms (e.g. `configure router rsvp` instead of `rsvp setup`)

## Answer Format

Always use **MD-CLI syntax** (brace notation). Example:
```sros
configure {
    router "Base" {
        rsvp {
            interface "toR2" {
                admin-state enable
            }
        }
    }
}
```

Include a verification `show` command at the end of configuration answers.

## When No Results Found

1. Try `list_products()` to verify the index is populated
2. Try broader search terms
3. Try without `product_line` filter (search all products)
4. Inform the user that the topic may not be in the current index
