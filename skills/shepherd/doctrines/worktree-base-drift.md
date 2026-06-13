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
> Field origin: shepherd v5.0.3 conductor feedback (downstream Rust service),
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
`base_branch` parameter. Empirical observation in v5.0.3 (a downstream Rust service) was
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

## Canonical no-isolation workaround (v5.0.6)

> Field origin: downstream Rust service, 2026-05-12 — `isolation: "worktree"` defaults
> to `main` on every dispatch when the sprint is on a non-`main` branch. The
> BASE-DRIFT halt fires correctly, but re-dispatching WITH isolation just repeats
> the same failure. The canonical workaround is to dispatch WITHOUT isolation.

When `isolation: "worktree"` consistently routes to `main` instead of the
active sprint branch, the conductor switches to **no-isolation parallel
dispatch** for the duration of that sprint:

1. **Drop `isolation: "worktree"` entirely** from the Agent call.
2. **Rely on file-disjoint `[FILE-SCOPE]` guarantees** — if the engineer's plan
   produces strictly non-overlapping file scopes, parallel coders can work in
   the same working tree without conflicts (last-write-wins is safe when there
   is only ONE writer per file).
3. **Remove `[WORKTREE]` and `[BASE-COMMIT-EXPECTED]` from the brief** — replace
   with `[WORKING-TREE]` stating the sprint root path and the branch.
4. **Coders `git add <their files>` and commit directly** to the sprint branch
   (shared). Commits land in dispatch-completion order. The wave-gate runs after
   all coders report back — ORDER OF COMMITS DOES NOT MATTER as long as scopes
   are disjoint.
5. **Add a single-line warning to the ENGINEER REPORT** in the dispatch message:
   "No-isolation mode — extra care required on [FILE-SCOPE] disjointness; any
   overlap is last-write-wins."

**What you lose:**
- The cherry-pick isolation barrier (two coders with accidental overlap → last-write-wins, not a conflict)
- The `CONTEXT-INVENTORY STALE` detection (coder can't compare against a worktree-isolated HEAD snapshot)
- The worktree-confinement enforcement from `doctrines/worktree-confinement.md`

**What mitigates the loss:**
- File-disjoint `[FILE-SCOPE]` guaranteed by the engineer's plan + conductor DEDUP-GATE pre-check
- Post-merge `git diff --stat` verifies no unexpected files were touched
- CLOSE-SWARM auditor `completeness` concern verifies real-work test and scope

**Document the mode in the close report:**
```markdown
## Dispatch mode: no-isolation (worktree-base-drift workaround)
Reason: `isolation:"worktree"` defaulted to `main` on all dispatch attempts.
Risk mitigation: file-disjoint [FILE-SCOPE] verified at DEDUP-GATE; post-wave
  `git diff --stat` reviewed; no overlap found.
```

This mode is the documented CANONICAL WORKAROUND until the Agent tool's
`isolation: "worktree"` parameter respects the caller's current branch.

## See also

- `conductor-cwd.md` — companion doctrine: never `cd` into a worktree.
- `shepherd:context` skill `cmd_worktree.sh` — the helper.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/agent-briefs.md` —
  brief template carrying `[BASE-COMMIT-EXPECTED]`.
