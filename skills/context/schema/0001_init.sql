-- skills/context/schema/0001_init.sql
-- shepherd v5.0.0 baseline schema.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE schema_versions (
  version    INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL,
  checksum   TEXT NOT NULL
);

CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL DEFAULT '',
  scope       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(scope)),
  metadata    TEXT CHECK(metadata IS NULL OR json_valid(metadata)),
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  started_at    INTEGER NOT NULL,
  ended_at      INTEGER,
  agent_role    TEXT,
  sprint_branch TEXT,
  metadata      TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);
CREATE INDEX idx_sessions_project_branch ON sessions(project_id, sprint_branch);

CREATE TABLE profiles_defs (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK(kind IN ('modifier','extension','override')),
  config      TEXT NOT NULL CHECK(json_valid(config)),
  source_path TEXT,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  UNIQUE(project_id, name)
);

CREATE TABLE mem_entries (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind        TEXT NOT NULL CHECK(kind IN ('doctrine','note','decision','incident','session')),
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  pinned      INTEGER NOT NULL DEFAULT 0,
  source_path TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE INDEX idx_mem_project_kind   ON mem_entries(project_id, kind);
CREATE INDEX idx_mem_project_pinned ON mem_entries(project_id, pinned) WHERE pinned = 1;

CREATE TABLE index_symbols (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  package       TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  line          INTEGER,
  visibility    TEXT,
  signature     TEXT,
  doc_summary   TEXT,
  language      TEXT NOT NULL,
  hash          TEXT NOT NULL,
  refreshed_at  INTEGER NOT NULL,
  UNIQUE(project_id, name, package, kind)
);
CREATE INDEX idx_symbols_project_name ON index_symbols(project_id, name);
CREATE INDEX idx_symbols_project_pkg  ON index_symbols(project_id, package);

CREATE TABLE index_concepts (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  concept             TEXT NOT NULL,
  canonical_symbol_id TEXT NOT NULL REFERENCES index_symbols(id) ON DELETE CASCADE,
  aliases_to_avoid    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(aliases_to_avoid)),
  notes               TEXT,
  UNIQUE(project_id, concept)
);

CREATE TABLE index_issues (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,
  labels       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels)),
  milestone    TEXT,
  assignees    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(assignees)),
  body         TEXT,
  url          TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  refreshed_at INTEGER NOT NULL
);
CREATE INDEX idx_issues_project_state     ON index_issues(project_id, state);
CREATE INDEX idx_issues_project_milestone ON index_issues(project_id, milestone);

CREATE TABLE index_prs (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,
  base_branch  TEXT NOT NULL,
  head_branch  TEXT NOT NULL,
  labels       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels)),
  url          TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  merged_at    INTEGER,
  refreshed_at INTEGER NOT NULL
);
CREATE INDEX idx_prs_project_state ON index_prs(project_id, state);

CREATE TABLE index_releases (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  tag          TEXT NOT NULL,
  name         TEXT,
  prerelease   INTEGER NOT NULL DEFAULT 0,
  draft        INTEGER NOT NULL DEFAULT 0,
  body         TEXT,
  url          TEXT NOT NULL,
  published_at INTEGER,
  refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, source, tag)
);

CREATE TABLE index_milestones (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,
  due_on       INTEGER,
  description  TEXT,
  url          TEXT NOT NULL,
  refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, source, number)
);

CREATE TABLE logs_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  ts            INTEGER NOT NULL,
  level         TEXT NOT NULL CHECK(level IN ('info','warn','error','gate','audit')),
  source        TEXT NOT NULL,
  event         TEXT NOT NULL,
  payload       TEXT CHECK(payload IS NULL OR json_valid(payload)),
  sprint_branch TEXT,
  session_id    TEXT
);
CREATE INDEX idx_logs_project_ts ON logs_events(project_id, ts);

CREATE TABLE artifacts (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind          TEXT NOT NULL,
  path          TEXT NOT NULL,
  sprint_branch TEXT,
  title         TEXT,
  hash          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  UNIQUE(project_id, path)
);
CREATE INDEX idx_artifacts_project_kind ON artifacts(project_id, kind);
CREATE INDEX idx_artifacts_sprint       ON artifacts(project_id, sprint_branch);

CREATE TABLE locks_history (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  session_id   TEXT NOT NULL,
  mode         TEXT NOT NULL CHECK(mode IN ('autorun','parallel','start','plant','context')),
  acquired_at  INTEGER NOT NULL,
  released_at  INTEGER,
  released_by  TEXT CHECK(released_by IS NULL OR released_by IN ('normal','reap','force')),
  metadata     TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);

-- Views
CREATE VIEW v_open_issues AS
  SELECT project_id, number, title, state, labels, milestone, assignees, url, updated_at
  FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC;

CREATE VIEW v_canonical_types AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary,
         s.file_path, s.line, c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.visibility IN ('pub','pub(crate)','export')
  ORDER BY s.package, s.name;

CREATE VIEW v_drift_risk AS
  SELECT project_id, number, title, milestone, labels
  FROM index_issues
  WHERE state = 'open'
    AND (labels LIKE '%"critical"%' OR labels LIKE '%"high"%');

CREATE VIEW v_mem_recent_7d AS
  SELECT * FROM mem_entries
  WHERE created_at >= unixepoch() - 7 * 86400 OR pinned = 1
  ORDER BY pinned DESC, created_at DESC;

CREATE VIEW v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;

INSERT INTO schema_versions (version, applied_at, checksum)
VALUES (1, unixepoch(), 'baseline-v5.0.0');

COMMIT;
