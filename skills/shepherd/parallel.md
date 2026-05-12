---
title: parallel
description: Multi-sprint worktree mode — runs N concurrent dev sprints of the current patch in parallel worktrees. Each runs the full /shepherd:start pipeline; conductor merges in dev-order on close. Maximum 5 concurrent sprints.
---

# shepherd/parallel — Multi-Sprint Parallel Mode

Activated by `/shepherd:parallel`. The conductor picks **N concurrent dev sprints** of the current patch (e.g., `dev.3`, `dev.4`, `dev.5` together), fans each into its own worktree with its own flock, then rebases them into the patch branch in dev-order on close.

This is fundamentally different from `/shepherd:autorun` (which runs sprints one after another) and from within-sprint coder parallelism (which `/shepherd:start` already does — see §note below).

> **Note on within-sprint parallelism:** `/shepherd:start` already dispatches parallel-safe coders in a single message — that is the mandatory default per the Brief-Validity Checklist and anti-pattern #1 in `flock.md`. You do NOT need `/shepherd:parallel` for that. `/shepherd:parallel` is specifically for running multiple **whole sprints** concurrently.

---

## When to use

Use `/shepherd:parallel` when:

- The patch-level seed has already decomposed multiple upcoming dev sprints (operator has authored several seeds in advance)
- Those sprints are scope-disjoint enough that they don't trip on each other (different packages, different services, different concerns)
- Operator says "run these N sprints in parallel"

Do NOT use when:

- Sprints are sequentially dependent (each builds on the prior)
- Schema migration or workspace-wide refactor is in flight in any candidate sprint
- The seeds for the candidate sprints don't yet exist or aren't operator-reviewed

---

## What the conductor does

1. **Confirm the sprint set with the operator.** Default behavior: report which dev seeds exist on disk and propose a parallelizable subset. Example:
   > "Seeds present for dev.3, dev.4, dev.5, dev.6. Of those, dev.3 (circuits) and dev.5 (gui) are scope-disjoint. dev.4 touches engine which dev.6 also reads. Suggest running dev.3 + dev.5 in parallel; dev.4 + dev.6 sequentially after. Confirm?"
2. **Cut a worktree per concurrent sprint** off the patch branch:
   ```bash
   git worktree add ../<repo>-wt-dev3 -b {sprint_branch_for_dev3} {patch_branch}
   git worktree add ../<repo>-wt-dev5 -b {sprint_branch_for_dev5} {patch_branch}
   ```
3. **Run the full /shepherd:start pipeline per worktree, concurrently.** Each worktree gets its own engineer → critic → coder waves → auditor swarm. Coder briefs include the absolute worktree path so each lane edits in the right tree.
4. **Gates run per worktree.** A failure in one worktree's gates does not block the others.
5. **Rebase into the patch branch in dev-order.** dev.3 merges before dev.5 even if dev.5 finishes first. Conductor pauses the merge order until predecessors are ready.
6. **Worktree cleanup** after merge: `git worktree remove ../<repo>-wt-devN`.

---

## Hard rules

- **One build-manifest writer at a time across all concurrent sprints.** If any candidate sprint touches a workspace build manifest that another candidate also touches, those sprints are not parallel-safe — drop one.
- **dev-order merge is non-negotiable.** Even if dev.5 finishes first, it waits for dev.3 to merge first. dev.{last} release pipeline only triggers after all prior sprints have merged.
- **Maximum 5 concurrent sprints.** Operational ceiling — context budget + worktree management get unwieldy past that.
- **No new dev sprint joins mid-flight without operator approval.** If new seeds appear after parallel mode started, they wait for the next /shepherd:parallel invocation.

---

## Hard stops (parallel-specific, in addition to autorun stops)

- Worktree corruption (`git worktree list` shows missing/locked entries)
- Two concurrent sprints both modifying the same build-manifest or the same package's public API
- Concurrent-sprint count > 5
- Conductor context budget approaching saturation

---

## Invocation

```
/shepherd:parallel
```

Conductor proposes the sprint set, operator confirms or trims, then fan-out begins.

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/commands/parallel.md` — command details
- `autorun.md` — sequential autopilot (the simpler sibling)
- `flock.md` — per-agent dispatch rules
- `SKILL.md` — conductor quick reference
- `superpowers:using-git-worktrees` — worktree creation discipline
- `superpowers:dispatching-parallel-agents` — parallel-fanout patterns
