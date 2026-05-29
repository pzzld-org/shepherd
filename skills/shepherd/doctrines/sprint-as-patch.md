# Sprint-as-patch — every `dev.N` is an entire patch, not a small step

> **Origin:** operator clarification 2026-05-15. Verbatim:
> "Every 'sprint' within the plugin is equivalent to something you might
> typically consider an entire patch. But to me, these dev.* sprints *are*
> the patches giving us ample opportunity to push our protocol forward
> consistently."

## What this means

The default mental model of "sprint" in most software contexts is **a thin
slice of work** — one focused increment, days of effort, narrow scope. That
is NOT what `dev.N` means in this shepherd-driven workflow.

In this workflow, a `dev.N` sprint IS what an outside observer would call a
**full patch**: a coherent, substantive protocol advance with multiple
parallel coder lanes, real feature shipping, deletion + addition, release-
notes-eligible content, and meaningful operator value at close.

The version-level `v{X}.{Y}.{Z}` branch is the **bundling of N patch-grade
sprints** into a release. It's not "the patch" with sprints as fragments;
it's the **collection** of patches into a versioned release.

## Implications

### For the planter (`/shepherd:plant`)

Seed authorship targets PATCH-GRADE scope per sprint:

- **Theme size:** what an outside observer would call a "patch theme" — not a
  single ticket, not a one-file-fix. Examples: "Realtime data-plane hardening",
  "Bot lifecycle observability", "Schema consolidation across all tracking
  tables".
- **Decomposition target:** patch-grade depth = each wave decomposed into many
  narrow **steps** (to the substantive LOC floor) and, under `/shepherd:spawn`, a
  substantial **total** lane count (the post-plan projection — never "per wave";
  `doctrines/primitive-axis-binding.md`). A thin sprint (one wave, a couple of
  broad steps) = under-scoped, reject back. The planter recommends; the engineer
  decomposes.
- **Deliverable density:** every sprint MUST ship operator-visible improvement;
  every sprint MUST have a SUBTRACT delta (deletion at parity with addition);
  every sprint MUST have at least one user-perceivable feature OR a structural
  improvement that unblocks downstream value.
- **Release-notes alignment:** at sprint close, the close-handoff should be
  release-notes-eligible content (operator may bundle multiple sprints into
  one release, but each sprint's close-handoff stands alone as release-notes
  material).
- **Patch-arc relationship:** the `{patch_slug}.seed.md` is the bundling
  spec — what `dev.0..dev.{last}` collectively deliver toward the version's
  thesis. NOT a master plan from which sprints are derived. Each
  `{sprint_slug}.seed.md` is a patch-grade standalone seed informed by the
  patch-arc seed.

### For the engineer (`@engineer`)

Plan authorship targets PATCH-GRADE scope per sprint:

- **Body depth:** N waves is non-trivial; the §2 BODY is where the actual
  patch ships. Decompose each wave into many narrow coder **steps**; multiple
  waves for L+ sprints (substantive LOC floor per `agents/engineer.md §Step
  decomposition discipline`). Lanes are a post-plan spawn projection, not a
  plan-body concept.
- **Real-work justification per phase:** plan body MUST cite each phase's
  operator-visible outcome — "Lane A delivers X" not "Lane A refactors Y".
  Structural-only phases need an outsized justification (unblocks N
  downstream).
- **Phase 0 mesh awareness:** mesh enumerates ALL open work, not just
  current-milestone — the engineer is responsible for absorbing
  patch-grade scope, including issues that may have been "deferred for
  later" in a smaller-sprint mental model.
- **Carry-forward discipline:** any item carried forward without action for
  3+ sprints (patch-equivalent: 3+ months in conventional cadence) gets
  `chronic` label per `carry-forward-refresh.md`. The
  `[ledger].chronic_threshold_patches` config remains the threshold count,
  but its mental model is "patches" = "sprints" in shepherd.

### For the conductor

Sprint-open expectations:

