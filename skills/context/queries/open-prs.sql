-- usage: shctx query open-prs
SELECT number, title, state, head_branch, base_branch, url, updated_at
FROM index_prs WHERE project_id = :project_id AND state = 'open' ORDER BY updated_at DESC;
