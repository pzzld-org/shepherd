---
title: conductor cwd discipline
description: |
  The conductor stays in the sprint root. Worktrees are inspected via `git -C
  <path>` and `Read`, never via `cd <worktree>`. The `cd` persists across Bash
  calls and is the documented cause of conductor commits landing on the wrong
  branch.
---

# Doctrine — Conductor cwd Discipline

> Project-agnostic principle: the Bash tool's working-directory state persists
> across calls, and any `cd` into a worktree silently re-targets subsequent
> `git commit`s to the worktree branch. This applies to every project, not
> just the one this doctrine was compiled from.
>
> Field origin: shepherd v5.0.1 conductor feedback (axiom v0.3.0-dev.4 XL),
> §2.1. v5.0.3 codifies the prevention.

## The rule

The conductor's working directory is the **sprint root** (the path where
`shepherd.toml` lives). It is set once at session open and **never changes**
mid-session. Specifically:

- **NEVER `cd <worktree-path>`** — the Bash tool's working directory persists
  across calls. A subsequent `git commit` in that session lands on the
  worktree branch, not the sprint branch.
- **NEVER `cd .claude/worktrees/...`** for any reason — inspection or
  otherwise.
- **NEVER `pushd` / `popd`** — same persistence hazard.

## How to inspect a worktree without leaving the sprint root

Use `git -C <path>` for every git operation, and absolute paths for every
file operation:

```bash
# Inspect a coder worktree's commit log
git -C .claude/worktrees/agent-XXX log -5 --oneline

# Diff a worktree's last commit
git -C .claude/worktrees/agent-XXX show HEAD --stat

# Read a specific file in the worktree
# (use the Read tool with the absolute path — not cat via Bash)
Read(file_path: "/abs/path/.claude/worktrees/agent-XXX/path/to/file.rs")

# Cherry-pick from a worktree branch into the sprint branch
# (run from the sprint root, not from the worktree)
git fetch ./.claude/worktrees/agent-XXX HEAD
git cherry-pick FETCH_HEAD
```

## Verification (any time the conductor doubts state)

```bash
# Confirm cwd is sprint root, not a worktree
pwd
# Should match the row 1 of `git worktree list` (the main worktree).

# Confirm checked-out branch is the sprint branch, not a worktree branch
git rev-parse --abbrev-ref HEAD
# Should match {sprint_branch} from shepherd.toml resolution.
```

If `pwd` returns anything ending in `.claude/worktrees/...`, **HALT**. Run
`cd <sprint-root>` in the next Bash call and verify before any `git`
operation.

## Why this is non-negotiable

The Bash tool documents:

> The working directory persists between commands, but shell state does not.

A conductor that forgets this AND drifts into a worktree AND runs `git
commit` will quietly land work on the wrong branch. The error is silent —
no exception raised, no warning emitted. Recovery is cherry-pick churn at
best, and lost commits at worst when the worktree is later cleaned up by
`git worktree remove`. **Prevention is mandatory.**

## When the rule does not apply

- **Coders** dispatched into worktrees via `isolation: "worktree"` start in
  the worktree by design — that is the agent's home. The doctrine is
  specifically for the conductor (main chat), not for flock agents.
- **Workers** doing branch cleanup may need to operate inside worktrees —
  use `git -C <path>` from the sprint root rather than `cd`.

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` §III — sprint-root
  invariant referenced in the conductor checklists.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md` — the
  recovery pattern when state drift is detected mid-sprint.
