---
name: parallel
description: Run N concurrent dev sprints of the current patch in parallel worktrees. Conductor proposes a parallel-safe sprint set, operator confirms, each sprint runs the full /shepherd:start pipeline in its own worktree, then merges in dev-order. Maximum 5 concurrent sprints.
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:parallel — Multi-Sprint Parallel Mode

Runs **N concurrent dev sprints** of the current patch in isolated worktrees. Each worktree runs the full `/shepherd:start` pipeline (engineer → critic → coder waves → auditor swarm). Conductor merges them into the patch branch in **dev-order** as they finish.

This is NOT within-sprint coder parallelism — that is already mandatory in `/shepherd:start` (parallel-safe coders MUST be batched in a single message per the Brief-Validity Checklist). This is **multiple whole sprints at once**.

## When

Use when the operator has authored multiple sprint seeds in advance and several are scope-disjoint. Operator says "run dev.3 + dev.5 in parallel" or similar.

Do NOT use when:
- Sprints are sequentially dependent (each builds on the prior)
- Schema migration or workspace-wide refactor is in flight in any candidate sprint
- The seeds for the candidate sprints don't yet exist or aren't operator-reviewed

## Step 0 — Auto-orient + propose sprint set

1. Load `superpowers:using-superpowers`, `superpowers:using-git-worktrees`, `superpowers:dispatching-parallel-agents`.
2. Read `shepherd.toml`. Detect current patch branch from `[branching]`.
3. Inventory existing dev seeds: `ls {paths.plans}/{sprint_slug_pattern with N as wildcard}.seed.md`.
4. Read each seed's scope summary; identify build-manifest writers, shared packages, public-API touchpoints.
5. **Propose a parallel-safe subset to the operator.** Example:
   > "Seeds present: dev.3 (circuits), dev.4 (engine), dev.5 (gui), dev.6 (bin/node). Parallel-safe pairs: {dev.3, dev.5} (no overlap), {dev.4, dev.6} (engine ↔ bin/node coupling — sequential). Suggest run dev.3 + dev.5 concurrently. Confirm or amend?"
6. Wait for operator confirmation before cutting any worktree.

## Step 1 — Fan out worktrees

For each confirmed sprint:

```bash
git worktree add ../<repo>-wt-<sprint-slot> -b {sprint_branch} {patch_branch}
```

The new worktree directories live OUTSIDE the main repo, side-by-side. Each gets its own conductor session.

## Step 2 — Run the full /shepherd:start pipeline per worktree, concurrently

Each worktree gets its own engineer → critic → coder waves → auditor swarm. Coder briefs include the absolute worktree path so each lane edits in the right tree.

## Step 3 — Gates run per worktree

A failure in one worktree's gates does not block the others.

## Step 4 — Rebase into the patch branch in dev-order

dev.3 merges before dev.5 even if dev.5 finishes first. Conductor pauses the merge order until predecessors are ready.

## Step 5 — Worktree cleanup

After merge: `git worktree remove ../<repo>-wt-<sprint-slot>`.

## Hard rules

- **One build-manifest writer at a time across all concurrent sprints.** If any candidate sprint touches a workspace build manifest (Cargo.toml, package.json, pyproject.toml, go.mod) that another candidate also touches, those sprints are not parallel-safe — drop one.
- **dev-order merge is non-negotiable.** Even if dev.5 finishes first, it waits for dev.3 to merge first. dev.{last} release pipeline only triggers after all prior sprints have merged.
- **Maximum 5 concurrent sprints.** Operational ceiling — context budget + worktree management get unwieldy past that.
- **No new dev sprint joins mid-flight without operator approval.** If new seeds appear after parallel mode started, they wait for the next /shepherd:parallel invocation.

## Hard stops (parallel-specific, in addition to the autorun stops)

- Worktree corruption (`git worktree list` shows missing/locked entries)
- Two concurrent sprints both modifying the same build-manifest or the same package's public API
- Concurrent-sprint count > 5
- Conductor context budget approaching saturation

## Invocation

```
/shepherd:parallel
```

Conductor proposes the sprint set, operator confirms or trims, then fan-out begins.

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/parallel.md` — full parallel-mode behavior
- `${CLAUDE_PLUGIN_ROOT}/commands/start.md` — within-sprint pipeline (used per worktree)
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/flock.md` — per-agent dispatch rules
- `superpowers:using-git-worktrees` — worktree creation discipline
- `superpowers:dispatching-parallel-agents` — parallel-fanout patterns
