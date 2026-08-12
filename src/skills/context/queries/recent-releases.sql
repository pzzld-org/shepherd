-- usage: shctx query recent-releases
SELECT tag, name, prerelease, draft, url, published_at
FROM index_releases WHERE project_id = :project_id
ORDER BY published_at DESC LIMIT 25;
