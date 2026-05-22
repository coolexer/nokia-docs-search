-- Nokia Docs FTS5 schema
-- One row per <article> element extracted from Oxygen WebHelp HTML files.

CREATE TABLE IF NOT EXISTS docs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_line   TEXT NOT NULL,   -- e.g. 'sros-26-3', '7250-ixr', '7705-sar-gen2', '7210-sas', '7705-sar'
    book           TEXT NOT NULL,   -- folder name under books/, e.g. 'mpls', 'bng-cups-upf'
    rel_path       TEXT NOT NULL,   -- relative to docs root, e.g. '26-3/7750-sr/books/mpls/mpls-overview.html'
    page_title     TEXT NOT NULL,   -- <title> of the HTML page
    section_id     TEXT NOT NULL,   -- id attribute of the <article> element
    section_title  TEXT NOT NULL,   -- first <h1/h2/h3> inside the article (not in nested articles)
    section_path   TEXT NOT NULL,   -- breadcrumb: 'Book > Parent Section > This Section'
    depth          INTEGER NOT NULL DEFAULT 0,  -- nesting depth (0 = page root article)
    char_len       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(rel_path, section_id)
);

CREATE INDEX IF NOT EXISTS idx_docs_product ON docs(product_line);
CREATE INDEX IF NOT EXISTS idx_docs_book    ON docs(product_line, book);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS build_manifest (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Separate body table for get_document (full text retrieval without FTS5 overhead).
CREATE TABLE IF NOT EXISTS docs_body (
    id   INTEGER PRIMARY KEY,  -- same rowid as docs.id
    body TEXT NOT NULL
);

-- Regular FTS5 table (stores its own content — simplest, snippet() works out of box).
-- Weights (via bm25 column order): section_title=10, page_title=5, section_path=3, body=1
-- tokenchars '-_.' keeps hyphenated CLI tokens (hold-time, bgp-vpn) as single tokens.
--
-- NOTE: re-running `nokia-docs index` without --reset uses INSERT OR IGNORE on docs
-- and skips existing FTS rows. Always use --reset to rebuild from scratch.
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    section_title,
    page_title,
    section_path,
    body,
    tokenize = "unicode61 remove_diacritics 2 tokenchars '-_.'"
);
