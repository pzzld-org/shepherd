---
title: SQLite-canonical operational state
slug: sqlite-canonical-state
status: binding
since: v5.1.7
---

# SQLite-canonical operational state

## Rule

`.artifacts/root.db` is the canonical store for operational and ephemeral
state. The filesystem is canonical only for human-authored durable artifacts.
Markdown reports are materialized views over DB rows, generated on demand
via `shctx report <kind>`.

## Allow-list

### SQLite-canonical (rows, queryable)

- Teammate identity, liveness, heartbeats (`teammates`, `heartbeats`)
- Inter-agent messages including heartbeat payloads (`mailbox`)
- Escalations: teammate → root surface points (`escalations`)
- Per-agent deliverable promise/complete ledger (`deliverables`)
- Structured discovery findings (`discovery_findings`)
- Structured audit findings (`audit_findings`)
- Hook events (`logs_events`, existing)
- Locks (`locks_history`, existing)
- Memory entries — doctrines/notes/decisions/incidents (`mem_entries`, existing)

### File-canonical (version-controlled, human-edited)

- `CLAUDE.md`, project doc roots
- `agents/*.md`, `commands/*.md`, `skills/**/*.md`, `doctrines/*.md`
- `.artifacts/docs/specs/*.md` (design specs)
- `.artifacts/docs/plans/*.md` (sprint plans)
- `.artifacts/docs/seeds/*.seed.md` (sprint seeds)
- `CHANGELOG.md`, `README.md`
- `skills/context/schema/*.sql` (the schema itself)

### Disposable (materialized on demand)

- Audit reports → `shctx report audit --sprint=<branch>`
- Discovery handoffs → `shctx report discovery --run=<id>`
- Sprint close reports → `shctx report close --sprint=<branch>`
- Operator-facing status pages → `shctx report teammates --team=<name>`

Disposable views may be written to `.artifacts/cache/` (gitignored) when
operators want a stable file path. Re-rendering from rows is idempotent.

## Why this exists

v5.1.5/v5.1.6 surfaced a defect cluster (#43, #49, #52, #53) where
ephemeral state was file-bound, causing:

- Opaque "did the write happen?" failures (no atomic commit)
- Invisible silent crashes (no liveness index)
- Filesystem-locked heartbeat protocols (no concurrent-write primitive)
- Markdown-paraphrase drift in cross-references (no schema)
- Operator-visible git churn from generated reports

SQLite gives atomicity, WAL concurrency, queryable structured state, and
indexable liveness. The shift to row-canonical eliminates the entire
class.

## Anti-patterns

1. **Inventing a new artifact path that isn't a `shctx <X> insert` call.**
   If a new operational-state kind needs storage, propose a schema migration
   first, then a `cmd_<sub>.sh`, then use it. Do not invent
   `.artifacts/<new-thing>/`.

2. **Writing a markdown report as the canonical output.** The report is a
   view. The rows are the truth. If an agent writes only markdown, the next
   agent has nothing to query.

3. **Reading the markdown view to "verify" rows landed.** Query the rows
   directly: `sqlite3 .artifacts/root.db "SELECT count(*) FROM <table>
   WHERE <filter>;"`

4. **Locking the markdown file to coordinate writes.** Use SQLite WAL +
   transactional inserts. The DB handles concurrency.

5. **Treating `shctx report` output as source-of-truth.** It's a snapshot.
   If state changes, re-render.

## Migration guidance (back-compat)

Existing markdown reporting flows continue to work without change in v5.1.7.
NEW flows added in v5.1.7+ MUST canonicalize via shctx. When an existing
markdown-report flow is touched for an unrelated reason, opportunistically
migrate it to the row-canonical pattern.

## Cited from

- `agents/discovery.md` (closes #43 via row-write contract)
- `agents/critic.md` (closes #52 via deliverable promise/complete)
- `agents/auditor.md` (closes #52, #44 via same pattern + intro-extras)
- `agents/conductor.md` (closes #50; references this doctrine in dispatch)
- `doctrines/workflow-compile-down.md` (canonical-state seam, §VI: the workflow runtime's within-session resume is never canonical — SQLite + git stay conductor-owned)
- `agents/shepherd.md` (closes #49 via liveness polling)

## Field origin

> Operator diagnosis, 2026-05-20: "consider why we continue producing so
> many artifacts when we have a sqlite instance specifically to help
> eliminate the need ... disk updates are a little slower than a database
> ... sqlite and databases have built in parallel / concurrent access
> protections unlike files."
