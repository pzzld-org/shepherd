CREATE VIEW IF NOT EXISTS v_mem_recent_7d AS
  SELECT * FROM mem_entries
  WHERE created_at >= unixepoch() - 7 * 86400 OR pinned = 1
  ORDER BY pinned DESC, created_at DESC;
