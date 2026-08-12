---
title: branching-model
description: Machine-readable branch lifecycle (cut/work/rebase/delete/release), the version-scale tiers, and the hygiene checks every shepherd session enforces. Use when cutting, rebasing, or releasing a branch.
---

# Branching Model — Version Cascade Lifecycle

Every shepherd session enforces this model. Drift from it produces orphan branches — see §V for recovery. Configured per-project via `shepherd.toml [branching]`: `{patch_branch}` = `patch_branch_pattern` (e.g. `v0.2.9`); `{sprint_branch}` = `sprint_branch_pattern` (e.g. `v0.2.9-dev.5`); `{sprints_per_patch}` = `sprints_per_patch` (default 10); `{main_branch}` = `main_branch` (default `main`). Examples below use the default mod-10 convention.

## I. Numbering scheme (default mod-10)

```
{sprint_branch} — v{MAJOR}.{MINOR}.{PATCH}-dev.{SPRINT}
  MAJOR ∈ ℤ⁺ UNBOUNDED   MINOR/PATCH ∈ {0..N-1} MOD-N (N=10)   SPRINT ∈ {0..N-1} MOD-N (N={sprints_per_patch})
```

**Hard invariant:** every patch has EXACTLY `{sprints_per_patch}` dev sprints. **No `dev.{sprints_per_patch}` ever — hitting it is a missed-release-trigger emergency. STOP and reconcile.** The sprint after `dev.{last}` is ALWAYS `dev.0` of the NEXT patch, never `dev.{sprints_per_patch}` — the next patch branch cannot exist until the current patch squashes to `{main_branch}`, tags, releases, and cuts from `{main_branch}` with a version bump. The release pipeline is therefore the unavoidable second half of every `dev.{last}` close.

## II. Sprint branch lifecycle

**II.1 CUT** (from `{patch_branch}`): `git checkout {patch_branch} && git pull --ff-only origin {patch_branch}; git checkout -b {sprint_branch}; git push -u origin {sprint_branch}`.

**II.2 WORK**: INTRO → BODY → CLOSE (`references/pipeline.md §INTRO`, `§CLOSE`). All commits land on `{sprint_branch}`, pushed between waves.

**II.3 REBASE-MERGE INTO PATCH**: `git checkout {patch_branch} && git pull --ff-only origin {patch_branch}; git rebase {sprint_branch}` (or `git merge --ff-only`); `git push origin {patch_branch}`.

**II.4 DELETE — NON-NEGOTIABLE**, both remote AND local, regardless of merge path (gh PR merge, direct rebase, autorun): `git push origin --delete {sprint_branch}; git branch -d {sprint_branch}; git fetch --prune origin`. A dev branch surviving on origin after merge is a process violation — `gh pr merge --delete-branch` alone is insufficient for solo/direct-rebase paths that never fire it, so this step is explicit regardless of path.

## III. Patch lifecycle (the `dev.{last}` release pipeline)

Fires per `[release].driver` when `{sprint_branch}` (SPRINT = `{sprints_per_patch}-1`) rebases into `{patch_branch}`:

- **`conductor`** — shepherd runs the full 7 steps: squash-PR `{patch_branch}`→`{main_branch}` + merge; tag; `gh release create`; compute rollover (§IV); cut next patch from `{main_branch}`; bump version files (`[branching.version_files]`); cut next `dev.0`.
- **`github-workflow`** — shepherd only opens the release PR; `[release].workflow_file` runs steps 2–7 on merge.
- **`operator`** — shepherd writes release notes only; operator runs all 7 steps manually.

## IV. Rollover algorithm

```
next_version(X, Y, Z):
  if Z < {sprints_per_patch}-1: return (X, Y, Z+1)
  if Y < {sprints_per_patch}-1: return (X, Y+1, 0)
  return (X+1, 0, 0)
```

Reuses `{sprints_per_patch}` as the mod-N base for MINOR and PATCH; override per-level via `[branching].mod_base = { sprint, patch, minor }` (advanced, defaults suffice for most projects).

## V. Hygiene (every session enforces these)

**V.1 session-start orphan-detection** — at every `/shepherd:*` invocation, list dev branches already merge-based into their patch; surface any hit to the operator before continuing (a forgotten delete from a prior session).

**V.2 pre-cut** — verify `{patch_branch}` matches origin exactly; verify no orphan dev branches remain for this patch.

**V.3 pre-rebase** — gates MUST pass at `{sprint_branch}` HEAD; the branch MUST have no merge commits (linear history required for a clean rebase).

**V.4 post-rebase** — verify the dev commits landed in `{patch_branch}`; re-run gates on patch HEAD. If gates fail post-rebase: `git reset --hard origin/{patch_branch}` (revert), file the failure as a hot-fix lane, and do NOT delete the dev branch yet.

**V.5 orphan recovery** — confirm the merge is solid before deleting an orphan; an orphan with commits NOT in the patch (failed-rebase residue) is surfaced to the operator for triage, never auto-deleted.

## VI. Direct-commit-to-main rule

