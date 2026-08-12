CREATE VIEW IF NOT EXISTS v_drift_risk AS
  SELECT project_id, number, title, milestone, labels
  FROM index_issues
  WHERE state = 'open'
    AND (labels LIKE '%"critical"%' OR labels LIKE '%"high"%');
