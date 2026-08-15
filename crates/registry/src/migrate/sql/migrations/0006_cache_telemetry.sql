-- 0006_cache_telemetry.sql — v5.1.3 dispatch cache telemetry
-- Field origin: 2026-05-19 operator request — "we simply need to ensure we are
-- actually benefitting from our own plugin both in plan execution and w.r.t.
-- maximizing our usage and tokens."
--
-- Captures per-dispatch prompt-caching health so the close-time @auditor's
-- completeness concern can verify the brief-cache-discipline structural rule
-- is producing real cache-read wins. Source data lands in
-- <ns>/logs/events-YYYY-MM-DD.jsonl from hooks/scripts/subagent_telemetry.sh;
-- `shctx refresh --scope=telemetry` shovels rows from JSONL into the table.
--
-- Tables:
--   index_cache_usage — one row per subagent dispatch (cache zone — derived,
--     rebuildable from the JSONL event log)
--
-- Views:
--   v_cache_usage — per-sprint × role rollup consumed by
--     skills/context/queries/cache-usage.sql + the @auditor completeness
--     concern's "## Cache telemetry" close-report subsection.
--
-- The UNIQUE(session_id, agent_id, ts) constraint makes refresh idempotent:
-- replaying the same JSONL line is a no-op via INSERT OR IGNORE.
--
-- The view filters parse_error IS NULL so degraded events surface as a row in
-- the table (visible via `shctx query` against the table directly) but do not
-- pollute the aggregated hit-rate the auditor reads. The auditor reading
-- `v_cache_usage` sees only honest measurements.

BEGIN;

CREATE TABLE IF NOT EXISTS index_cache_usage (
  id                            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id                    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  ts                            INTEGER NOT NULL,                 -- unix seconds (epoch)
  session_id                    TEXT,                             -- parent session id (from hook payload)
  role                          TEXT NOT NULL,                    -- engineer|critic|coder|auditor|worker|discovery|unknown
  agent_id                      TEXT,                             -- subagent id (durable across resume)
  sprint                        TEXT,                             -- git branch at dispatch
  turns                         INTEGER,                          -- assistant turns observed in the subagent transcript
  input_tokens                  INTEGER,                          -- raw input tokens (non-cached prefix)
  output_tokens                 INTEGER,
  cache_read_input_tokens       INTEGER,
  cache_creation_input_tokens   INTEGER,
  ephemeral_5m_input_tokens     INTEGER,                          -- subset of cache_creation (5m TTL writes)
  ephemeral_1h_input_tokens     INTEGER,                          -- subset of cache_creation (1h TTL writes)
  hit_rate                      REAL,                             -- cache_read / (cache_read + cache_creation + input); null when undefined
  parse_error                   TEXT,                             -- nullable; populated when the hook could not aggregate
  UNIQUE(session_id, agent_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_cache_usage_sprint   ON index_cache_usage(project_id, sprint);
CREATE INDEX IF NOT EXISTS idx_cache_usage_role_ts  ON index_cache_usage(project_id, role, ts);

-- Per-sprint × role rollup. The view excludes parse_error rows so that the
-- aggregate hit-rate the auditor reads reflects only honest measurements.
-- The avg_first_turn_creation column proxies "stable-prefix cost": it
-- averages cache_creation across single-turn dispatches, which is the
-- cleanest signal for the size of the cacheable system prefix per role.
CREATE VIEW IF NOT EXISTS v_cache_usage AS
  SELECT
    project_id,
    sprint,
    role,
    COUNT(*)                                                                AS dispatches,
    AVG(hit_rate)                                                           AS avg_hit_rate,
    SUM(input_tokens)                                                       AS total_input,
    SUM(cache_read_input_tokens)                                            AS total_cache_read,
    SUM(cache_creation_input_tokens)                                        AS total_cache_creation,
    AVG(CASE WHEN turns = 1 THEN cache_creation_input_tokens ELSE NULL END) AS avg_first_turn_creation
  FROM index_cache_usage
  WHERE parse_error IS NULL
  GROUP BY project_id, sprint, role;

-- schema_versions row is inserted by cmd_migrate.sh after this script runs.
COMMIT;
