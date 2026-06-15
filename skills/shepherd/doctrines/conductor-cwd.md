---
title: conductor anchor discipline (cwd + HEAD + worktree context)
description: |
  The conductor stays anchored to the sprint root: its working directory,
  its checked-out branch, and its active worktree are all the sprint root's.
  Worktrees are inspected via `git -C <path>` and `Read`, never via `cd`,
  `git switch`, `git checkout`, or `git worktree add` from inside a worktree.
  Any drift here is a silent fault — commits land on the wrong branch and/or
  new worktrees nest inside existing ones, producing dangling state the
  cherry-pick cycle cannot recover.
---

# Doctrine — Conductor Anchor Discipline

> Project-agnostic principle: the conductor process holds three pieces of
> persistent state across Bash calls — current working directory (`cwd`),
> checked-out branch (`HEAD`), and active worktree (the worktree whose path
> contains `cwd`). All three default to the **sprint root** at session
> open. If any of the three drifts mid-session, subsequent `git`, `Write`,
> and `Edit` operations silently target the wrong context. Recovery is
> never clean.
>
> Field origin: shepherd v5.0.1 conductor feedback (downstream Rust service),
> §2.1 — `cd <worktree>` drifted cwd and conductor commits landed on lane
> branches. v5.0.3 codified the cwd ban. v5.0.6 extends the doctrine to
> HEAD-state and worktree-nesting, after a follow-on field report that the
> conductor's `git switch <agent-branch>` (for "inspection") produced
> worktrees-within-worktrees state when the next `shctx worktree create-batch`
> resolved its base from the drifted HEAD.

## The rule (three anchors, never drift)

The conductor's anchor triple is fixed at session open and **never changes**
mid-session:

