---
title: Branching Model — version cascade lifecycle
description: The literal, machine-readable model for branch lifecycle. Defines pattern interpolation, branch creation/rebase/deletion rules, rollover algorithm, and the hygiene checks every shepherd session enforces. Authoritative reference; SKILL.md cites this file.
---

# Branching Model — Version Cascade Lifecycle

The literal model for branch lifecycle. Every shepherd session (planter, conductor, autorun, parallel) enforces this model. Drift from this model is a process violation that produces orphan branches — see Hygiene §V for the recovery procedure.

The model is configured per-project via `shepherd.toml [branching]`. Throughout this doc:

- `{patch_branch}` is the resolved value of `[branching].patch_branch_pattern` (e.g., `v0.2.9` for the v0.2.9 patch under default config)
- `{sprint_branch}` is the resolved `[branching].sprint_branch_pattern` (e.g., `v0.2.9-dev.5`)
- `{sprints_per_patch}` is `[branching].sprints_per_patch` (default 10)
- `{main_branch}` is `[branching].main_branch` (default `main`)

Examples in this doc use the default mod-10 dev.{0..9} convention; substitute your project's pattern.

---

## I. Numbering scheme (default mod-10)

```
{sprint_branch}  — e.g., v{MAJOR}.{MINOR}.{PATCH}-dev.{SPRINT}

  MAJOR   ∈ ℤ⁺          UNBOUNDED
  MINOR   ∈ {0..N-1}    MOD-N (default N=10)
  PATCH   ∈ {0..N-1}    MOD-N
  SPRINT  ∈ {0..N-1}    MOD-N where N = {sprints_per_patch}
```

**Hard invariants** (under default mod-10):

- Every patch has EXACTLY `{sprints_per_patch}` dev sprints. No `dev.{sprints_per_patch}` ever — hitting it is a missed-release-trigger emergency. STOP and reconcile.
- When dev.{last} of patch X.Y.Z closes, the cascade ratchets PATCH (and possibly MINOR / MAJOR per §IV).

**The "next sprint branch is always dev.0" corollary:** the sprint AFTER `dev.{last}` is `dev.0` of the NEXT PATCH — never `dev.{sprints_per_patch}`. The next patch branch cannot exist until the current patch arc squashes to `{main_branch}`, tags, releases, and the next patch branch is cut from `{main_branch}` with a version bump.

The release pipeline is therefore the natural and unavoidable second half of any dev.{last} close — it's mechanical, not gated.

---

## II. Sprint branch lifecycle (every dev.{N} within a patch)

### II.1 — CUT

Source: `{patch_branch}`.

```bash
git checkout {patch_branch} && git pull --ff-only origin {patch_branch}
git checkout -b {sprint_branch}
git push -u origin {sprint_branch}
```

### II.2 — WORK

Three-section pipeline (see SKILL.md §III): §1 INTRODUCTION → §2 BODY → §3 CLOSE. All commits land on `{sprint_branch}`; pushed to origin between waves.

### II.3 — REBASE-MERGE INTO PATCH

```bash
git checkout {patch_branch}
git pull --ff-only origin {patch_branch}
git rebase {sprint_branch}     # OR: git merge --ff-only {sprint_branch}
git push origin {patch_branch}

# Verify integration:
git log {patch_branch} --oneline | head -5
```

### II.4 — DELETE

**NON-NEGOTIABLE.** Both remote AND local:

```bash
git push origin --delete {sprint_branch}
git branch -d {sprint_branch}
git fetch --prune origin

# Verify deletion:
git ls-remote --heads origin {sprint_branch}    # expect: empty output
git branch | grep "{sprint_branch}"              # expect: empty output
```

A dev branch surviving on origin after step 3 is a **process violation**. Step 4 is required regardless of how the merge happened (gh PR merge, direct rebase, autorun).

**Why `--delete-branch` from `gh pr merge` is insufficient:** projects that skip the PR step for dev branches (solo workspace, direct rebase) never fire `--delete-branch`. Step 4 is explicit to handle both paths.

---

## III. Patch lifecycle (the dev.{last} release pipeline)

When `{sprint_branch}` (where SPRINT = `{sprints_per_patch}-1`) rebases into `{patch_branch}`, the **full patch lifecycle** fires per `[release].driver`:

