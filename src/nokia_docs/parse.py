"""Parse Nokia documentation HTML files into article chunks.

Supports two formats:
  1. Oxygen WebHelp (SR OS, SR Linux): nested <article> elements inside
     div.wh_topic_content. Each article becomes one Chunk.
  2. NSP custom format: div#core content area, no articles, one Chunk
     per HTML page (body[id] as section_id).

selectolax Lexbor backend: use .text() not .text_content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser, LexborNode

from nokia_docs.products import PRODUCT_PATTERNS

# --------------------------------------------------------------------------- #
# Product line / book detection                                                 #
# --------------------------------------------------------------------------- #

# Order matters: more-specific patterns must come before substrings they contain.
_PRODUCT_PATTERNS: list[tuple[str, str]] = [
    # SR Linux — must come before "26-3" to avoid mis-classification
    ("SR Linux",               "srlinux-26-3"),
    ("sr-linux",               "srlinux-26-3"),
    ("srlinux",                "srlinux-26-3"),
    # NSP
    ("NSP webdocs",            "nsp"),
    ("webdocs-enus",           "nsp"),
    # SR OS
    ("26-3",                   "sros-26-3"),
    ("7250_ixr",               "7250-ixr"),
    ("7250_IXR",               "7250-ixr"),
    ("7705 sar gen2",          "7705-sar-gen2"),
    ("7705_sar_gen2",          "7705-sar-gen2"),
    ("7705 sar",               "7705-sar"),
    ("7705_sar",               "7705-sar"),
    ("7210_sas",               "7210-sas"),
    ("7210_SAS",               "7210-sas"),
    ("7x50-shared",            "sros-26-3"),
]


def _detect_product(rel_path: str) -> str:
    """Detect product slug from ALL path parts (most-specific match wins)."""
    parts = Path(rel_path).parts
    for part in parts:
        part_lower = part.lower()
        for pattern, slug in PRODUCT_PATTERNS:
            if pattern.lower() in part_lower:
                return slug
    return parts[0].lower().replace(" ", "-") if parts else "unknown"


def _detect_book(rel_path: str) -> str:
    """Extract book name from path. Handles both WebHelp and NSP layouts."""
    parts = Path(rel_path).parts
    # WebHelp: .../books/<book-name>/page.html
    for i, p in enumerate(parts):
        if p == "books" and i + 1 < len(parts):
            return parts[i + 1]
    # NSP: .../<Guide_Name>/page.html  (parent folder is the "book")
    return parts[-2] if len(parts) >= 2 else "unknown"


# --------------------------------------------------------------------------- #
# Text helpers                                                                  #
# --------------------------------------------------------------------------- #

def _clean(text: str) -> str:
    text = re.sub(r"[^\S\n]+", " ", text)   # collapse spaces incl. \xa0 (non-breaking)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _node_text(node: LexborNode) -> str:
    return node.text(deep=True, separator=" ", strip=True) or ""


_TITLE_CLASS_RE = re.compile(r"\btitle\b")


# --------------------------------------------------------------------------- #
# Chunk dataclass                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class Chunk:
    product_line:  str
    book:          str
    rel_path:      str
    page_title:    str
    section_id:    str
    section_title: str
    section_path:  str
    depth:         int
    body:          str

    @property
    def char_len(self) -> int:
        return len(self.body)


# --------------------------------------------------------------------------- #
# Format 1: Oxygen WebHelp parser (SR OS, SR Linux)                            #
# --------------------------------------------------------------------------- #

def _own_body(article: LexborNode) -> str:
    """Text of `article` excluding text of its descendant <article> elements."""
    clone_tree = LexborHTMLParser(article.html or "")
    all_arts = clone_tree.css("article")
    for sub in all_arts[1:]:
        try:
            sub.decompose()
        except Exception:
            pass
    # Strip boilerplate that WebHelp sometimes injects inside topic content.
    for sel in (".related-links", ".linklist", "nav", "footer"):
        for node in clone_tree.css(sel):
            try:
                node.decompose()
            except Exception:
                pass
    root = all_arts[0] if all_arts else clone_tree.root
    if root is None:
        return ""
    return _clean(root.text(deep=True, separator=" ", strip=True) or "")


def _first_heading_direct(article: LexborNode) -> str:
    """First h1-h6 NOT inside a nested <article>. Falls back to aria-labelledby."""
    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def _walk(node: LexborNode) -> str:
        for child in node.iter():   # direct children only in selectolax-lexbor
            tag = (child.tag or "").lower()
            if tag == "article":
                continue
            if tag in HEADINGS:
                return _clean(child.text(deep=True, separator=" ", strip=True) or "")
            # DITA div/p/span acting as heading via class="...title..."
            cls = child.attributes.get("class") or ""
            if tag in ("div", "p", "span") and _TITLE_CLASS_RE.search(cls):
                txt = _clean(child.text(deep=True, separator=" ", strip=True) or "")
                if txt:
                    return txt
            found = _walk(child)
            if found:
                return found
        return ""

    result = _walk(article)
    if result:
        return result

    # Last resort: aria-labelledby
    labelled_id = article.attributes.get("aria-labelledby")
    if labelled_id:
        for node in article.css(f"#{labelled_id}"):
            txt = _clean(node.text(deep=True, separator=" ", strip=True) or "")
            if txt:
                return txt
    return ""


def _depth_from_class(article: LexborNode, rec_depth: int = 0) -> int:
    """Nesting depth from DITA class attribute; falls back to recursion counter."""
    cls = article.attributes.get("class", "")
    for part in cls.split():
        if part.startswith("nested"):
            try:
                return int(part[6:])
            except ValueError:
                pass
    return rec_depth


def _parse_webhelp(
    tree: LexborHTMLParser,
    rel_path: str,
    page_title: str,
    product_line: str,
    book: str,
) -> list[Chunk]:
    """Parse Oxygen WebHelp format (SR OS, SR Linux)."""
    content_div: LexborNode | None = None
    for div in tree.css("div"):
        if "wh_topic_content" in (div.attributes.get("class") or ""):
            content_div = div
            break
    if content_div is None:
        return []

    chunks: list[Chunk] = []

    def _process(art: LexborNode, ancestor_titles: list[str], rec_depth: int = 0) -> None:
        section_id = (art.attributes.get("id") or "").strip()
        if not section_id:
            for child in art.iter():
                if (child.tag or "").lower() == "article":
                    _process(child, ancestor_titles, rec_depth)
            return

        section_title = _first_heading_direct(art) or section_id
        depth = _depth_from_class(art, rec_depth)
        section_path = " > ".join(ancestor_titles + [section_title])
        body = _own_body(art)

        if body or section_title:
            chunks.append(Chunk(
                product_line=product_line,
                book=book,
                rel_path=rel_path,
                page_title=page_title,
                section_id=section_id,
                section_title=section_title,
                section_path=section_path,
                depth=depth,
                body=body,
            ))

        for child in art.iter():
            if (child.tag or "").lower() == "article":
                _process(child, ancestor_titles + [section_title], rec_depth + 1)

    # Top-level articles: those whose parent is NOT an article.
    for art in content_div.css("article"):
        parent = art.parent
        if parent is not None and (parent.tag or "").lower() != "article":
            _process(art, [], 0)

    return chunks


# --------------------------------------------------------------------------- #
# Format 2: NSP custom HTML parser                                              #
# --------------------------------------------------------------------------- #

# NSP nav/index pages to skip
_NSP_SKIP_NAMES = {
    "index.html", "testgui.html", "ipmtoc.html",
    "ipabout.html", "iplegal.html", "iploe.html",
}


def _parse_nsp(
    tree: LexborHTMLParser,
    html_path: Path,
    rel_path: str,
    page_title: str,
    product_line: str,
    book: str,
) -> list[Chunk]:
    """Parse NSP custom HTML format (one Chunk per page)."""
    if html_path.name in _NSP_SKIP_NAMES:
        return []

    core = tree.css_first("#core")
    if core is None:
        return []

    # Skip pure TOC pages (only pTOC* paragraphs, no real content)
    headings = core.css("h1,h2,h3,h4,h5,h6")
    if not headings:
        return []

    # Section ID from <body id="...">
    body_el = tree.css_first("body")
    section_id = (body_el.attributes.get("id") or "").strip() if body_el else ""
    if not section_id:
        section_id = html_path.stem

    # Main heading: prefer h4.pMapTitle (NSP chapter title), then any h1-h4
    section_title = ""
    for h in headings:
        cls = h.attributes.get("class") or ""
        txt = _clean(h.text(deep=True, separator=" ", strip=True) or "")
        if txt and ("pMapTitle" in cls or (h.tag or "") in ("h1", "h2", "h3")):
            section_title = txt
            break
    if not section_title:
        # First heading of any kind
        for h in headings:
            txt = _clean(h.text(deep=True, separator=" ", strip=True) or "")
            if txt:
                section_title = txt
                break
    if not section_title:
        section_title = page_title or section_id

    # Remove nav/boilerplate before extracting body text
    clone_tree = LexborHTMLParser(core.html or "")
    for sel in ("nav", "header", "footer", ".breadcrumb", ".nav", ".navbar",
                "#page_header", ".wh_header", ".wh_footer"):
        for node in clone_tree.css(sel):
            try:
                node.decompose()
            except Exception:
                pass
    root = clone_tree.css_first("#core") or clone_tree.root
    body = _clean((root.text(deep=True, separator=" ", strip=True) if root else "") or "")

    if not body:
        return []

    return [Chunk(
        product_line=product_line,
        book=book,
        rel_path=rel_path,
        page_title=page_title,
        section_id=section_id,
        section_title=section_title,
        section_path=section_title,
        depth=0,
        body=body,
    )]


# --------------------------------------------------------------------------- #
# Main entry point                                                              #
# --------------------------------------------------------------------------- #

def parse_html(html_path: Path, docs_root: Path) -> list[Chunk]:
    """Parse one Nokia documentation HTML file. Returns [] for nav pages."""
    try:
        raw = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    tree = LexborHTMLParser(raw)

    # Page title — prefer <head title> to avoid inline SVG <title> tags.
    title_el = tree.css_first("head title") or tree.css_first("title")
    page_title = _clean(title_el.text(deep=True, strip=True) or "") if title_el else html_path.stem

    rel_path = str(html_path.relative_to(docs_root)).replace("\\", "/")
    product_line = _detect_product(rel_path)
    book = _detect_book(rel_path)

    # Detect format and dispatch.
    if tree.css_first("#core") is not None and not tree.css("article"):
        # NSP custom format
        return _parse_nsp(tree, html_path, rel_path, page_title, product_line, book)
    else:
        # Oxygen WebHelp format (SR OS, SR Linux)
        return _parse_webhelp(tree, rel_path, page_title, product_line, book)
