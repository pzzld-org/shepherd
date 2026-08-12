-- skills/context/schema/migrations/0020_drop_mailbox.sql
-- shepherd v6.3.7 — retire the generic mailbox; add a dedicated inter-session
-- signal channel (#206).
--
-- WHY. The `shctx mailbox send/recv/ack/stale` surface was ONE generic inbox
-- straddling two unrelated jobs: (a) intra-session teammate<->lead coordination
-- and (b) cross-session handoff between two independent operator sessions. Job
-- (a) belongs to the harness — the native SendMessage queue is root's canonical
-- inbox, and escalations moved onto it in v6.2.8 (hooks/scripts/teammate_idle.sh).
-- Overloading one table for both is what produced the #206 desync: `mailbox recv`
-- returned empty while coordinate_drive_guard.sh reported "N unread" against it and
-- re-fired the drive guard every fresh session.
--
-- WHAT. Drop the mailbox table + its unread view outright (job (a) is not ours).
-- Job (b) is a real, distinct capability, so give it a PURPOSE-BUILT table:
-- `session_signals`. Its only client is a cross-session handoff (today: the
-- `--staged` plant->spawn `seed-ready` nudge; spawn-flags.md §--staged). It is
-- deliberately NARROW — send + poll(+consume), no ack/read/stale tri-state — and
-- NOTHING treats it as an inbox to "drain": the drive guard never reads it, so the
-- phantom-unread class is structurally gone, not merely filtered. The committed
-- seed FILE remains the source of truth; this channel is only the nudge.
--
-- Drop the view first (it selects from mailbox), then the table (indexes go with
-- it). IF EXISTS on every DROP so a DB that never reached 0007 is a clean no-op and
-- re-running is idempotent. The schema_versions row is inserted by cmd_migrate.sh
-- after this runs — do NOT self-insert it here.
PRAGMA foreign_keys = ON;

-- --- retire the generic mailbox (job (a) belongs to native SendMessage) --------
DROP VIEW  IF EXISTS v_mailbox_unread_per_recipient;
DROP TABLE IF EXISTS mailbox;

-- --- dedicated cross-session signal channel (job (b)) --------------------------
-- recipient  : target session slug, e.g. "spawn-<sprint_slug>" — NOT a teammate.
-- kind        : signal type, e.g. "seed-ready".
-- payload     : JSON body (advisory; the committed artifact is the source of truth).
-- consumed_at : stamped by `signal poll --consume`; a one-shot, not a read/ack pair.
CREATE TABLE IF NOT EXISTS session_signals (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   TEXT    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sender       TEXT    NOT NULL,
  recipient    TEXT    NOT NULL,
  kind         TEXT    NOT NULL,
  payload      TEXT    NOT NULL CHECK(json_valid(payload)),
  sent_at      INTEGER NOT NULL,
  consumed_at  INTEGER
);

-- Poll path: unconsumed signals for one recipient (optionally one kind).
CREATE INDEX IF NOT EXISTS idx_session_signals_pending
  ON session_signals(recipient, kind, consumed_at)
  WHERE consumed_at IS NULL;
