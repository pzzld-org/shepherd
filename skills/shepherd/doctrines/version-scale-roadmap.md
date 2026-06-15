# Version-scale roadmap — what each version level commits to

> **Origin:** v5.1.3 (2026-05-19). Operator: "I would like to see a version-based plan & seed scale factor."
> **Hardened:** v6.0.0 (2026-05-28) — added scope-is-not-a-quality-bar opening note after recurring observation that planters and shepherds were using "it's just a patch" as cover to defer or downscope work (FL03/shepherd #66, a downstream Rust service).

> **Scope is workload-scale, NEVER a quality bar (binding, v6.0.0).** `--scope sprint`, `patch`, `minor`, `version` (per `doctrines/scope-scale-workload.md`) declare how many sprints a spawn session will walk. They do NOT permit a planter to defer or downscope the contents of any individual seed, and they do NOT permit a conductor to come up short on lane delivery, gate honesty, or close-grade thresholds. The seed is the contract; the scope flag only governs how many sprints are walked. Phrases like "this is just a patch", "since we're only doing a small sprint", "we can defer this to a hot-fix" — these are framework-recognized malpractice patterns. A `/shepherd:spawn --scope patch` run with 9 lanes per sprint executes 9 lanes per sprint, full stop. If real-work cannot land, halt rather than ship short.

This doctrine establishes a binding scale factor between the version level a seed or plan addresses and the number of sprints it commits to. It governs how upstream artefacts (vision documents, roadmaps, patch plans) decompose into the actual unit of execution: the shepherd **dev sprint**.

It extends `doctrines/sprint-as-patch.md` upward. Where sprint-as-patch says "every dev sprint is operator-equivalent to a full patch theme," this doctrine names the three levels above the dev sprint and what each commits to.

## Terminology bridge — "patch" in shepherd vs in standard git practice

Read this first. The word "patch" appears in two distinct senses and conflating them causes drift:

| Term | Meaning |
|---|---|
| **Standard-practice "patch"** | A small fix. Bug correction, typo, one-file change. What `vX.Y.{Z+1}` connotes in plain semver. |
| **Shepherd "dev sprint"** (`vX.Y.Z-dev.N`) | A substantive delivery — what an outside observer would call a *patch worth of work*. Operator-visible improvement, SUBTRACT delta, release-notes-eligible. |
| **Shepherd "patch branch"** (`vX.Y.Z`) | The umbrella. Cumulative known-good state. Collects up to 10 dev sprints under one theme before the next patch opens. |

When external tooling or convention says "patch," it usually means standard-practice patch. When shepherd says "dev sprint," it means what others call a patch. Shepherd's "patch branch" is one level higher than either of those — it is the planning unit, not the unit of work.

If a downstream tool (CC, CI rules, contributor expectations) fights you over this, the resolution is **shepherd's "dev sprint" = traditional "patch"** in mental conversion. The vocabulary mismatch is friction, but the model is consistent.

## The four tiers

| Tier | Form | Sprint capacity | What it is |
|---|---|---|---|
| Major | `vX` | ~1000 sprints | The largest imaginable roadmap. Generational vision. Captures where the project could go over its full lifetime. |
| Minor | `vX.Y` | ~100 sprints | The practical long-term roadmap. What we plan toward over a multi-year horizon. Has ~10 patches in it. |
| **Patch** | **`vX.Y.Z`** | **≤ 10 sprints** | The implementable arc. Concrete goals + deliverables for a near-term theme. **The planning unit.** |
| Dev sprint | `vX.Y.Z-dev.N` (branch only) | 1 sprint | Where actual work happens. Each is "a patch worth of work" by traditional vocabulary. |

## File-naming rule — seeds and plans live at PATCH scope

**The patch-arc seed, the patch plan, and all roadmap artefacts are named for the patch (`vX.Y.Z`), NOT the dev sprint (`vX.Y.Z-dev.N`).** (Intermediate per-sprint *seeds* are the exception — see below.)

| Artefact | Filename pattern | Example |
|---|---|---|
| Patch seed | `vXYZ-<topic>.seed.md` | `v514-teammate-parallel.seed.md` |
| Patch plan | `vXYZ-<topic>.plan.md` | `v514-teammate-parallel.plan.md` |
| Minor roadmap | `vXY-roadmap.md` | `v52-roadmap.md` |
| Major vision | `vX-vision.md` | `v6-vision.md` |

The slug rule (per `doctrines/seed-naming.md` and `[[slug-form-filenames]]` memory) collapses dots: `v514` not `v5.1.4`. **The `-dev.N` identifier NEVER appears in the FINAL shipped artefacts this rule governs — the patch-arc seed/plan, CHANGELOG entries, tags, and release PR titles are all patch-scoped (`vXYZ`).**

This restriction does **NOT** forbid intermediate per-sprint **seed** filenames. A multi-sprint patch executed via `/shepherd:start` (or fanned out by `/shepherd:spawn --parallel`) legitimately writes per-sprint seeds named `vXYZ-devN.seed.md` — those carry `-devN` by design, per `doctrines/seed-naming.md` and `references/seed-template.md §File path`. The patch-scope rule is about what the *patch arc* and the *shipped release* are named, not about the intermediate seeds a multi-sprint patch fans out into.

If a patch has multiple dev sprints, they are NOT each given their own plan file. The patch plan governs the arc; the engineer may amend or version the plan across sprints, but the filename stays at patch scope. Sprint-specific context (which lanes go in which wave of which sprint) lives inside the plan's body, organized by phase or wave.

## Dev branches are an optional execution affordance

The `vX.Y.Z-dev.N` branch is a **convenience pattern**, not a mandate.

**When to use dev branches** — large or risky work where you want a cushion:

- The sprint introduces architectural change (new package, schema migration, deprecated-API removal)
- The sprint touches business-critical / money-path code
- Multiple coders run in parallel and a catastrophic outcome would cost rebase work
- You want a clean per-sprint git history for review

**When to skip dev branches** — small or meta work where the cushion has no value:

- Meta repos (the shepherd plugin itself, documentation-only sprints, doctrine refinement)
- Single-file fixes where the patch branch can absorb the change directly
- Hot-fixes (per `doctrines/chain-repair.md` mechanical-drift hot-fix lanes)
- Any sprint where the operator judges the rollback risk too low to warrant a separate branch

**The artefact naming does not change either way.** Whether you cut a dev.N branch or commit directly to the patch branch, the seed and plan are still named `vXYZ-<topic>.{seed,plan}.md`.

## What each tier commits to

### Major (`vX`) — 1000-sprint vision

A generational commitment. Names the largest possible roadmap the operator can imagine. Most projects never see their `vX+1` document materialize because the roadmap fills before that horizon arrives — that is fine. The major doc exists to anchor the *direction*.

### Minor (`vX.Y`) — 100-sprint practical roadmap

Decomposes the major direction into themes the project will deliver across a multi-year horizon. Names which themes group into which patches. Revised periodically as reality diverges from the plan.

### Patch (`vX.Y.Z`) — ≤ 10-sprint focused arc (THE PLANNING UNIT)

The natural planning unit for shepherd. A patch seed:

- Commits to a maximum of 10 dev sprints worth of work
- Names a single theme or operator-visible deliverable
- Decomposes into ordered sprints (which depends on which)
- Stays at patch breadth — does NOT name implementation details that belong inside an individual sprint's lane decomposition

A patch with > 10 sprints of work is too large; split into `vX.Y.{Z}` + `vX.Y.{Z+1}`. Small patches (< 2 sprints) are not a problem — the framework executes whatever the seed describes. The planter does NOT gatekeep patch contents based on perceived semver size; the operator decides what a patch is for, and the seed describes the work.

### Dev sprint (`vX.Y.Z-dev.N` branch — optional) — the unit of work

Each dev sprint is "a patch worth of work" by traditional vocabulary. Substantive. Per `doctrines/sprint-as-patch.md`: ships operator-visible improvement, has SUBTRACT delta, is release-notes-eligible.

**A dev sprint is not small.** Operator framing: "every sprint should be as if a user had invoked some `/superpowers:brainstorming` then executed such plan without shepherd or whatever." Shepherd's contribution is making that workflow standard (seed → plan → semi-automatic dispatch via conductor) — not making the sprints themselves smaller.

## Implications for the engineer

The engineer authors **one plan per patch** by default. If the patch has multiple dev sprints, the plan organizes them into phases or waves rather than spawning multiple plan files. The plan filename is patch-scoped (`vXYZ-<topic>.plan.md`).

When `/shepherd:start` fires for sprint N of the patch:
- The engineer either authors the patch plan (if first sprint) OR amends it (if subsequent sprint)
- The amendment is dated and tracked under "Mid-patch plan deviations" in the plan footer
- The plan as a whole still names the full patch arc, not just sprint N

## Application to this plugin's own repo

The shepherd plugin's own repo uses this same scale factor:

- Current major: `v5` (the post-migration era; vision implicit in `CLAUDE.md`)
- Current minor: `v5.1` (the flock-with-discovery + hardened-hooks horizon)
- Current patch: `v5.1.3` (cleanup, cache discipline, dispatch telemetry — this sprint)
- The `v5.1.3-dev.1` branch exists as a convenience for this PR — the plugin repo would have been fine without it, since the work is meta and the rollback cushion offers little here. But it does no harm.

The v5.1.4 patch seed at `.artifacts/docs/plans/v514-teammate-parallel.seed.md` governs up to 10 dev sprints. Realistic decomposition is 1–3 dev sprints depending on Phase 0 findings. For a focused single-theme patch, fewer sprints is often better.

## Anti-patterns

- Putting `dev.N` in the **patch-arc** seed/plan filename (`v514-dev1-teammate-parallel.seed.md` as *the patch plan*) or in a CHANGELOG entry, tag, or release PR title — wrong; the patch arc and shipped release are patch-scoped (`vXYZ`). (This does NOT forbid intermediate per-sprint seeds named `vXYZ-devN.seed.md` — those are allowed; see `references/seed-template.md §File path` and `doctrines/seed-naming.md`.)
- A patch seed with > 10 sprints worth of scope — split the patch
- A separate plan file per dev sprint within one patch — wrong; the plan organizes them inside as phases/waves
- A dev sprint that promises operator-visible change in the seed but does not deliver it — that is seed/implementation drift (a `@critic` RECONSIDER and an `@auditor completeness` C+ cap), NOT a sprint reclassification. Do not "reshape as a `@worker` dispatch" after the fact to avoid grade exposure.
- Treating dev branches as mandatory — they are optional cushion, especially in meta or doc-only sprints
- Conflating shepherd's "patch" (umbrella) with standard-practice "patch" (small fix) — the latter is what shepherd calls a dev sprint

## See also

- `doctrines/sprint-as-patch.md` — every dev sprint is patch-grade scope (this doctrine extends it upward)
- `doctrines/seed-naming.md` — slug rules
- `doctrines/seed-anchored-by-issues.md` — how seed lanes anchor to GH issues
- `planter.md` — seed authorship behavior (operates at patch scope per this doctrine)
- `agents/engineer.md` — plan authorship behavior (operates at patch scope, with phase decomposition for multi-sprint patches)
- `references/branching-model.md` — git branch topology
