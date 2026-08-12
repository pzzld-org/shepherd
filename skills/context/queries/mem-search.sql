-- usage: shctx query mem-search --q=<term>
SELECT id, kind, title, body, json(tags) AS tags, pinned, created_at
FROM mem_entries
WHERE project_id = :project_id AND (title LIKE :q OR body LIKE :q)
ORDER BY pinned DESC, created_at DESC LIMIT 50;
