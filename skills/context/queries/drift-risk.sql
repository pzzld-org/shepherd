-- usage: shctx query drift-risk
SELECT number, title, milestone, json(labels) AS labels
FROM v_drift_risk WHERE project_id = :project_id;
