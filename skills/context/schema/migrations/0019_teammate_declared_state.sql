-- skills/context/schema/migrations/0019_teammate_declared_state.sql
-- shepherd v6.3.2 — explicit teammate declared_state (#193/#194/#195/#98).
--
-- The teammates table (0007) carried ONE state column, `status`, that conflated
-- two things: a machine-written lifecycle state (booting/active/idle/retired) and
-- a would-be crash flag no writer ever set — the crash concept lived only as a
-- `presumed-crashed` string DERIVED on read from last_seen_at. Since #93 retired
-- the per-tool heartbeat emitter, no teammate advances last_seen_at on a cadence,
-- so that derived verdict false-positives: a healthy engineer crosses the 5-min
-- stale threshold and reads `presumed-crashed` while actively running, and the
-- coordinate-drive Stop hook blocks/cancels on ghosts from prior sessions.
--
-- Add ONE explicit column the teammate (or its lead) DECLARES: an intent/progress
-- state from a fixed enum. A declaration wins over the timing heuristic —
-- `in-progress`/`init` never read as crashed no matter the heartbeat gap; `error`
-- is the escalation signal (#98); `complete` is terminal; `idle` is an explicit
-- rest. NULL = no declaration, so every pre-0019 behavior is preserved (fully
-- backward compatible). Written by `shctx teammate state <name> --set=<s>` and by
-- `shctx teammate heartbeat --state=<s>`; read by liveness / prune --crashed /
-- panes / coordinate_drive_guard.sh / dash.
--
-- NOTE on idempotency: unlike the CREATE-TABLE-IF-NOT-EXISTS migrations, a plain
-- ADD COLUMN is not re-apply-safe. The usual idempotent trick (a table rebuild) is
-- deliberately AVOIDED: teammates has a dependent view (v_teammates_live), and a
-- DROP/RENAME rebuild reintroduces the exact ALTER-RENAME view-reparse abort that
-- 0017 was just fixed for. The version-gated migrate runner (schema_versions)
-- applies this exactly once, so a single ADD COLUMN is correct. v_teammates_live is
-- `SELECT t.*`, so it surfaces the new column with no view edit. The schema_versions
-- row is inserted by cmd_migrate.sh after this runs — do NOT self-insert it here.
PRAGMA foreign_keys = ON;

ALTER TABLE teammates ADD COLUMN declared_state TEXT
  CHECK(declared_state IS NULL OR declared_state IN
        ('init','in-progress','error','complete','idle'));