### Driver = `conductor`

Shepherd runs the full pipeline.

```bash
# 1. SQUASH PATCH → MAIN
gh pr create --base {main_branch} --head {patch_branch} \
  --title "release: {patch_branch}" \
  --body-file [release].release_notes_path
gh pr merge <N> --squash --delete-branch

# 2. TAG
git checkout {main_branch} && git pull --ff-only origin {main_branch}
git tag -a {release_tag_pattern} -m "{patch_branch} — <one-line summary>"
git push origin {release_tag_pattern}

# 3. RELEASE
gh release create {release_tag_pattern} \
  --notes-file [release].release_notes_path

# 4. ROLLOVER (compute next version per §IV algorithm)

# 5. CUT NEXT PATCH
git checkout -b {next_patch_branch} {main_branch}
git push -u origin {next_patch_branch}

# 6. VERSION BUMP
# Edit all files referencing the prior version per [branching.version_files] (project config)

# 7. CUT NEXT dev.0
git checkout -b {next_sprint_branch} {next_patch_branch}
git push -u origin {next_sprint_branch}
```

### Driver = `github-workflow`

Shepherd authors release notes + opens the release PR; a GH Actions workflow handles squash/tag/release/cut-next on PR merge.

```bash
# Shepherd's only step:
gh pr create --base {main_branch} --head {patch_branch} \
  --title "release: {patch_branch}" \
  --body-file [release].release_notes_path
```

The workflow at `[release].workflow_file` runs steps 2–7 on the squash-merge commit.

### Driver = `operator`

Shepherd writes release notes; operator runs squash/tag/release manually.

```bash
# Shepherd's only step:
# (none — release notes already written by dev.{last} sprint close)
```

Operator runs steps 1–7 from the conductor sequence above.

---

## IV. Rollover algorithm

After `{sprint_branch}` (last sprint of patch) closes, compute the next version:

```
function next_version(current = (X, Y, Z)):
    # If PATCH < N-1, just bump PATCH:
    if Z < {sprints_per_patch} - 1:
        return (X, Y, Z+1)

    # PATCH = N-1: bump MINOR if MINOR < N-1
    if Y < {sprints_per_patch} - 1:
        return (X, Y+1, 0)

    # MINOR = N-1: bump MAJOR (MAJOR is unbounded)
    return (X+1, 0, 0)
```

**Note:** the framework reuses `{sprints_per_patch}` as the mod-N base for MINOR and PATCH because most projects keep them aligned (10 sprints per patch, 10 patches per minor, 10 minors per major). Projects that want different mod bases per level can override via `[branching].mod_base = { sprint = 10, patch = 10, minor = 10 }` (advanced config; defaults work for most).

---

## V. Hygiene (every session enforces these checks)

### V.1 — Session-start orphan-detection (one-liner)

At every `/shepherd:*` invocation, run:

```bash
# List dev branches NOT yet rebased into their patch branch
for dev_branch in $(git branch --list "{sprint_branch_pattern with N=*}" --format='%(refname:short)'); do
    patch=$(echo $dev_branch | sed 's/-dev\.[0-9]*//')
    if git merge-base --is-ancestor $dev_branch $patch 2>/dev/null; then
        echo "$dev_branch already merged into $patch — DELETE per §II.4"
    fi
done
```

If any output, the conductor surfaces the orphans to the operator before continuing — a forgotten dev-branch-delete from a prior session.

### V.2 — Pre-cut hygiene

Before cutting a new sprint branch:

```bash
# Verify the patch branch is up-to-date with origin
git fetch origin
git log origin/{patch_branch}..{patch_branch} --oneline   # expect: empty output
git log {patch_branch}..origin/{patch_branch} --oneline   # expect: empty output

# Verify no orphan dev branches exist for this patch
git branch --list "{sprint_branch_pattern_for_this_patch}"
```

### V.3 — Pre-rebase hygiene

Before rebasing dev into patch:

```bash
# Verify gates pass at HEAD
{gates.check}
{gates.lint}
{gates.format}
# (and any [gates.extra])

# Verify dev branch has no merge commits (must be linear for clean rebase)
git log {patch_branch}..{sprint_branch} --merges --oneline   # expect: empty output
```

### V.4 — Post-rebase hygiene

