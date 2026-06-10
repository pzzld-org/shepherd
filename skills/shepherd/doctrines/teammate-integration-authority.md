---
title: teammate integration authority
description: |
  Teammate-conductors NEVER integrate their own worktree into the dev branch.
  Integration is a root-exclusive, review-gated (LANE-INTEGRATE) decision.
  Enforced mechanically by teammate_git_guard.sh + halt code TEAMMATE-GIT-WRITE.
introduced: v6.0.9
related: "#99"
---

# Doctrine — Teammate Integration Authority

> The observed defect (GH #99): a teammate-conductor attempted a `git rebase`
> onto the dev branch mid-wave, producing a diverged sprint branch that root
> could not cleanly merge. The teammate's intent was correct (its lane was
> complete); the action was wrong (only root may integrate). This doctrine names
> the rule, the seam, and the mechanical guard so it cannot recur.

## The rule

**Teammate-conductors have no integration authority.**

A teammate's git authority is bounded to commits on its own worktree branch:
`git add` and `git commit` inside its assigned worktree are permitted.
Everything that moves work off that branch and onto a shared branch is
root-only:

- `git merge` — forbidden for teammates
- `git rebase` (onto dev or sprint branch) — forbidden for teammates
- `git push` (to dev or sprint branch) — forbidden for teammates
- `git cherry-pick` (onto dev or sprint branch) — forbidden for teammates

When a teammate reaches for any of these: STOP.
`SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)`.
Root handles the integration.

## The seam — LANE-INTEGRATE

Integration is a first-class pipeline seam, not an afterthought.
After a teammate lane's `WAVE-COMPLETE`, root executes a `LANE-INTEGRATE`
step (defined in `skills/shepherd/pipeline.md §II`) BEFORE merging the lane
diff into the dev branch:

1. **Small diffs** (< 200 lines changed): root reviews the diff inline
   (`git diff --stat` + `git diff` summary) and merges directly.
2. **Large diffs** (≥ 200 lines changed): root dispatches a single `@auditor`
   diff-review concern (`shctx graph compile --segment=lane-integrate-LN
   --verify`). Merge is blocked until the auditor's concern resolves.

`LANE-INTEGRATE` is conductor-inline in spawn mode (root owns it); in solo
mode the conductor IS root and integrates directly — same mechanical steps,
no team coordination required.

`LANE-INTEGRATE` is NEVER compiled into a Dynamic Workflow and NEVER delegated
to a teammate-conductor.

## Mechanical enforcement

`hooks/scripts/teammate_git_guard.sh` is a `PreToolUse(Bash)` guard:

- It reads `session_id` from the hook stdin.
- It looks up `session_id` in the `teammates` registry table.
- If the session is a non-retired teammate AND the Bash command is a
  dev-branch integration (`git merge`, `git rebase` onto a shared branch,
  `git push`, or `git cherry-pick` onto the dev branch): the guard denies
  the command and emits `TEAMMATE-GIT-WRITE`.
- In-worktree `git add`/`git commit` pass without restriction (no
  false-positive on legitimate lane commits).
- Sessions not in the `teammates` table (root, solo conductor, other tools)
  pass unconditionally.

The guard is config-gated via `shepherd.toml [spawn].teammate_git_guard`
(default `on`) and follows house style (`set -uo pipefail`, source
`_lib.sh || exit 0`, runaway-bounded, `log_event` every decision).

## Scope in solo mode

`/shepherd:start` (solo): the conductor IS root. There are no teammates.
The `LANE-INTEGRATE` seam exists conceptually as the point at which the solo
conductor reviews its own coder lanes' diffs before proceeding — the same
size-gated logic applies (large diffs still get an auditor concern). The
mechanical guard does not fire because no `teammates` rows exist.

## Why this matters

Three consequences of a teammate integrating itself:

1. **Diverged sprint branch.** Root's subsequent wave-gate runs a rebase
   that conflicts with the teammate's unauthorized rebase. Sprint halts.
2. **Lost wave-gate signal.** Root's gate (the authoritative pass/fail) fires
   on an already-rebased branch, producing a false-pass or a duplicate commit.
3. **Audit trail break.** The integration commit has no corresponding
   `LANE-INTEGRATE` review record — the completeness auditor flags this at
   close as an off-graph dispatch.

Integration authority at root keeps the sprint branch's history linear,
auditable, and under one owner.

## See also

- `pipeline.md §II` — `LANE-INTEGRATE` node in the stage taxonomy
- `pipeline.md §XII` — YAML node shape for `LANE-INTEGRATE`
- `pipeline.md §XIII` anti-pattern 10 — "Teammate lane merged without LANE-INTEGRATE review"
- `dispatch-tier-separation.md §IV-bis.8` — `TEAMMATE-GIT-WRITE` halt code mechanics
- `agents/conductor.md §Hard prohibitions #19` — teammate git custody
- `agents/shepherd.md §Side-effect boundary` — `LANE-INTEGRATE` in the root write table
- `hooks/scripts/teammate_git_guard.sh` — the mechanical guard