| Anchor | Bound to | Drift mechanism (BANNED) | Inspection path (USE) |
|---|---|---|---|
| `cwd` | sprint root (`shepherd.toml`'s directory) | `cd`, `pushd` | `git -C <path>` + absolute `Read`/`Write` |
| `HEAD` | `{sprint_branch}` | `git switch`, `git checkout`, `git restore --source` | `git -C <worktree-path> rev-parse HEAD` |
| worktree | primary worktree (row 1 of `git worktree list`) | `git worktree add` run from inside a worktree | always run `git worktree add` from sprint root |

A drift in **any** of these silently re-targets every subsequent operation.
The Bash tool's persistence guarantee — *"The working directory persists
between commands, but shell state does not"* — applies to cwd; git's HEAD
file persists on disk for HEAD; the active worktree is derived from cwd.
There is no shell-level safety net. **Prevention is mandatory.**

## The bans (explicit, with the correct alternative for each)

### Ban 1 — `cd` / `pushd` into a worktree

```bash
# BANNED — drifts cwd; next `git commit` lands on the worktree's branch
cd .claude/worktrees/agent-XXX
pushd .claude/worktrees/agent-XXX

# CORRECT — inspect with -C, write with absolute paths
git -C .claude/worktrees/agent-XXX log -5 --oneline
git -C .claude/worktrees/agent-XXX show HEAD --stat
Read(file_path: "/abs/.claude/worktrees/agent-XXX/path/to/file.rs")
```

### Ban 2 — `git switch` / `git checkout` to an agent lane branch

```bash
# BANNED — drifts HEAD; subsequent commits land on agent-XXX's branch,
# AND any later `shctx worktree create-batch --from $(current branch)`
# resolves its base from the drifted HEAD → worktrees-within-worktrees.
git switch agent-XXX
git checkout agent-XXX
git checkout agent-XXX -- some/file.rs

# CORRECT — inspect via -C; cherry-pick via git fetch / cherry-pick;
# read files via the Read tool at absolute paths
git -C .claude/worktrees/agent-XXX log --oneline
git fetch ./.claude/worktrees/agent-XXX HEAD
git cherry-pick FETCH_HEAD
```

Branch operations the conductor **does** perform (per
`references/branching-model.md`):

- `git checkout {patch_branch}` / `{sprint_branch}` / `{main_branch}` —
  ONLY the three project-managed branches in the branching model. Never
  an `agent-<lane-id>` branch.
- `git checkout -b {next_sprint_branch}` at sprint close — creating the
  next sprint branch off the patch branch.

Agent lane branches (`agent-*`, `lane-*`, anything created by `shctx
worktree create-batch` or `Agent({ isolation: "worktree" })`) are
**permanently off-limits** to the conductor's HEAD.

### Ban 3 — `git worktree add` from inside a worktree

```bash
# BANNED — git resolves the new worktree's base path relative to the
# CURRENT worktree, producing nested .claude/worktrees/.../.claude/worktrees/...
# state that the cleanup logic does not handle.
cd .claude/worktrees/agent-XXX
git worktree add ../agent-YYY -b lane-YYY    # ← nested!

# CORRECT — always run `git worktree add` from the sprint root, with
# explicit absolute paths, OR use the helper which enforces this for you:
shctx worktree create-batch lane-1 lane-2 lane-3 --from "$SPRINT_BRANCH"
```

`shctx worktree create-batch` resolves `shctx_repo_root` from the current
git toplevel, so calling it from inside a worktree silently nests too —
the helper is only safe when invoked from the sprint root. This is the
same invariant by a different surface.

## Why each ban matters

- **Ban 1 (cwd)** — a commit issued after a drifted `cd` lands on the
  worktree's branch and is invisible to the sprint branch until cherry-pick.
  When `shctx worktree merge` later runs, the conductor's stray commit may
  be silently re-played or silently dropped depending on the cherry-pick
  conflict path.
- **Ban 2 (HEAD)** — a drifted HEAD plus a subsequent `git commit` produces
  a *signed* commit on the lane branch with the conductor as author and
  the sprint branch as the *intended* target. The auditor swarm's
  `code-quality` check greps for `agent-XXX` commits authored by the
  conductor's git ident and fails the close. Worse: a subsequent `shctx
  worktree create-batch --from HEAD` records the drifted SHA as the brief's
  `[BASE-COMMIT-EXPECTED]`, propagating the wrong base into every lane in
  the next wave.
- **Ban 3 (worktree nesting)** — nested worktrees are not handled by
  `git worktree list` consistently across git versions, and `git worktree
  remove` from the outer worktree can leave the inner worktree's `.git`
  pointer dangling. The cleanup path that runs at sprint close
  (`branching-model.md` §II.4) does not see nested worktrees and skips
  them; the next session-open hygiene check fails on orphans nobody
  intended to create.

## Mandatory verification (run at session open + before every worktree op)

```bash
# 1. cwd is the primary worktree, not a sub-worktree.
pwd
# Expect: matches row 1 of `git worktree list` (the bare/primary line).

# 2. HEAD is the sprint branch (or patch/main during release plumbing),
#    never an agent-* branch.
git rev-parse --abbrev-ref HEAD
# Expect: matches {sprint_branch} from shepherd.toml resolution.

# 3. We are not inside a sub-worktree.
[[ "$(git rev-parse --git-dir)" == "$(git rev-parse --git-common-dir)" ]] \
  || { echo "DRIFT: inside a sub-worktree"; exit 1; }
```

If any of the three fails, **HALT**. Recovery procedure:

```bash
# Recover cwd
cd "$(git -C "$(pwd)" worktree list --porcelain | awk '/^worktree /{print $2; exit}')"

# Recover HEAD (back to sprint branch)
git checkout "{sprint_branch}"

# Verify before any further git operation
pwd
git rev-parse --abbrev-ref HEAD
git rev-parse --git-dir
git rev-parse --git-common-dir
```

Re-run the three-check before continuing. Do **not** issue any
`Write`/`Edit`/`git commit`/`git worktree` operation until all three
checks pass.

## When the rule does not apply

- **Coders, auditors (read-only), workers** dispatched via the `Agent`
  tool start in their own subprocess; they have their own cwd/HEAD/worktree
  triple. Subagents may freely inhabit a worktree — that is the entire
  point of parallel coder dispatch. The doctrine binds the **conductor's
  session only**.
- **Sprint-close branch operations** (cut next sprint, rebase-merge into
  patch, squash-merge to main) operate on project-managed branches, not
  agent lane branches. They are allowed and required.

## HEAD advancement in no-isolation mode (v5.0.6 clarification)

When coders are dispatched in **no-isolation mode** (per
`worktree-base-drift.md §Canonical no-isolation workaround`), each coder
commits directly to the sprint branch. The conductor's HEAD therefore
advances as coders complete and commit.

This is **not a violation** of the conductor anchor discipline. The anchor
rule says conductor HEAD stays on `{sprint_branch}` — it does. It says
nothing about HEAD being pinned to a specific SHA. HEAD-at-`{sprint_branch}`
is the invariant; the specific commit it points to is expected to advance.

**What to verify** (mandatory after each coder returns in no-isolation mode):

```bash
# HEAD still on sprint branch (not an agent-* branch)
git rev-parse --abbrev-ref HEAD
# Should return: {sprint_branch}

# Check what landed
git log --oneline -5
```

Do NOT verify HEAD SHA against `[BASE-COMMIT-EXPECTED]` (that field is only
present in worktree-mode briefs). In no-isolation mode, simply verify the
branch name and inspect the log.

## See also

- `worktree-base-drift.md` — companion doctrine: agent worktrees must
  branch from the sprint HEAD, not from a drifted conductor HEAD.
- `worktree-confinement.md` — the coder-side mirror: subagents must keep
  their writes inside the worktree.
- `references/branching-model.md` §V.1 — session-open hygiene check that
  surfaces orphan branches produced by earlier drift.
- `chain-repair.md` — recovery pattern when state drift is detected
  mid-sprint.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` §VII anti-patterns #15
  + #22 — the conductor-side cues that surface this doctrine at runtime.
