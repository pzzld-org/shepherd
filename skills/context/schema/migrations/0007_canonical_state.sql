-- skills/context/schema/migrations/0007_canonical_state.sql
-- shepherd v5.1.7 — SQLite-canonical operational state.
-- Adds teammates, heartbeats, mailbox, escalations, deliverables,
-- discovery_findings, audit_findings + 3 hot-query views.
--
-- v6.0.3 (passover CRITICAL): relocated from schema/ root into migrations/ so
-- cmd_migrate.sh actually applies it (the runner only globs migrations/NNNN_*.sql,
-- so the v5.1.7 operational-state tables were never created in consumer DBs).
-- Made idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill runner can
-- safely (re)apply it. The schema_versions row is inserted by cmd_migrate.sh after
-- this script runs — do NOT self-insert it here (that was the prior bug).
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

-- Teammate identity + liveness
CREATE TABLE IF NOT EXISTS teammates (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  team_name     TEXT NOT NULL,
  teammate_name TEXT NOT NULL,
  agent_type    TEXT NOT NULL,
  session_id    TEXT,
  tmux_pane_id  TEXT,
  spawned_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,
  status        TEXT NOT NULL CHECK(status IN
                  ('booting','active','idle','crashed','retired')),
  metadata      TEXT CHECK(metadata IS NULL OR json_valid(metadata)),
  UNIQUE(project_id, team_name, teammate_name)
);
CREATE INDEX IF NOT EXISTS idx_teammates_project_status ON teammates(project_id, status);
CREATE INDEX IF NOT EXISTS idx_teammates_last_seen      ON teammates(last_seen_at);

-- Heartbeats
CREATE TABLE IF NOT EXISTS heartbeats (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  teammate_id  TEXT NOT NULL REFERENCES teammates(id) ON DELETE CASCADE,
  ts           INTEGER NOT NULL,
  phase        TEXT,
  tool_name    TEXT,
  note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_teammate_ts ON heartbeats(teammate_id, ts DESC);

-- Mailbox
CREATE TABLE IF NOT EXISTS mailbox (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sender_id       TEXT NOT NULL,
  recipient_name  TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK(kind IN
                    ('heartbeat_payload','escalation','ack','status','generic')),
  payload         TEXT NOT NULL CHECK(json_valid(payload)),
  target_file     TEXT,
  requires_ack    INTEGER NOT NULL DEFAULT 0,
  sent_at         INTEGER NOT NULL,
  read_at         INTEGER,
  acked_at        INTEGER,
  expires_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mailbox_recipient_unread ON mailbox(recipient_name, read_at)
  WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_mailbox_ack_pending      ON mailbox(requires_ack, acked_at)
  WHERE requires_ack = 1 AND acked_at IS NULL;

-- Escalations
CREATE TABLE IF NOT EXISTS escalations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  teammate_id   TEXT REFERENCES teammates(id) ON DELETE SET NULL,
  sprint_branch TEXT,
  role          TEXT NOT NULL,
  phase         TEXT,
  question      TEXT NOT NULL,
  blocking      INTEGER NOT NULL DEFAULT 1,
  context_refs  TEXT CHECK(context_refs IS NULL OR json_valid(context_refs)),
  raised_at     INTEGER NOT NULL,
  resolved_at   INTEGER,
  resolution    TEXT
);
CREATE INDEX IF NOT EXISTS idx_escalations_unresolved
  ON escalations(project_id, resolved_at) WHERE resolved_at IS NULL;

-- Deliverable ledger (stall detector)
CREATE TABLE IF NOT EXISTS deliverables (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  agent_session  TEXT NOT NULL,
  agent_role     TEXT NOT NULL,
  kind           TEXT NOT NULL,
  target_ref     TEXT NOT NULL,
  promised_at    INTEGER NOT NULL,
  delivered_at   INTEGER,
  status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK(status IN ('pending','delivered','stalled','aborted'))
);
CREATE INDEX IF NOT EXISTS idx_deliverables_pending
  ON deliverables(project_id, status) WHERE status = 'pending';

-- Discovery findings
CREATE TABLE IF NOT EXISTS discovery_findings (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch  TEXT,
  discovery_run  TEXT NOT NULL,
  section        TEXT,
  title          TEXT NOT NULL,
  body           TEXT NOT NULL,
  sources        TEXT CHECK(sources IS NULL OR json_valid(sources)),
  created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovery_sprint_run
  ON discovery_findings(project_id, sprint_branch, discovery_run);

-- Audit findings
CREATE TABLE IF NOT EXISTS audit_findings (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch  TEXT,
  concern        TEXT NOT NULL,
  severity       TEXT NOT NULL CHECK(severity IN
                   ('info','low','medium','high','critical')),
  hypothesis     TEXT NOT NULL,
  falsification  TEXT,
  confidence     TEXT CHECK(confidence IN ('low','medium','high')),
  finding        TEXT NOT NULL,
  evidence_refs  TEXT CHECK(evidence_refs IS NULL OR json_valid(evidence_refs)),
  gh_issue       INTEGER,
  created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_sprint_severity
  ON audit_findings(project_id, sprint_branch, severity);

-- Hot-query views (DROP+CREATE for idempotent re-apply; views carry no data)
DROP VIEW IF EXISTS v_teammates_live;
CREATE VIEW v_teammates_live AS
  SELECT t.*, (strftime('%s','now')*1000 - t.last_seen_at) AS ms_since_seen
  FROM teammates t
  WHERE t.status NOT IN ('crashed','retired');

DROP VIEW IF EXISTS v_mailbox_unread_per_recipient;
CREATE VIEW v_mailbox_unread_per_recipient AS
  SELECT recipient_name, COUNT(*) AS unread_count, MIN(sent_at) AS oldest_sent
  FROM mailbox
  WHERE read_at IS NULL
  GROUP BY recipient_name;

DROP VIEW IF EXISTS v_escalations_open;
CREATE VIEW v_escalations_open AS
  SELECT e.*, t.teammate_name, t.team_name
  FROM escalations e
  LEFT JOIN teammates t ON t.id = e.teammate_id
  WHERE e.resolved_at IS NULL
  ORDER BY e.raised_at;

COMMIT;
