-- usage: shctx query open-issues
SELECT number, title, state, json(labels) AS labels, milestone, url, updated_at
FROM v_open_issues WHERE project_id = :project_id;
