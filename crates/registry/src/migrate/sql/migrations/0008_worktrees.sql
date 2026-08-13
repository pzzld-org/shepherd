-- 0008_worktrees.sql — v5.1.8 worktree lifecycle tracking
-- Field origin: GitHub issue #22 — zombie worktree refs accumulate after
-- force-remove with no cleanup step.
--
-- Claude Code v2.1+ fires WorktreeCreate / WorktreeRemove hooks around its
-- own worktree lifecycle (used by `--worktree` and `isolation: "worktree"` in
-- Agent dispatches). Shepherd's flock dispatches coders/auditors with
-- `isolation: "worktree"` per agents/conductor.md. When those worktrees are
-- force-removed, the `worktree-agent-*` branch refs accumulate as zombies in
-- `git branch -a` because nothing prunes them.
--
-- This migration adds a single `worktrees` table that the
-- hooks/scripts/worktree_lifecycle.sh hook writes to on both events. On
-- WorktreeCreate the hook records path + branch + tool_use_id + ts; on
-- WorktreeRemove it flips status to 'removed' and prunes any orphan
-- `worktree-agent-*` ref whose `git rev-parse --verify` fails.
--
-- Idempotent: hook re-runs INSERT OR IGNORE (UNIQUE on path+created_at not
-- enforced — the hook is single-shot per event, duplicates would be a
-- runtime defect we want surfaced, not silenced).
--
-- Indexes scope queries to the two hot paths: status lookups (active rows
-- for the remove handler) and per-sprint rollups (operator inspection).

BEGIN;

CREATE TABLE IF NOT EXISTS worktrees (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  path        TEXT NOT NULL,
  branch      TEXT,
  tool_use_id TEXT,
  agent_role  TEXT,
  sprint      TEXT,
  created_at  INTEGER NOT NULL,   -- epoch ms
  removed_at  INTEGER,             -- NULL while active
  status      TEXT NOT NULL DEFAULT 'active'   -- active | removed | zombie
                CHECK(status IN ('active','removed','zombie'))
);

CREATE INDEX IF NOT EXISTS ix_worktrees_status ON worktrees(status);
CREATE INDEX IF NOT EXISTS ix_worktrees_sprint ON worktrees(sprint);

-- schema_versions row is inserted by cmd_migrate.sh after this script runs.
COMMIT;
