---
title: workdir-prune
status: binding
introduced: v6.2.5
description: |
  `shctx prune` reclaims accreted workdir + registry state without affecting
  outcomes. --dry-run is the DEFAULT; --confirm executes on-disk sweeps by MOVING
  targets into a /tmp run dir (reversible — the snapshot IS the move). Eligibility
  is fenced on ALL THREE: sprint/branch != current git branch, a terminal state,
  and age >= floor. It NEVER touches releases, the current sprint's focus,
  sprint_metrics, pinned/doctrine memory, unresolved escalations, pending
  deliverables, or active locks/loops. On-disk sweeps execute now; DB-row sweeps
  ship preview-only and are enabled incrementally ("start now, finish over time").
---

# Workdir prune — reclaim transient state, never an outcome (#171)

A long-lived shepherd workdir accretes: stale dispatch tags for closed sprints,
aged event logs, over-retained precompact snapshots, terminal registry rows. None
of it is read by outcome-determining logic, but it is never swept, so `.artifacts/`
/ `.shepherd/` grows without bound. `shctx prune` reclaims it under a strict fence.
`/shepherd:cleanup` only ever pruned the `teammates` table; this is the general GC.

## The fence — three conditions, all required

An item is eligible ONLY if all three hold:

1. **Not current.** Its sprint/branch != the current git branch. The active
   sprint's state is always kept.
2. **Terminal.** A closed/released/aborted/acked state — never an in-flight one.
3. **Aged.** Older than the configured age floor.

Presence alone is never sufficient. The active fence is the current git branch.

## Never-touch (outcome-affecting)

`index_releases`, the current sprint's `focus`, `sprint_metrics` (adaptation
priors read every spawn), pinned/doctrine/decision `mem_entries`, unresolved
`escalations`, pending `deliverables`, active `locks` (`released_at IS NULL`),
active `loops`, the whole `index_*`/`projects` core, and the tracked
`.artifacts/docs/` subtree (plans, seeds, reports — including a plan's
critic-proof). These are never candidates, by construction.

## Safety discipline (mirrors CLAUDE.md backfill rules)

- **--dry-run is the default.** It prints the plan and writes it to
  `/tmp/shepherd-prune-<epoch>/plan.csv`; nothing is removed.
- **--confirm executes on-disk sweeps by MOVING**, not deleting: targets go into
  the /tmp run dir, so the snapshot IS the removal and a `mv` back restores them.
- **Every DB DELETE is table-guarded.** A workdir DB may lack later migrations
  (e.g. this repo's DB has only migrations {1,2,7}); a sweep against an absent
  table must skip, never error (guard with a `sqlite_master` existence check).
- **VACUUM is opt-in** (`--vacuum`) and needs `--confirm`; it briefly needs
  exclusive DB access, so it is never implicit.

## Scope — on-disk now, DB rows over time

- **On-disk (executes with --confirm):** stale `dispatch/<sprint>/` dirs (sprint
  != current, aged), aged `logs/events-*.jsonl` + `logs/hooks/*.jsonl`, precompact
  `memory/snapshots/` beyond the newest-N.
- **DB rows (PREVIEW-ONLY in v6.2.5):** eligible-row COUNTS are reported
  (`logs_events`, crashed/retired `heartbeats`, acked/expired `mailbox`,
  closed-sprint `discovery_findings`/`audit_findings`, terminal `loops`, released
  `locks_history`) but nothing is deleted. Deletion is enabled incrementally in a
  later patch, each sweep table-guarded and snapshotted — "start now, finish over
  time." A prune that bounds coverage says so; it does not silently truncate.

## Config

```toml
[prune]
logs_days        = 60   # age floor for log files
dispatch_days    = 30   # age floor for stale dispatch dirs
snapshots_keep   = 20   # precompact snapshots to retain (newest-first)
findings_sprints = 6    # keep findings for the last N sprints
```

Flags override config (`--logs-days=`, `--dispatch-days=`, `--snapshots-keep=`);
config overrides the built-in defaults above.

## See also

- `doctrines/adaptation-loop.md` — the priors/findings retention this respects.
- `doctrines/cache-telemetry.md` — the logs this ages out are observability, not outcomes.
- `commands/cleanup.md` — the teammates-only prune this generalizes.