After step 3 (rebase) but before step 4 (delete):

```bash
# Verify the dev branch's commits are now in the patch branch
git log {patch_branch} --oneline | grep "<sprint identifier>"

# Run gates ONE more time on patch HEAD
{gates.check}
{gates.lint}
{gates.format}
```

If gates fail post-rebase, REVERT the rebase (`git reset --hard origin/{patch_branch}`), file the failure as a hot-fix lane, and DO NOT delete the dev branch yet.

### V.5 — Recovery from orphan branches

If V.1 surfaces an orphan dev branch that's already been merged into the patch:

```bash
# Confirm the merge is solid
git log {patch_branch} --oneline | grep "<orphan sprint identifier>"

# Delete the orphan
git push origin --delete <orphan>
git branch -d <orphan>
git fetch --prune origin
```

If the orphan has commits NOT in the patch (failed-rebase residue), surface to operator — those commits need triage before deletion.

---

## VI. Direct-commit-to-main rule

**NEVER** direct-commit to `{main_branch}` unless `[branching].allow_direct_main_commit = true` (which should be false for any non-bootstrap project).

The squash-merge from patch is the ONLY way commits reach `{main_branch}` under normal operation. Hot-fixes that genuinely belong on main go through:

1. Cut a hot-fix branch off `{main_branch}`
2. Apply the fix
3. PR + critic gate + auditor pass
4. Squash-merge back to `{main_branch}`
5. Cherry-pick the squash commit into the active patch branch

---

## VII. Custom branch models

Projects with non-mod-10 conventions configure `[branching]` accordingly. See `docs/customization.md` §"Custom branch / release model" for examples (5-sprint patches, calendar-versioned releases, monorepo per-package patches, trunk-based).

The framework's lifecycle (cut → work → rebase → DELETE → cut next) applies identically; only the pattern interpolation changes.

---

## VII-bis. Parallel lane cherry-pick conflict expectations (v5.0.9)

> Field origin: shepherd v5.0.8 conductor feedback (downstream Rust service) §3.

When N coders run in parallel with `isolation: "worktree"`, **file-overlap
between parallel lane branches IS possible** even when `[FILE-SCOPE]` lists are
designed to be disjoint. Common causes:

- Both lanes touch the same `mod.rs` (pub re-export) or `lib.rs` (crate root)
  to add an import/export — these files are often not in any lane's explicit
  MAY-MODIFY list but get implicitly modified.
- Two lanes add different functions to the same test file.
- One lane generates code that includes generated bindings another lane also
  generates.

**Expected conductor behavior at WAVE-GATE rebase:**

- Cherry-pick conflicts on shared files ARE expected and ARE the conductor's
  responsibility to resolve. They do not indicate a framework bug.
- Resolve with `git checkout --ours / --theirs` or manual edit as appropriate.
  For `mod.rs` / `lib.rs` additions, both sides' additions should be kept
  (they're additive).
- Use `-X theirs` or `-X ours` only when the conflict is on whitespace/comment
  wording (semantics-free). Never use these flags on logical code conflicts.

**Mitigation (for the engineer):**

- Explicitly allocate `mod.rs` / `lib.rs` in one lane's MAY-MODIFY list and
  add it to all other lanes' MUST-NOT-TOUCH lists.
- Or: use the `[FILE-SCOPE]` "MAY MODIFY: lines N..M" form (per
  `doctrines/coder-brief-format-shared-artifacts.md`) to partition shared files
  by line range.

**STAGE-GRAPH-VIOLATION vs. expected conflict:** A conflict on a file that IS
in a coder's `[FILE-SCOPE]` and also appears in another coder's worktree commit
(i.e., was NOT in that other coder's `[FILE-SCOPE]`) IS a violation — the other
coder wrote outside their scope. Flag with `SCOPE OVERFLOW` in the audit report.
A conflict on a file that BOTH coders legitimately touched (both had it in their
MAY-MODIFY) is NOT a violation — just a merge to resolve.

---

## VIII. See also

- `SKILL.md` §II — branch topology summary
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — `[branching]` schema
- `${CLAUDE_PLUGIN_ROOT}/docs/customization.md` — alternative models
- `seed-template.md` — frontmatter `parallel_with` field
- `flock.md` §IV — label/milestone discipline
