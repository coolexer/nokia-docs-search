"""FastMCP server — Nokia documentation FTS5 search.

Three tools exposed to Claude:
  search_docs      — full-text search, returns snippets + metadata
  get_document     — retrieve full text of a specific section
  list_products    — list product lines and their books

DB path from environment variable NOKIA_DOCS_DB (required at startup).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from fastmcp import FastMCP

from nokia_docs.db import validate_metadata
from nokia_docs.search import (
    Document,
    Hit,
    ProductInfo,
)
from nokia_docs.search import (
    get_document as _get_document,
)
from nokia_docs.search import (
    list_products as _list_products,
)
from nokia_docs.search import (
    search_docs as _search_docs,
)
from nokia_docs.standards import (
    StandardsHit,
    StandardsProductInfo,
)
from nokia_docs.standards import (
    list_standards_products as _list_standards_products,
)
from nokia_docs.standards import (
    search_standards as _search_standards,
)

# --------------------------------------------------------------------------- #
# DB connection — thread-local read-only connections                            #
# --------------------------------------------------------------------------- #

_db_path: Path | None = None
_tls = threading.local()


def _validate_database(db_path: Path) -> None:
    """Validate that db_path is a readable, compatible search database."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Database is not readable: {db_path}") from exc
    try:
        validate_metadata(conn)
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    """Return a read-only SQLite connection for the current thread.

    Each thread gets its own connection to avoid cursor-state races
    when FastMCP dispatches tool calls concurrently.
    """
    global _db_path

    # Resolve and validate the DB path once (shared across threads)
    if _db_path is None:
        db_path_str = os.environ.get("NOKIA_DOCS_DB", "")
        if not db_path_str:
            raise RuntimeError(
                "NOKIA_DOCS_DB environment variable is not set. "
                "Set it to the path of the nokia_docs.db file."
            )
        p = Path(db_path_str)
        if not p.exists():
            raise RuntimeError(
                f"Database not found: {p}\n"
                "Run: nokia-docs index <docs_root> -o <path/to/nokia_docs.db>"
            )
        _validate_database(p)
        _db_path = p

    # Per-thread connection
    conn: sqlite3.Connection | None = getattr(_tls, "conn", None)
    if conn is None:
        conn = sqlite3.connect(
            f"file:{_db_path}?mode=ro", uri=True, check_same_thread=False
        )
        conn.execute("PRAGMA cache_size=-32000")
        conn.execute("PRAGMA mmap_size=268435456")   # 256 MB memory-mapped I/O
        conn.execute("PRAGMA temp_store=MEMORY")
        _tls.conn = conn
    return conn


# --------------------------------------------------------------------------- #
# MCP server                                                                    #
# --------------------------------------------------------------------------- #

mcp = FastMCP(
    name="nokia-docs",
    instructions=(
        "Nokia documentation and standards search. Use search_docs to find "
        "documentation sections, get_document to read full content, "
        "list_products to see documentation products, search_standards for "
        "standards compliance questions, and list_standards_products to see "
        "indexed standards data."
    ),
)


