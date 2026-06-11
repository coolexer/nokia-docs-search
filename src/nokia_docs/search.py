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
    match_mode: str = "strict"


@dataclass(frozen=True)
class SearchCandidate:
    match_mode: str
    fts_query: str
    important_terms: list[str]


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


_NOISE_TERMS = {
    "7250", "7750", "7705", "7210", "7450", "7950",
    "IXR", "IXR-e", "IXR-e2", "SR", "SR-1", "SR-2", "VSR",
}
_NOISE_TERMS_NORMALIZED = {term.casefold() for term in _NOISE_TERMS}

_MEANINGFUL_SHORT_TERMS = {"AD", "AS", "IP", "L2", "L3", "PTP", "BGP", "QoS"}
_MEANINGFUL_SHORT_TERMS_NORMALIZED = {
    term.casefold() for term in _MEANINGFUL_SHORT_TERMS
}

_VARIANT_REPLACEMENTS = {
    "signalling": ["signaling"],
    "signaling": ["signalling"],
    "BGP-AD": ["BGP AD"],
    "auto-discovery": ["auto discovery"],
    "AS path": ["AS-path"],
    "AS-path": ["AS path"],
    "QoS": ["QOS"],
    "QOS": ["QoS"],
}


def _is_explicit_fts(query: str) -> bool:
    return bool(re.search(r"\b(AND|OR|NOT|NEAR)\b", query)) or any(
        op in query for op in (" + ", "*")
    )


def _query_words(query: str) -> list[str]:
    bare = re.sub(r'"[^"]*"', " ", query).replace('"', " ")
    return [w for w in re.split(r"\s+", bare.strip()) if w]


def _quote_prefix(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"*'


def _and_query(terms: list[str]) -> str:
    return " AND ".join(_quote_prefix(term) for term in terms)


def _or_query(terms: list[str]) -> str:
    return " OR ".join(_quote_prefix(term) for term in terms)


def _strict_query(query: str, terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return _quote_prefix(terms[0])
    phrase = " ".join(terms).replace('"', '""')
    return f'"{phrase}" OR ({_and_query(terms)})'


def _is_release_like(term: str) -> bool:
    return bool(re.fullmatch(r"\d{2}\.\d+(?:\.R\d+)?", term))


def _relaxed_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    skip_next_class_letter = False
    for term in terms:
        normalized = term.strip(",;()[]")
        normalized_noise = normalized.casefold()
        if skip_next_class_letter and re.fullmatch(r"[A-Za-z]", normalized):
            skip_next_class_letter = False
            continue
        if normalized.lower() == "class":
            skip_next_class_letter = True
            continue
        skip_next_class_letter = False
        if normalized_noise in _NOISE_TERMS_NORMALIZED or _is_release_like(normalized):
            continue
        if (
            len(normalized) <= 2
            and normalized.casefold() not in _MEANINGFUL_SHORT_TERMS_NORMALIZED
        ):
            continue
        result.append(normalized)
    return result


def _variant_term_sets(query: str, terms: list[str]) -> list[list[str]]:
    variants: list[list[str]] = []
    for source, replacements in _VARIANT_REPLACEMENTS.items():
        if source in query:
            for replacement in replacements:
                variant_query = query.replace(source, replacement)
                variant_terms = _relaxed_terms(_query_words(variant_query))
                if variant_terms and variant_terms != terms and variant_terms not in variants:
                    variants.append(variant_terms)
    for term in terms:
        if "-" in term:
            candidate = [
                part
                for t in terms
                for part in (t.split("-") if t == term else [t])
            ]
            if candidate not in variants:
                variants.append(candidate)
    return variants


def plan_search_queries(query: str) -> list[SearchCandidate]:
    """Build ordered FTS candidates for strict and fallback documentation search."""
    query = query.strip()
    if not query:
        return []
    if _is_explicit_fts(query) or '"' in query:
        return [SearchCandidate("strict", query, _query_words(query))]

    terms = _query_words(query)
    candidates: list[SearchCandidate] = []
    strict = _strict_query(query, terms)
    if strict:
        candidates.append(SearchCandidate("strict", strict, terms))

    relaxed_terms = _relaxed_terms(terms)
    if relaxed_terms and relaxed_terms != terms:
        candidates.append(
            SearchCandidate(
                "relaxed",
                _strict_query(" ".join(relaxed_terms), relaxed_terms),
                relaxed_terms,
            )
        )

    for variant_terms in _variant_term_sets(query, relaxed_terms or terms):
        candidates.append(
            SearchCandidate(
                "variant",
                _strict_query(" ".join(variant_terms), variant_terms),
                variant_terms,
            )
        )

    soft_terms = relaxed_terms or terms
    if len(soft_terms) > 1:
        candidates.append(SearchCandidate("soft", _or_query(soft_terms), soft_terms))

    unique: list[SearchCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.match_mode, candidate.fts_query)
        if key not in seen and candidate.fts_query:
            unique.append(candidate)
            seen.add(key)
    return unique


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

    candidates = plan_search_queries(query)
    return candidates[0].fts_query if candidates else ""


_BM25_WEIGHTS = "10.0, 5.0, 3.0, 1.0"


def _run_fts_search(
    fts_query: str,
    conn: sqlite3.Connection,
    product_line: str | None = None,
    book: str | None = None,
    top_k: int = 10,
    match_mode: str = "strict",
) -> list[Hit]:
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

    rows = conn.execute(sql, params).fetchall()

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
            match_mode=match_mode,
        )
        for r in rows
    ]


