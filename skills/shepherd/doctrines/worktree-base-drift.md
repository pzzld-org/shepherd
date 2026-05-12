---
title: worktree base-drift prevention
description: |
  Coder worktrees MUST be branched from the sprint HEAD, not from `main` or
  any older base. The conductor pre-creates worktrees with `shctx worktree
  create-batch` instead of relying on `Agent({ isolation: "worktree" })`,
  which has been observed to non-deterministically branch from the wrong
  base (`main`) when the sprint is mid-flight.
---

# Doctrine — Worktree Base-Drift Prevention

> Project-agnostic principle: the value of a parallel coder dispatch
> evaporates the moment a worktree is branched from the wrong commit. The
> cherry-pick comes back as a conflict storm, the lane has to be redone,
> and the wave-gate slips. Pre-creation makes the base explicit and
> verifiable; the brief's `[BASE-COMMIT-EXPECTED]` line then forms a
> tripwire the coder honors.
>
> Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5),
> §1. Two of three Wave-1 lanes dispatched via `Agent({ isolation:
> "worktree" })` halted with `BASE-DRIFT — worktree HEAD <main SHA> does
> not match expected <sprint SHA>`. v5.0.4 codifies the prevention.

## The rule

The conductor MUST NOT rely on the Agent tool's `isolation: "worktree"`
mode for coder dispatch in a sprint context. Instead, the conductor:

1. **Pre-creates** worktrees from the sprint HEAD via:

   ```bash
   shctx worktree create-batch lane-1 lane-2 lane-3 --from "$SPRINT_BRANCH"
   ```

   This emits the `[BASE-COMMIT-EXPECTED]` SHA on the last line of output.

2. **Pastes** the `[WORKTREE-PATH]` and `[BASE-COMMIT-EXPECTED]` lines into
   each coder brief verbatim. The path is `.claude/worktrees/agent-<lane>`;
   the SHA is the `git rev-parse <sprint_branch>` snapshot taken at
   pre-create time.

3. **Never** uses `Agent({ isolation: "worktree", ... })` for sprint coder
   dispatch — this option remains valid for ad-hoc one-off agent work
   outside a sprint, but is unsafe inside one.

## Why pre-create instead of `isolation: "worktree"`

The Agent tool's `isolation: "worktree"` documentation does not specify a
`base_branch` parameter. Empirical observation in v5.0.3 (axiom dev.5) was
that a fraction of dispatches branched from `main` (carrying the previous
release's HEAD) instead of the active sprint branch. The same dispatch with
identical parameters succeeded for other lanes — suggesting either a race
condition or non-deterministic base-branch selection.

Pre-creation eliminates the variable. The branch is named, the base SHA is
pinned, the brief carries both — the coder verifies on entry.

## Coder brief — `[BASE-COMMIT-EXPECTED]` Step 0.5

The coder brief includes:

```
[WORKTREE-PATH] /abs/path/to/repo/.claude/worktrees/agent-<lane-id>
[BASE-COMMIT-EXPECTED] <40-char SHA captured at dispatch time>
```

The coder's Startup Protocol Step 0.5 verifies:

```bash
HEAD=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
[[ "$HEAD" == "$BASE_COMMIT_EXPECTED" ]] || halt "BASE-DRIFT — worktree HEAD $HEAD does not match expected $BASE_COMMIT_EXPECTED"
```

A `BASE-DRIFT` halt is a brief-validity failure. The conductor either:

- **Re-creates** the worktree with `shctx worktree create-batch <lane>
  --from "$SPRINT_BRANCH"` (preferred), then re-dispatches with the new SHA.
- **Investigates** why the worktree drifted (was the sprint branch advanced
  between dispatch and verification? did another conductor session race?).

## When `Agent({ isolation: "worktree" })` is safe

- One-off agent work outside a sprint context (no DEDUP-GATE, no Pattern B
  overlap, no cherry-pick cycle to honor).
- Research / read-only agents that don't write source.
- Worker dispatches whose deliverable is a markdown report, not a commit.

In every other case, prefer `shctx worktree create-batch` + explicit
`[WORKTREE-PATH]` + `[BASE-COMMIT-EXPECTED]`.

## See also

- `conductor-cwd.md` — companion doctrine: never `cd` into a worktree.
- `shepherd:context` skill `cmd_worktree.sh` — the helper.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/agent-briefs.md` —
  brief template carrying `[BASE-COMMIT-EXPECTED]`.
