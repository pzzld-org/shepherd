-- skills/context/schema/migrations/0021_spawn_lead.sql
-- shepherd v6.3.8 — record the LEAD session of a spawned team (#223).
--
-- WHY. coordinate_drive_guard.sh only ever exempted registered TEAMMATES (the
-- #197 gate). It never had a way to tell "the recorded lead of this live team"
-- apart from "some other, unrelated session that happens to share the same
-- per-repo shepherd.db". A second, non-teammate session polling the same
-- v_teammates_live live/idle counts got nudged with [coordinate-active-drive]
-- every turn even though it spawned nothing and owns no team to drain. The DB
-- had NO concept of a lead session at all — this migration adds one.
--
-- WHAT. `spawn_leads` records, per team_name, which session_id is the LEAD
-- that spawned it (i.e. the one the drive-guard contract actually applies to).
-- Spawn already refuses to start a second concurrent team, so team_name is a
-- safe natural key — one row per live spawned team. Populated by
-- `shctx teammate register-lead` at spawn time; consumed by
-- coordinate_drive_guard.sh to distinguish "I am the lead of a live team" from
-- "I am a bystander session sharing this DB with someone else's live team".
--
-- The schema_versions row is inserted by cmd_migrate.sh after this script
-- runs — do NOT self-insert it here.
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS spawn_leads (
  team_name   TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  session_id  TEXT NOT NULL,
  spawned_at  INTEGER NOT NULL
);

COMMIT;
