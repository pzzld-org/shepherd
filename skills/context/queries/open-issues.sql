-- usage: shctx query open-issues
-- Deterministic order, no volatile `updated_at` column → byte-stable brief tail
-- so the injected open-issues block doesn't churn the cache run-to-run
-- (v6.0.5 caching audit; cf. doctrines/brief-cache-discipline.md).
SELECT number, title, state, json(labels) AS labels, milestone, url
FROM v_open_issues WHERE project_id = :project_id ORDER BY number;