- **Body-depth heuristic** in SKILL.md §III is now BINDING, not aspirational:
  decompose each wave to the T-shirt substantive LOC floor (many narrow steps);
  spawn-mode **total** lane minimums per `agents/engineer.md §Lane projection`.
- **PAUSE between sprints is meaningful** — each sprint close is a
  patch-equivalent waypoint where the operator may want to:
  - Release-tag intermediate progress
  - Re-prioritize the patch arc
  - Inject mid-arc operator amendments
  - Cut the patch early if the next sprint's value isn't clear
- **Sprint-through grants** to skip the PAUSE between sprints are NOT the
  default — they're operator-explicit for cases where the next sprint is
  obviously next.

### For the auditor

Close-time grading expectations:

- **Real-work test is binding** — a sprint that fails real-work caps at C+.
  If the seed promised feature X and X didn't ship (or shipped non-functional),
  that's a failed sprint, not a passable increment.
- **SUBTRACT-DON'T-ADD discipline scales with sprint** — a patch-grade sprint
  that adds 2000 LOC and deletes 50 LOC is suspect; the framework's SUBTRACT
  doctrine expects parity-or-better deletion.
- **Grade rubric anchors to patch-grade output, not sprint-grade input:**
  - **A** is patch-grade theme delivered + SUBTRACT win + zero CRITICAL/HIGH
  - **B** is patch-grade theme delivered with manageable findings + SUBTRACT met
  - **C+** is theme partially delivered OR SUBTRACT violation OR ledger silence
  - **D / F** is theme not delivered, regression introduced

### For the critic

Plan-gate expectations:

- **Under-scoped seed → RECONSIDER.** If the seed reads like "fix this one
  bug" or "add this one feature", critic verdict is RECONSIDER — escalate
  to engineer to expand the theme to patch-grade.
- **Under-scoped plan → RECONSIDER.** A body under-decomposed below the
  T-shirt's substantive step-depth (or, under spawn, an under-parallelized lane
  projection), or a body that doesn't ship operator-visible value, reject.

## What does NOT change

- The branch topology (`v{X}.{Y}.{Z}-dev.N`) stays the same.
- The 3-section pipeline (INTRO → BODY → CLOSE) stays the same.
- The flock identity stays the same (6 agents now in v5.1.1).
- The release driver (`[release].driver`) still fires at `dev.{last}` close.
- The patch-branch lifecycle (rebase-merge dev into patch; squash-merge patch
  into main) stays the same.

What changes is the **mental scope** every actor brings to a sprint: not
"I'm doing one increment of this patch" but "I'm doing one PATCH of this
version arc".

## Anti-patterns this doctrine catches

1. **Seed too narrow.** Planter emits a seed with one bullet of work, single
   crate scope, expected duration 1 hour. Critic rejects to "expand to
   patch-grade theme; reference v0.X.Y previous patch as scope anchor".
2. **Plan too narrow.** Engineer emits a plan with 2 lanes touching 4 files.
   Critic verdict RECONSIDER: not patch-grade.
3. **Auditor grading on sprint-input cadence.** Auditor grades B+ for "made
   reasonable incremental progress on the patch". Per this doctrine, that
   grades C+ — the sprint promised a patch, the patch didn't ship.
4. **Conductor sprint-throughs by default.** Conductor auto-skips PAUSE
   because "the next sprint is obvious". Per this doctrine, PAUSE is the
   patch-checkpoint; default to it.
5. **"This is just a small follow-up sprint."** No such thing in this
   workflow. Either it's patch-grade or it's not a sprint, it's a hotfix
   subgraph.

## See also

- `skills/shepherd/SKILL.md` §III Sprint impactfulness contract (now binding)
- `skills/shepherd/planter.md` — seed sizing guidance
- `skills/shepherd/references/seed-template.md` — scope cues for patch-grade seeds
- `agents/engineer.md` — plan-quality bar at patch-grade
- `doctrines/subtract-dont-add.md` — SUBTRACT discipline applies per patch-grade sprint
- `doctrines/issue-ledger-awareness.md` — patch-grade Phase 0 includes ALL open ledger items