def _term_present(term: str, text: str) -> bool:
    normalized_term = term.lower().replace("-", " ")
    normalized_text = text.lower().replace("-", " ")
    pattern = rf"(?<![A-Za-z0-9.]){re.escape(normalized_term)}(?![A-Za-z0-9.])"
    return bool(re.search(pattern, normalized_text))


def _soft_match_count(hit: Hit, terms: list[str]) -> int:
    haystack = " ".join([hit.page_title, hit.section_title, hit.section_path, hit.snippet])
    return sum(1 for term in terms if _term_present(term, haystack))


def _soft_title_path_count(hit: Hit, terms: list[str]) -> int:
    haystack = " ".join([hit.page_title, hit.section_title, hit.section_path])
    return sum(1 for term in terms if _term_present(term, haystack))


def _rank_soft_hits(hits: list[Hit], terms: list[str]) -> list[Hit]:
    return sorted(
        hits,
        key=lambda hit: (
            -_soft_match_count(hit, terms),
            -_soft_title_path_count(hit, terms),
            -hit.score,
            hit.doc_id,
        ),
    )


def search_docs(
    query: str,
    conn: sqlite3.Connection,
    product_line: str | None = None,
    book: str | None = None,
    top_k: int = 10,
) -> list[Hit]:
    """Full-text search across Nokia documentation."""
    top_k = max(1, min(top_k, 50))
    candidates = plan_search_queries(query)
    if not candidates:
        return []

    enough_hits = min(top_k, 3)
    fallback_rows: list[Hit] = []
    seen_doc_ids: set[int] = set()

    for candidate in candidates:
        try:
            hits = _run_fts_search(
                candidate.fts_query,
                conn,
                product_line=product_line,
                book=book,
                top_k=top_k,
                match_mode=candidate.match_mode,
            )
        except sqlite3.OperationalError:
            if candidate.match_mode != "strict":
                continue
            escaped_query = '"' + query.replace('"', '""') + '"'
            try:
                hits = _run_fts_search(
                    escaped_query,
                    conn,
                    product_line=product_line,
                    book=book,
                    top_k=top_k,
                    match_mode=candidate.match_mode,
                )
            except sqlite3.OperationalError:
                hits = []

        if candidate.match_mode == "soft":
            hits = _rank_soft_hits(hits, candidate.important_terms)
        elif candidate.match_mode == "strict" and len(hits) >= enough_hits:
            return hits[:top_k]

        added_from_candidate = False
        for hit in hits:
            if hit.doc_id in seen_doc_ids:
                continue
            fallback_rows.append(hit)
            seen_doc_ids.add(hit.doc_id)
            added_from_candidate = True

        if added_from_candidate and candidate.match_mode != "strict":
            return fallback_rows[:top_k]

    return fallback_rows[:top_k]


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