@mcp.tool()
def search_docs(
    query: str,
    product_line: str | None = None,
    book: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Search Nokia documentation and release notes using full-text search (FTS5/BM25).

    Args:
        query:        Natural-language query or FTS5 syntax.
                      Examples: "rsvp interface configuration",
                                "bgp hold-time", '"md-cli" configure router',
                                "EVPN new features 26.3"
        product_line: Optional filter.
                      Docs slugs : 'sros-26-3', 'srlinux-26-3', 'nsp',
                                   '7250-ixr', '7705-sar-gen2', '7210-sas', '7705-sar'.
                      Docs aliases: 'sros','srlinux','srl','nsp','ixr','sar','sas'.
                      RN slugs  : 'rn-sros', 'rn-srl', 'rn-sas', 'rn-eda', 'rn-mag-c'.
                      RN aliases: 'rn', 'release notes', 'rn sros', 'rn srl', 'eda', 'mag-c'.
        book:         Optional filter by book/section (e.g. 'mpls', 'new-features',
                      'resolved-issues', 'known-issues').
        top_k:        Number of results (1-50, default 10).

    Returns list of hits with doc_id, product_line, book, section_title,
    section_path, snippet (with [[highlighted]] terms), and BM25 score.
    """
    conn = _get_conn()

    hits: list[Hit] = _search_docs(
        query=query,
        conn=conn,
        product_line=product_line,
        book=book,
        top_k=top_k,
    )
    return [
        {
            "doc_id":        h.doc_id,
            "product_line":  h.product_line,
            "book":          h.book,
            "page_title":    h.page_title,
            "section_title": h.section_title,
            "section_path":  h.section_path,
            "rel_path":      h.rel_path,
            "snippet":       h.snippet,
            "score":         round(h.score, 4),
        }
        for h in hits
    ]


@mcp.tool()
def get_document(
    doc_id: int,
    include_neighbors: bool = False,
) -> dict:
    """Get the full text of a documentation section by its doc_id.

    Use doc_id from a previous search_docs call to retrieve complete content.

    Args:
        doc_id:            ID returned by search_docs.
        include_neighbors: If True, also return sibling sections on the same page.

    Returns full body text, metadata, and optionally neighbour section list.
    """
    conn = _get_conn()

    doc: Document | None = _get_document(
        doc_id=doc_id,
        conn=conn,
        include_neighbors=include_neighbors,
    )
    if doc is None:
        return {"error": f"Document {doc_id} not found."}
    return {
        "doc_id":        doc.doc_id,
        "product_line":  doc.product_line,
        "book":          doc.book,
        "page_title":    doc.page_title,
        "section_title": doc.section_title,
        "section_path":  doc.section_path,
        "rel_path":      doc.rel_path,
        "depth":         doc.depth,
        "body":          doc.body,
        "neighbors":     doc.neighbors,
    }


@mcp.tool()
def list_products() -> list[dict]:
    """List all Nokia product lines in the documentation index.

    Returns each product's slug, display name, section count, and book list.
    Call this to know what's available before searching.
    """
    conn = _get_conn()

    products: list[ProductInfo] = _list_products(conn)
    return [
        {
            "slug":         p.slug,
            "display_name": p.display_name,
            "num_sections": p.num_sections,
            "books":        p.books,
        }
        for p in products
    ]


@mcp.tool()
def search_standards(
    query: str | None = None,
    product_line: str | None = None,
    platform: str | None = None,
    release: str | None = None,
    group: str | None = None,
    support_status: str | None = None,
    top_k: int = 20,
) -> list[dict]:
    """Search Nokia standards compliance spreadsheet data.

    Use this for questions like whether SR OS, SR Linux, 7250 IXR, or 7705 SAR
    Gen2 supports a specific RFC, draft, or standards group in a release.
    """
    conn = _get_conn()
    hits: list[StandardsHit] = _search_standards(
        conn=conn,
        query=query,
        product_line=product_line,
        platform=platform,
        release=release,
        group=group,
        support_status=support_status,
        top_k=top_k,
    )
    return [
        {
            "id":             h.id,
            "product_line":   h.product_line,
            "platform":       h.platform,
            "release":        h.release,
            "group_title":    h.group_title,
            "standard_ref":   h.standard_ref,
            "standard_title": h.standard_title,
            "standard_text":  h.standard_text,
            "support_status": h.support_status,
            "source_name":    h.source_name,
            "sheet_name":     h.sheet_name,
            "row_number":     h.row_number,
            "score":          round(h.score, 4),
        }
        for h in hits
    ]


@mcp.tool()
def list_standards_products() -> list[dict]:
    """List indexed standards-compliance products, platforms, releases, and sources."""
    conn = _get_conn()
    products: list[StandardsProductInfo] = _list_standards_products(conn)
    return [
        {
            "product_line": p.product_line,
            "platforms":    p.platforms,
            "releases":     p.releases,
            "num_records":  p.num_records,
            "source_names": p.source_names,
        }
        for p in products
    ]


# --------------------------------------------------------------------------- #
# Entry point                                                                   #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    mcp.run()