NEVER direct-commit to `{main_branch}` unless `[branching].allow_direct_main_commit = true` — NEVER true for a non-bootstrap project. The squash-merge from patch is the ONLY path under normal operation. A genuine hot-fix on main: cut off `{main_branch}` → apply the fix → PR + critic gate + auditor pass → squash-merge back to `{main_branch}` → cherry-pick the squash commit into the active patch branch.

## VII. Custom branch models

Non-mod-10 conventions configure `[branching]` accordingly (`docs/customization.md`). The lifecycle (cut → work → rebase → DELETE → cut next) applies identically; only pattern interpolation changes.

## VII-bis. Parallel lane cherry-pick conflicts

When N coders run in parallel with `isolation: "worktree"`, file overlap between lane branches IS possible even with disjoint `[FILE-SCOPE]` lists — both lanes touching `mod.rs`/`lib.rs` for a re-export, two lanes editing the same test file, or overlapping generated bindings. **Expected conductor behavior at WAVE-GATE rebase:** these cherry-pick conflicts ARE the conductor's job to resolve, NOT a framework bug. Resolve with `--ours`/`--theirs` or manual edit; keep BOTH sides' additions for `mod.rs`/`lib.rs`. Use `-X theirs`/`-X ours` ONLY for whitespace/comment-only conflicts — NEVER on logical code conflicts.

**`SCOPE OVERFLOW` vs. expected conflict:** a conflict on a file in one coder's `[FILE-SCOPE]` that ALSO appears in another coder's commit but was NOT in that coder's scope is a violation — flag `SCOPE OVERFLOW`. A conflict on a file BOTH coders legitimately had in MAY-MODIFY is not a violation, just a merge. Mitigation: allocate shared files (`mod.rs`/`lib.rs`) to exactly one lane's MAY-MODIFY and all others' MUST-NOT-TOUCH, or partition by line range (`references/flock.md §Brief assembly` `[SHARED-FILE-RULE]`).

## Version scale

Four tiers, each a binding scope-to-sprint-count factor — **scope is workload-scale, NEVER a quality bar.** `--scope sprint|patch|minor|version` (`references/spawn-flags.md §--scope`) declares how many sprints a spawn session walks; it does NOT permit downscoping a seed's contents or a conductor coming up short on lane delivery, gate honesty, or close-grade thresholds. "This is just a patch" / "since it's only a small sprint" / "we can defer this to a hot-fix" are FRAMEWORK-RECOGNIZED MALPRACTICE. A `--scope patch` run with 9 lanes/sprint executes 9 lanes/sprint, full stop — halt rather than ship short.

| Tier | Form | Sprint capacity | What it is |
|---|---|---|---|
| Major | `vX` | ~1000 sprints | Generational vision; direction anchor |
| Minor | `vX.Y` | ~100 sprints | Multi-year practical roadmap, ~10 patches |
| **Patch** | **`vX.Y.Z`** | **≤10 sprints** | The planning unit |
| Dev sprint | `vX.Y.Z-dev.N` (branch only) | 1 sprint | The unit of work |

A patch commits to a MAX of 10 dev sprints, names one theme, decomposes into ordered sprints; >10 → split into `vX.Y.{Z}` + `vX.Y.{Z+1}`. <2 sprints is fine — the planter does NOT gatekeep on perceived semver size.

**File-naming — patch-scoped for FINAL artifacts.** The patch-arc seed, the patch plan, and all roadmap artefacts live in the patch-slug run dir (`runs/vXYZ/`, slug form per `references/seed-template.md §File path`), NEVER a dev-sprint one. `-dev.N` NEVER appears in CHANGELOG entries, tags, or release PR titles — this does NOT forbid intermediate per-sprint seeds (`runs/vXYZ-devN/seed.md`), which legitimately carry it. A patch with multiple dev sprints gets ONE plan file (`runs/vXYZ/plan.md`), organized into phases/waves — never one plan file per sprint.

**Dev branches are an optional execution affordance, not a mandate.** Use for architectural change, money-path code, multi-coder parallel risk, or a clean per-sprint history. Skip for meta/doc-only repos, single-file fixes, or hot-fixes (`chain-repair`, `references/pipeline.md §Phase-0 amendment`). Artefact naming is unaffected either way.

**Anti-patterns:** `dev.N` in a patch-arc run-dir name, CHANGELOG, tag, or release-PR title; a patch seed >10 sprints of scope; a separate plan file per dev sprint; a dev sprint promising but not delivering operator-visible change (seed/impl drift → critic RECONSIDER + auditor completeness C+ cap — never reclassify as a `@worker` dispatch to dodge grade exposure); treating dev branches as mandatory; conflating shepherd's "patch" (umbrella) with standard-practice "patch" (small fix, what shepherd calls a dev sprint).

## See also

- `skills/shepherd/SKILL.md §Sprint contract` — dev.N patch-grade scope, branch topology summary
- `references/pipeline.md §Gates` — cargo-sequential gate execution
- `references/seed-template.md` — seed/plan run-dir slug form
- `references/grading-rubric.md` — completeness cap on undelivered scope
- `docs/configuration.md` — `[branching]` schema
- `docs/customization.md` — alternative branch/release models
