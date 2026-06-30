---
title: flock-output-review
status: binding
introduced: v6.2.4
description: |
  A conductor does NOT forward a wave's coder output to root (WAVE-COMPLETE) on a
  coder's own "self-gate green" claim. Before WAVE-COMPLETE it holds a PASS verdict
  from an adversarial @auditor in wave-review mode, run against a fixed four-item
  checklist; a REDO verdict forces the named author to redo the named scope through
  the hot-fix vehicle ladder. Root applies the same gate at LANE-INTEGRATE, delegates
  the verdict instead of hand-reading diffs, and never repairs a teammate's source
  itself. Behavioral wiring only — reuses the @auditor, the hot-fix ladder, Pattern B
  overlap, and the coder brief; no new command, CLI verb, or state table.
---

# Flock-output review — the conductor reviews its flock before it forwards, and forces redo on the author (#167)

The tier structure holds only if each tier owns the quality of its own output. A
conductor that forwards a coder's diff on the coder's own "self-gate green" claim
pushes the verify-and-force-redo burden UP to root. Root then re-reads every diff,
becomes the de-facto reviewer of every coder, and its sprint-long reasoning context
bloats — the exact failure the tiers exist to prevent. Conductors are ephemeral and
tunnel-visioned on their lane; that is precisely why the lane's output is reviewed
*inside* the lane, by a reviewer that is not the context that wrote it, before it
leaves the lane.

