-- usage: shctx query search-symbols --q="<fts5 expression>" [--limit=20]
-- FTS5 search over public symbols (name + signature + doc_summary).
-- Falls back gracefully if FTS isn't available (returns empty); use
-- `shctx search` for the user-facing search subcommand.
SELECT s.package, s.kind, s.name, s.signature, s.file_path, s.line,
       bm25(index_fts_symbols) AS rank
FROM index_fts_symbols
JOIN index_symbols s ON s.rowid = index_fts_symbols.rowid
WHERE index_fts_symbols MATCH :q
  AND s.project_id = :project_id
ORDER BY rank
LIMIT COALESCE(:limit, 20);
