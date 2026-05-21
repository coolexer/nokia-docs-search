"""FTS5 search layer for Nokia documentation."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from nokia_docs.products import PRODUCT_DISPLAY_NAMES, resolve_product


@dataclass
class Hit:
    doc_id: int
    product_line: str
    book: str
    page_title: str
    section_title: str
    section_path: str
    rel_path: str
    snippet: str
    score: float


@dataclass
class Document:
    doc_id: int
    product_line: str
    book: str
    page_title: str
    section_title: str
    section_path: str
    rel_path: str
    depth: int
    body: str
    neighbors: list[dict] = field(default_factory=list)


@dataclass
class ProductInfo:
    slug: str
    display_name: str
    num_sections: int
    books: list[str]


def _resolve_product(product_line: str | None) -> str | None:
    """Compatibility wrapper around the central product registry."""
    return resolve_product(product_line)


def _sanitize_query(query: str) -> str:
    """Convert natural-language input into an FTS5 query.

    Explicit FTS5 syntax is passed through. For plain multi-word input, use an
    exact phrase for ranking plus prefix-matched AND terms for recall. Prefix
    terms are important because the tokenizer keeps "." as part of tokens, so a
    word at sentence end can be indexed as ``word.``.
    """
    query = query.strip()
    if not query:
        return ""

    if re.search(r"\b(AND|OR|NOT|NEAR)\b", query) or any(op in query for op in (" + ", "*")):
        return query

    if query.startswith('"') and query.endswith('"'):
        return query

    quoted: list[str] = []
    bare = re.sub(r'"[^"]*"', lambda m: (quoted.append(m.group()) or ""), query)
    bare = bare.replace('"', "")
    words = [w for w in re.split(r"\s+", bare.strip()) if w]

    parts: list[str] = list(quoted)
    if words:
        if len(words) == 1:
            parts.append(f'"{words[0]}"*')
        else:
            phrase = " ".join(words)
            individual = " AND ".join(f'"{w}"*' for w in words)
            parts.append(f'"{phrase}" OR ({individual})')

    return " ".join(parts) if parts else ""


_BM25_WEIGHTS = "10.0, 5.0, 3.0, 1.0"


def search_docs(
    query: str,
    conn: sqlite3.Connection,
    product_line: str | None = None,
    book: str | None = None,
    top_k: int = 10,
) -> list[Hit]:
    """Full-text search across Nokia documentation."""
    top_k = max(1, min(top_k, 50))
    fts_query = _sanitize_query(query)
    if not fts_query:
        return []

    extra_where = ""
    params: list = [fts_query]
    resolved_product = resolve_product(product_line)

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
            snippet(docs_fts, 3, '[[', ']]', '...', 32) AS snip,
            bm25(docs_fts, {_BM25_WEIGHTS}) AS score
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
        params[0] = '"' + query.replace('"', '""') + '"'
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
            score=-r[8],
        )
        for r in rows
    ]


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


def list_products(conn: sqlite3.Connection) -> list[ProductInfo]:
    """List all product lines in the index with their books."""
    rows = conn.execute(
        """SELECT product_line, COUNT(*) as n
           FROM docs GROUP BY product_line ORDER BY n DESC"""
    ).fetchall()

    result = []
    for product_slug, n_sections in rows:
        books = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT book FROM docs WHERE product_line=? ORDER BY book",
                (product_slug,),
            ).fetchall()
        ]
        result.append(
            ProductInfo(
                slug=product_slug,
                display_name=PRODUCT_DISPLAY_NAMES.get(product_slug, product_slug),
                num_sections=n_sections,
                books=books,
            )
        )
    return result