A compiling diff is not a correct diff. The field case (#167): a coder told to
surface silent task panics instead (1) reinvented a canonical helper under a new
name, (2) added a workspace-wide unstable build flag for one call site, and (3) did
not address panics at all. It compiled green; the conductor forwarded it as
WAVE-COMPLETE; root caught all three on review and forced a redo. A review gate
inside the lane catches all three before WAVE-COMPLETE — and the redo lands on the
coder, not on root.

## The gate (conductor tier)

Before emitting `WAVE-COMPLETE` for a wave, the conductor MUST hold a
`review_verdict: PASS` from an adversarial review of that wave's coder output. A
coder's self-gate-green claim is NOT the review.

- **Reviewer.** At least one `@auditor` dispatched in **wave-review mode**
  (`mode: wave-review`, `agents/auditor.md §Modes`). Read-only: it reads the diffs
  and returns a verdict, so the conductor keeps the *conclusion*, not the raw diffs.
  Delegating the read is what preserves a long-running conductor's context.
- **Timing — Pattern B, no serial tail.** The wave-review auditor for Wave N is
  dispatched concurrently with Wave N+1's coders, in the same batch
  (`doctrines/pattern-b-overlap.md`). This is the existing `WAVE-N-AUDIT` lane, now
  mandatory and checklist-bound rather than engineer-optional.
- **Checklist (applied to each coder diff in the wave):**
  1. **Intent** — does it satisfy the linked issue's stated INTENT, not merely
     compile and pass gates?
  2. **No fragile global** — was a global/unstable build flag or a workspace-wide
     feature introduced to serve a single local call site? (An env `RUSTFLAGS`
     overriding a `.cargo/config.toml` cfg, a workspace `feature` for one site:
     fragile across CI legs and build contexts.)
  3. **No reinvention** — does it re-create an existing canonical helper/type under
     a new name? Behavioral dedup per `doctrines/zero-duplicate-tolerance.md` —
     applied to what the code *does*, not only its symbol name.
  4. **No passes-local-breaks-CI** — any pattern green here but red in CI/deploy?
     (Env var overriding a config-file setting; feature-resolution divergence; a
     stale-incremental false green.)
- **Verdict.** `PASS` (no checklist hit — emit `WAVE-COMPLETE`) or `REDO` (one or
  more hits — each finding carries a `Suggested redo` block: the exact author, the
  exact scope, and the required change). The conductor pastes that block into the
  REDO brief verbatim; it does not re-derive the fix.

## The REDO loop (both tiers)

REDO forces the **specific named author** to redo the **specific named scope**. It is
the proactive sibling of HOTFIX: HOTFIX fires reactively on a gate/audit *finding*;
REDO fires on a review *verdict*. Both route through one vehicle.

- **Target — deterministic, never blanket.** The coder/cluster named in the verdict
  (conductor tier), or the teammate-conductor lane named in the verdict (root tier).
  One named author, one named scope. Re-running a whole wave for a one-author finding
  is a violation.
- **The REDO brief.** The author's original coder brief plus a `[REDO]` block:
  `[PRIOR-DISPATCH]` (author id + the verdict finding, verbatim) and
  `[REDO-CONSTRAINT]` (fix only the named items; identical `[FILE-SCOPE]`; no adjacent
  refactor). Reuses the coder brief template (`references/agent-briefs.md`); no new
  brief format.
- **Vehicle.** The hot-fix cardinality ladder (`doctrines/hotfix-dispatch.md`): `H=1`
  → one subagent; `H ∈ (1,5]` → one batched dynamic workflow; `H ≥ 6` → a dedicated
  lane. Vehicle ≠ concurrency — the ≤3-concurrent-coder cap still binds inside the
  chosen vehicle.
- **Termination.** ≤3 REDO iterations on the same scope. The third unresolved REDO
  raises `REDO-CAP-EXCEEDED` (→ `HARD-STOP`, surface to operator). Never loop a coder
  on the same scope forever.

## Root tier — delegate the verdict, never repair the source

Root lasts the whole sprint, so it keeps its reasoning context lean: it **delegates**
deep verification to an `@auditor` that returns a verdict, rather than hand-reading
every teammate diff. At `LANE-INTEGRATE` (`doctrines/teammate-integration-authority.md`)
an `@auditor` diff-review returns the verdict; root keeps the conclusion, not the
diffs, and inline-reviews only a small diff (< 200 lines changed, the threshold in
`teammate-integration-authority.md`). A teammate lane whose verdict is `REDO` gets a
`REDO-DIRECTIVE` via `SendMessage` to the **owning teammate-conductor** — the existing
"route the fix through the owning teammate, never a direct root fix" path
(`GATES-BROKEN`, `agents/shepherd.md §Escalation triage`). Root never edits a teammate's
source (root prohibition #2); it forces the lane to redo and re-surface a fresh
`WAVE-COMPLETE`.

## Mechanical teeth

- The `WAVE-COMPLETE` payload carries a required `review_verdict: PASS` +
  `reviewer: <agent-id>`. A teammate `WAVE-COMPLETE` missing it is a
  `DISPATCH-CONTRACT-VIOLATION` — root refuses the wave (the "missing wave-gate
  evidence" clause, `agents/shepherd.md §Halt codes`).
- SOLO mode (no root to refuse the wave): the close `completeness` auditor verifies
  every wave recorded a `review_verdict: PASS`; a wave forwarded without one is a
  completeness finding that caps the grade (`agents/auditor.md §completeness`).
- Coverage row: `doctrines/invariant-enforcement-matrix.md §V-bis`.

## Anti-patterns

- Forwarding `WAVE-COMPLETE` on a coder's self-gate-green claim with no `wave-review`
  verdict.
- Blanket-re-running a whole wave when the verdict named one author and one scope.
- Root hand-reading every teammate diff instead of delegating the verdict to an
  `@auditor` — context bloat, the exact failure root exists to avoid.
- Root fixing a teammate's source itself instead of issuing a `REDO-DIRECTIVE` to the
  owning teammate.
- Looping a coder on the same REDO past 3 iterations instead of raising
  `REDO-CAP-EXCEEDED`.

## See also

- `doctrines/hotfix-dispatch.md` — the vehicle ladder REDO reuses.
- `doctrines/pattern-b-overlap.md` — why wave-review overlaps the next wave.
- `doctrines/auditor-hypothesis-driven.md` — the wave-review auditor's finding discipline.
- `doctrines/teammate-integration-authority.md` — LANE-INTEGRATE, where root runs the same gate.
- `doctrines/zero-duplicate-tolerance.md` — the reinvention check (behavioral dedup).
- `agents/auditor.md §Modes` — the `wave-review` mode and its verdict shape.
