# Preflight via `shctx doctor` — single-command sanity check

> Origin: v5.1.1 (2026-05-15). The session-open hook performs a subset of
> these checks automatically. `shctx doctor` is the manual-invocation
> equivalent + an extended check set the operator runs before opening a
> sprint or when something feels off.

## What it does

`shctx doctor` runs a structured preflight across the project's shepherd
state and outputs a status table. Six sections:

| Section | Verifies |
|---|---|
| `[GIT]` | HEAD branch matches expected pattern; cwd is sprint root (not sub-worktree); orphan worktree count |
| `[PLAN]` | plan.md presence for current sprint; Stage Graph YAML block present; canonical-types.md freshness |
| `[CTX REGISTRY]` | root.db presence + size; schema migration version vs migrations/ latest; sprint-patterns.md entry count |
| `[HOOKS]` | hooks.json validity; each registered script present + executable; event log writable + recently-active |
| `[MCP]` | each `[mcp].*=true` in shepherd.toml → tool prefix callable |
| `[LOCK]` | shepherd.lock presence + sessions-id match |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All green — proceed |
| 1 | Warnings only — proceed but note items |
| 2 | Errors — operator should address before sprint open |

Non-blocking by design — the doctor reports, the operator decides.

## When to run

| Trigger | Recommendation |
|---|---|
| Before `/shepherd:plant` | Optional — planter doesn't need it but it surfaces blockers early |
| Before `/shepherd:start` | **Recommended** — catches pre-sprint state issues before the engineer's MESH absorbs them |
| Before `/shepherd:autorun` | **Strongly recommended** — autorun bypasses operator pauses; preflight catches issues that would otherwise compound silently |
| Before `/shepherd:parallel` | **Required** — parallel mode is multi-worktree; preflight catches stale sub-worktrees first |
| When something feels off | Always — the doctor is cheap (~ 5 seconds) and informative |
| Mid-sprint after `/reload-plugins` | Optional — verifies the reload picked up everything |

## Integration with `/shepherd:start`

The `session_open.sh` hook performs a subset of doctor checks
automatically (per `doctrines/conductor-cwd.md`). For the FULL check, the
operator runs `shctx doctor` manually OR the start command can auto-invoke
via `shepherd.toml [preflight].auto_invoke = "doctor"`.

When auto-invoke is on, the doctor output appends to additionalContext at
SessionStart; the operator sees the preflight inline.

## Sample output

```
shepherd preflight — v5.1.1
============================

[GIT]
  ✓ HEAD on sprint branch (v0.4.0-dev.3)
  ✓ cwd is sprint root (/Users/jo3/src/fl03/axiom)
  ✓ No sub-worktree drift
  ⚠ 1 orphan worktree (.claude/worktrees/agent-abc — last commit 4 days ago)

[PLAN]
  ✓ plan.md exists (.artifacts/plans/v0.4.0-dev.3.plan.md)
  ✓ Stage Graph block present (12 nodes)
  ⚠ canonical-types.md last refresh: 14 days ago — stale per dev.0 policy
  ✓ Plan Stage Graph has INTRO-COMBO-WAVE node (v5.1.1+)

[CTX REGISTRY]
  ✓ root.db exists (.shepherd/root.db, 12.4 MB)
  ✓ Schema at migration 0014; latest 0014
  ✓ sprint-patterns.md exists (8 entries)

[HOOKS]
  ✓ 8 hooks active (session_open, bash_guard, bash_post, lock_guard,
                    agent_pause_detector, agent_insight_capture,
                    agent_invocation_tagger, discovery_capture)
  ✓ Event log: 47 entries today (15 deny, 8 warn, 24 pass)
  ✓ All scripts executable

[MCP]
  ✓ github callable
  ✓ supabase callable
  ✗ sentry advertised in shepherd.toml but tool prefix not callable
    → run /reload-plugins to refresh catalog

[LOCK]
  ✓ shepherd.lock held by current session
  ✓ No concurrent conductor session detected

============================
Exit: 1 (warnings: 2)
```

Warnings:
- Orphan worktree — run `git worktree prune` or `git worktree remove`
- Stale canonical-types — run `shctx canonical refresh` (or wait for dev.0
  CANONICAL-TYPES-REFRESH worker)

## Output format options

```
shctx doctor              # full table (default)
shctx doctor --section=git  # one section
shctx doctor --json        # machine-readable
shctx doctor --quick       # skip MCP checks (fastest)
```

## Failure surface

If `shctx doctor` itself fails (e.g., not in a shepherd project, missing
shepherd.toml), exit code is 2 and stderr explains:

```
shctx: doctor command requires a shepherd project (no .claude/shepherd.toml found)
       run `shctx init` to scaffold a new project, or `cd` to a shepherd project root.
```

## Implementation

Lives at `skills/context/scripts/cmd_doctor.sh`, dispatched from `shctx`
main script's case statement.

Reads:
- `.claude/shepherd.toml` (resolves branches, gates, paths)
- `.git/HEAD` (current branch)
- `.git/worktrees/` (sub-worktree enumeration)
- `<paths.plans>/<sprint_branch>.plan.md` (plan presence + Stage Graph check)
- `<paths.ctx>/canonical-types.md` mtime (freshness check)
- `<ns>/root.db` (size + migration version via sqlite3)
- `<ns>/logs/hooks/<today>.jsonl` (event log activity)
- `<ns>/shepherd.lock` (lock state)
- ToolSearch query for MCP tool callability

Writes: nothing — preflight is read-only.

## Anti-patterns

1. **Treating doctor as the source of truth.** It surfaces state; it doesn't
   correct it. Operator addresses the warnings.
2. **Running doctor inside a sub-worktree.** The first check (cwd is sprint
   root) will fire; don't be alarmed, the doctor is doing its job. `cd` back
   to sprint root first.
3. **Suppressing warnings.** A warning means real state drift; investigate
   before suppressing. The `--quick` flag is for time-pressured cases, not
   willful blindness.

## See also

- `skills/context/scripts/cmd_doctor.sh` — implementation
- `hooks/scripts/session_open.sh` — automatic subset at session start
- `doctrines/conductor-cwd.md` — the three-anchor verification that
  doctor's `[GIT]` section automates
- `doctrines/hook-event-log.md` — event log the `[HOOKS]` section reads
