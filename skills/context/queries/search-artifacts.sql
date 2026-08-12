-- usage: shctx query search-artifacts --q="<fts5 expression>" [--limit=20]
-- FTS5 search over artifact content (path + title + content).
SELECT a.kind, a.path, a.title, a.sprint_branch,
       snippet(index_fts_artifacts, 2, '«', '»', ' … ', 12) AS context,
       bm25(index_fts_artifacts) AS rank
FROM index_fts_artifacts
JOIN artifacts a ON a.rowid = index_fts_artifacts.rowid
WHERE index_fts_artifacts MATCH :q
  AND a.project_id = :project_id
ORDER BY rank
LIMIT COALESCE(:limit, 20);
