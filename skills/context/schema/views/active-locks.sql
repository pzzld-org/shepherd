CREATE VIEW IF NOT EXISTS v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;
