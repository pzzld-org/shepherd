---
title: coder worktree confinement
description: |
  Coder file writes — including shared-context artifacts like
  `.shepherd/ctx/*.md` — go to the worktree path. Writes to the sprint
  root path are silently dropped from the conductor's cherry-pick and
  create dual-write dirt the conductor has to clean up.
---

# Doctrine — Coder Worktree Confinement

> Project-agnostic principle: a coder's deliverable is a worktree commit.
> The conductor cherry-picks that commit onto the sprint branch. Anything
> the coder wrote to the sprint root is NOT in the commit, so it does NOT
> survive the cherry-pick — yet it DOES leave a dirty working tree the
> conductor must stash before the cherry-pick can run. The result is
> silent loss of work plus extra cycles.
>
> Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5),
> §3. Lane 9 wrote source files to its worktree but `.shepherd/ctx/feature-
> flag-matrix.md` to the main workspace; Lane 6 wrote `canonical-types.md`
> to BOTH locations. Conductor stashed and resolved manually before each
> cherry-pick. v5.0.4 codifies the prevention.

## The rule

Every `Write`, `Edit`, or `git add` target MUST resolve under the brief's
`[WORKTREE].Path`. This applies uniformly to:

- Source code (`.rs`, `.py`, `.ts`, …)
- Build manifests (`Cargo.toml`, `package.json`, …)
- Migrations (`*.sql`)
- Documentation (`README.md`, `CHANGELOG.md`)
- **Shared-context artifacts** (`.shepherd/ctx/*.md`,
  `.shepherd/reports/*.md`, `.shepherd/docs/*.md`, …)

Yes — even files that "feel like" they belong at the sprint root. If a
brief asks you to update `.shepherd/ctx/canonical-types.md`, the brief
also gives you `[WORKTREE].Path = /abs/.claude/worktrees/agent-XXX` and
your write target is
`/abs/.claude/worktrees/agent-XXX/.shepherd/ctx/canonical-types.md`.

## Why writes to sprint root silently fail

The conductor's integration model is:

1. Coder commits inside the worktree.
2. Conductor runs `shctx worktree merge <agent-id>` (or equivalent
   `git -C <repo> cherry-pick <worktree HEAD>`).
3. Cherry-pick replays the worktree's commit objects onto the sprint
   branch.

Files the coder wrote to the SPRINT ROOT — outside the worktree — are
NOT part of the worktree commit. They show up in the sprint root's
`git status` as a dirty working tree. The cherry-pick refuses to run
on a dirty index, so the conductor stashes those changes — and they're
typically dropped or re-applied incorrectly.

## How to honor confinement

1. **Read** the brief's `[WORKTREE].Path` once at startup.
2. **Bind** every absolute path you write to that prefix.
3. If unsure, prefer absolute paths over relative paths — the absolute
   path makes confinement visible at every Write.

```bash
# Good
WT="/abs/repo/.claude/worktrees/agent-3"
Write "$WT/crates/foo/src/lib.rs" "..."
Write "$WT/.shepherd/ctx/canonical-types.md" "..."

# Bad — these silently land in the wrong place
Write ".shepherd/ctx/canonical-types.md" "..."   # CWD-dependent
Write "/abs/repo/.shepherd/ctx/canonical-types.md" "..."  # sprint root!
```

## Brief-side responsibilities

The conductor's brief MUST include:

```
[WORKTREE]
Path:   /abs/repo/.claude/worktrees/agent-<lane-id>
Branch: agent-<lane-id>
Commit: <commit-message-template>

[BASE-COMMIT-EXPECTED] <40-char SHA>
```

If the brief omits `[WORKTREE].Path`, the coder halts with
`BRIEF INVALID — missing [WORKTREE].Path` per Startup Protocol Step 0.

## Shared-context append discipline

When two lanes both touch the same `.shepherd/ctx/*.md` file (different
sections), the conductor's `coder-brief-format-shared-artifacts.md`
doctrine applies — briefs specify section line-ranges or footer-append
behavior so cherry-pick conflicts resolve cleanly.

## See also

- `worktree-base-drift.md` — companion doctrine: worktrees must branch
  from sprint HEAD.
- `coder-brief-format-shared-artifacts.md` — when multiple lanes write
  to the same shared file.
- `agents/coder.md` Hard Prohibitions — canonical enforcement.
