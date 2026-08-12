CREATE VIEW IF NOT EXISTS v_open_issues AS
  SELECT project_id, number, title, state, labels, milestone, assignees, url, updated_at
  FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC;
