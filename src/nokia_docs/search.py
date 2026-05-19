"""FTS5 search layer for Nokia docs.

search_docs(query, conn, product_line?, book?, top_k?) -> list[Hit]
get_document(doc_id, conn, include_neighbors?) -> Document | None
list_products(conn) -> list[ProductInfo]
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Result types                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class Hit:
    doc_id:        int
    product_line:  str
    book:          str
    page_title:    str
    section_title: str
    section_path:  str
    rel_path:      str
    snippet:       str
    score:         float


@dataclass
class Document:
    doc_id:        int
    product_line:  str
    book:          str
    page_title:    str
    section_title: str
    section_path:  str
    rel_path:      str
    depth:         int
    body:          str
    neighbors:     list[dict] = field(default_factory=list)  # only if include_neighbors=True


@dataclass
class ProductInfo:
    slug:         str
    display_name: str
    num_sections: int
    books:        list[str]


# --------------------------------------------------------------------------- #
# Product alias resolution                                                      #
# --------------------------------------------------------------------------- #

_ALIASES: dict[str, str] = {
    # SR Linux
    "srlinux":     "srlinux-26-3",
    "sr linux":    "srlinux-26-3",
    "sr-linux":    "srlinux-26-3",
    "srl":         "srlinux-26-3",
    # NSP
    "nsp":         "nsp",
    # SR OS
    "sros":        "sros-26-3",
    "sr os":       "sros-26-3",
    "sr-os":       "sros-26-3",
    "sros-26-3":   "sros-26-3",
    "sros 26.3":   "sros-26-3",
    "sros26":      "sros-26-3",
    "7750":        "sros-26-3",
    "7750-sr":     "sros-26-3",
    "ixr":         "7250-ixr",
    "7250":        "7250-ixr",
    "7250 ixr":    "7250-ixr",
    "7250-ixr":    "7250-ixr",
    "sar-gen2":    "7705-sar-gen2",
    "sar gen2":    "7705-sar-gen2",
    "7705-sar-gen2": "7705-sar-gen2",
    "7705 sar gen2": "7705-sar-gen2",
    "sar":         "7705-sar",
    "7705":        "7705-sar",
    "7705-sar":    "7705-sar",
    "7705 sar":    "7705-sar",
    "sas":         "7210-sas",
    "7210":        "7210-sas",
    "7210-sas":    "7210-sas",
    "7210 sas":    "7210-sas",
    # Release Notes
    "rn":               "rn-sros",
    "rn sros":          "rn-sros",
    "sros rn":          "rn-sros",
    "release notes":    "rn-sros",
    "release notes sros": "rn-sros",
    "rn-sros":          "rn-sros",
    "rn srl":           "rn-srl",
    "rn srlinux":       "rn-srl",
    "srl rn":           "rn-srl",
    "srlinux rn":       "rn-srl",
    "release notes srlinux": "rn-srl",
    "rn-srl":           "rn-srl",
    "rn sas":           "rn-sas",
    "rn-sas":           "rn-sas",
    "rn eda":           "rn-eda",
    "rn-eda":           "rn-eda",
    "eda":              "rn-eda",
    "rn mag-c":         "rn-mag-c",
    "rn magc":          "rn-mag-c",
    "rn-mag-c":         "rn-mag-c",
    "mag-c":            "rn-mag-c",
    "magc":             "rn-mag-c",
}


def _resolve_product(product_line: str | None) -> str | None:
    if not product_line:
        return None
    # Normalize: lowercase, collapse whitespace/underscores/hyphens → spaces
    # (aliases are stored with spaces; hyphens in slugs are preserved by exact lookup)
    normalized_spaces = re.sub(r"[\s_]+", " ", product_line.strip().lower())
    if normalized_spaces in _ALIASES:
        return _ALIASES[normalized_spaces]
    # Also try with hyphens collapsed to spaces (e.g. "rn-sros" → "rn sros")
    normalized_no_hyphen = re.sub(r"[\s_\-]+", " ", product_line.strip().lower())
    if normalized_no_hyphen in _ALIASES:
        return _ALIASES[normalized_no_hyphen]
    # Fall back to the original slug as-is (allows direct slug pass-through)
    return normalized_spaces


# --------------------------------------------------------------------------- #
# Query sanitizer                                                               #
# --------------------------------------------------------------------------- #

def _sanitize_query(query: str) -> str:
    """Convert a natural-language query into an FTS5 query string.

    Rules:
    - Empty / whitespace-only → returns "" (caller should return [] early).
    - Quoted phrases ("hold-time") pass through.
    - Explicit FTS5 operators (AND, OR, NOT, +, *) pass through.
    - Everything else: individual tokens joined with implicit AND,
      phrase form first (high score) + individual words (recall).
    """
    query = query.strip()
    if not query:
        return ""   # Caller checks for empty and returns [] early.

    # If the user is using FTS5 syntax explicitly, pass through.
    # Use word-boundary regex so words like "standby", "random", "sandbox"
    # don't accidentally match the substring "AND"/"OR"/"NOT".
    if re.search(r'\b(AND|OR|NOT)\b', query) or any(op in query for op in (" + ", " * ")):
        return query

    # If already fully quoted, pass through.
    if query.startswith('"') and query.endswith('"'):
        return query

    # Extract quoted sub-phrases first; strip stray quotes from bare portion
    # to avoid unbalanced-quote FTS5 parse errors.
    quoted: list[str] = []
    bare = re.sub(r'"[^"]*"', lambda m: (quoted.append(m.group()) or ""), query)
    bare = bare.replace('"', "")   # drop any unmatched stray quotes

    # Tokenise bare words.
    words = [w for w in re.split(r"\s+", bare.strip()) if w]

    parts: list[str] = list(quoted)
    if words:
        if len(words) == 1:
            parts.append(f'"{words[0]}"*')
        else:
            # Exact phrase first (high score) + individual words (recall)
            phrase = " ".join(words)
            individual = " ".join(f'"{w}"' for w in words)
            parts.append(f'"{phrase}" OR ({individual})')

    return " ".join(parts) if parts else ""


# --------------------------------------------------------------------------- #
# search_docs                                                                   #
# --------------------------------------------------------------------------- #

_BM25_WEIGHTS = "10.0, 5.0, 3.0, 1.0"  # section_title, page_title, section_path, body


def search_docs(
    query: str,
    conn: sqlite3.Connection,
    product_line: str | None = None,
    book: str | None = None,
    top_k: int = 10,
) -> list[Hit]:
    """Full-text search across Nokia documentation.

    Args:
        query:        Natural-language or FTS5 query string.
        conn:         Open SQLite connection.
        product_line: Optional filter slug (e.g. 'sros-26-3', '7250-ixr').
                      Accepts aliases: 'sros', '7750', 'ixr', 'sar', 'sas'.
        book:         Optional filter by book folder name.
        top_k:        Max results to return (default 10, max 50).

    Returns list of Hit objects ordered by relevance.
    """
    top_k = max(1, min(top_k, 50))
    fts_query = _sanitize_query(query)
    if not fts_query:
        return []   # empty / whitespace-only query — nothing to search
    resolved_product = _resolve_product(product_line)

    # Build WHERE clause additions.
    extra_where = ""
    params: list = [fts_query]

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
            snippet(docs_fts, 3, '[[', ']]', '…', 32) AS snip,
            bm25(docs_fts, {_BM25_WEIGHTS})            AS score
        FROM docs_fts
        JOIN docs d ON docs_fts.rowid = d.id
        WHERE docs_fts MATCH ?
          {extra_where}
        ORDER BY score
        LIMIT ?
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # FTS5 query parse error — fall back to escaped literal search.
        escaped = '"' + query.replace('"', '""') + '"'
        params[0] = escaped
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

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
            score=-r[8],   # bm25() is negative-better; negate so higher = better
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# get_document                                                                  #
# --------------------------------------------------------------------------- #

def get_document(
    doc_id: int,
    conn: sqlite3.Connection,
    include_neighbors: bool = False,
) -> Document | None:
    """Retrieve full text of a specific document section by ID."""
    row = conn.execute(
        """SELECT d.id, d.product_line, d.book, d.page_title,
                  d.section_title, d.section_path, d.rel_path, d.depth,
                  b.body
           FROM docs d
           JOIN docs_body b ON d.id = b.id
           WHERE d.id = ?""",
        (doc_id,),
    ).fetchone()

    if not row:
        return None

    doc = Document(
        doc_id=row[0],
        product_line=row[1],
        book=row[2],
        page_title=row[3],
        section_title=row[4],
        section_path=row[5],
        rel_path=row[6],
        depth=row[7],
        body=row[8],
    )

    if include_neighbors:
        # Same page: return sibling sections (same rel_path, up to 10).
        siblings = conn.execute(
            """SELECT d.id, d.section_title, d.depth
               FROM docs d
               WHERE d.rel_path = ? AND d.id != ?
               ORDER BY d.id
               LIMIT 10""",
            (doc.rel_path, doc_id),
        ).fetchall()
        doc.neighbors = [
            {"doc_id": r[0], "section_title": r[1], "depth": r[2]}
            for r in siblings
        ]

    return doc


# --------------------------------------------------------------------------- #
# list_products                                                                 #
# --------------------------------------------------------------------------- #

_DISPLAY_NAMES: dict[str, str] = {
    # Documentation
    "sros-26-3":     "Nokia SR OS 26.3 (7750 SR / 7x50)",
    "srlinux-26-3":  "Nokia SR Linux 26.3",
    "7250-ixr":      "Nokia 7250 IXR 26.3 R1",
    "7705-sar-gen2": "Nokia 7705 SAR Gen2",
    "7705-sar":      "Nokia 7705 SAR",
    "7210-sas":      "Nokia 7210 SAS 26.3 R1",
    "nsp":           "Nokia NSP",
    # Release Notes
    "rn-sros":       "Nokia SR OS Release Notes",
    "rn-srl":        "Nokia SR Linux Release Notes",
    "rn-sas":        "Nokia 7210 SAS Release Notes",
    "rn-eda":        "Nokia EDA Release Notes",
    "rn-mag-c":      "Nokia MAG-c Release Notes",
}


def list_products(conn: sqlite3.Connection) -> list[ProductInfo]:
    """List all product lines in the index with their books."""
    rows = conn.execute(
        """SELECT product_line, COUNT(*) as n
           FROM docs GROUP BY product_line ORDER BY n DESC"""
    ).fetchall()

    result = []
    for product_slug, n_sections in rows:
        books = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT book FROM docs WHERE product_line=? ORDER BY book",
                (product_slug,),
            ).fetchall()
        ]
        result.append(ProductInfo(
            slug=product_slug,
            display_name=_DISPLAY_NAMES.get(product_slug, product_slug),
            num_sections=n_sections,
            books=books,
        ))
    return result
