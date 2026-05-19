# Brief cache discipline — stable framing first, variable content last

> **Origin:** v5.1.3 (2026-05-19). Operator: "every agent within the flock
> needs to leverage prompt caching to prevent the degradation of outputs."

A flock dispatch is paid for twice: once in tokens at the model boundary, and
once in coherence — long, reshuffled prompts produce drifty, lower-fidelity
work. Both costs are reducible to the same discipline: **stable framing
first, variable content last**. This doctrine codifies the ordering every
brief MUST follow so the runtime's implicit prompt cache actually reuses the
prefix across dispatches.

## The principle

A flock brief is a user message. The conductor builds it inline. The Claude
Code runtime places implicit cache breakpoints at major content transitions;
everything BEFORE a breakpoint is eligible for reuse across dispatches in the
same conductor session. Therefore: **stable framing first, variable content
last**. The prefix is what gets cached. The variable tail is what changes.
Reordering one section between the two blocks invalidates the prefix and
the dispatch pays the system-prompt creation cost again.

## Stable framing block (top of every brief)

Deterministic order, recyclable across dispatches:

| Order | Section | Owns |
|---|---|---|
| 1 | `[ROLE]` | Identifies the flock role being dispatched |
| 2 | `[SKILLS]` | The skill load list — deterministic per role |
| 3 | `[DOCTRINES]` | Project + framework doctrines to load |
| 4 | `[PROTOCOL-REMINDERS]` | Short per-role reminders (halt codes, hard prohibitions) — reused verbatim |

These four blocks change rarely. The conductor's template macros (textual or
implicit) emit them verbatim across every dispatch in a sprint. A coder
dispatched twice in the same sprint should see byte-identical `[ROLE]` +
`[SKILLS]` + `[DOCTRINES]` + `[PROTOCOL-REMINDERS]` blocks — that identity is
what makes the prefix cacheable.

## Variable content block (bottom)

Dispatch-specific, deterministic order:

| Order | Section | Owns |
|---|---|---|
| 1 | `[FILE-SCOPE]` | Per-lane MAY-MODIFY / MUST-NOT-TOUCH paths |
| 2 | `[CONTEXT-INVENTORY]` | Cited symbols + paths the lane will touch |
| 3 | `[DO-NOT-DUPLICATE]` | Greps that must return expected count |
| 4 | `[ACCEPTANCE]` | Runnable verification |
| 5 | `[NON-GOALS]` | What this lane explicitly does not do |
| 6 | `[WORKTREE]` | Path + branch + commit template (coder dispatches only) |
| 7 | `[BASE-COMMIT-EXPECTED]` | SHA the worktree was branched from (coder dispatches only) |

## The rule

Every bracketed section in the stable block MUST appear before any bracketed
section in the variable block. Prose interleaving is fine — the rule
governs bracketed-section ordering, not freeform connective text. The
bracketed-section order itself, within each block, is non-negotiable.

## Why ordering matters

The Claude Code runtime places implicit cache breakpoints at major content
transitions in a long user message. When the stable framing block sits at
the top of every dispatch in a sprint, the runtime caches that prefix on
first emit and replays it on every subsequent dispatch — paying the
cache-read rate (≈10% of input) instead of the full input rate. Across a
sprint of 15–30 dispatches, that turns into a measurable spend reduction;
across an autorun of 200+ dispatches, it dominates the cost budget.

The consistency benefit is at least as important as the dollar benefit.
When every dispatch sees the same `[ROLE]` + `[SKILLS]` + `[PROTOCOL-REMINDERS]`
prefix, the model's behavior on those sections is stable across the sprint —
the same skills load, the same halt codes apply, the same prohibitions hold.
When the prefix shuffles, the model re-reads framing it has already absorbed,
burns context window on re-orientation, and produces subtly different
behavior dispatch to dispatch. The drift is hard to attribute and harder to
debug. Cache-first ordering eliminates the variable.

What breaks if you intersperse: any variable section emitted before any
stable section invalidates the prefix from that point forward. A brief that
emits `[FILE-SCOPE]` between `[ROLE]` and `[SKILLS]` produces a different
prefix on every dispatch (because `[FILE-SCOPE]` is per-lane) — the runtime
caches nothing useful, and the dispatch pays full cache-creation rate. The
v5.1.3 telemetry hooks (per `doctrines/cache-telemetry.md`) surface per-role
hit-rate, making this regression immediately visible.

## Enforcement

The completeness auditor at sprint close reads captured briefs from the
conductor's dispatch run-log and verifies ordering. LOW finding per
violation; aggregates to MEDIUM if > 30% of dispatches violate. This is
post-hoc verification, NOT a pre-dispatch gate — the rule is structural
discipline, encoded in the brief templates at `references/agent-briefs.md`
and reinforced by the conductor's brief-assembly habit. Pre-dispatch
gating would slow every dispatch with a parse step; post-hoc verification
catches drift while keeping the hot path fast.

## Anti-patterns

- Putting `[FILE-SCOPE]` before `[SKILLS]` (variable before stable — invalidates the prefix).
- Interleaving variable sections with stable ones (e.g., `[ROLE]` → `[FILE-SCOPE]` → `[SKILLS]`).
- Emitting `[ACCEPTANCE]` at the very top "for emphasis" — defeats caching for every downstream section.
- Customizing `[PROTOCOL-REMINDERS]` per dispatch (defeats reuse — protocol reminders are role-stable, not dispatch-specific; per-dispatch nuance belongs in `[CONTEXT-INVENTORY]` or `[ACCEPTANCE]`).
- Putting `[WORKTREE]` / `[BASE-COMMIT-EXPECTED]` at the top of a coder brief because they "feel like setup." They are dispatch-specific and belong in the variable tail.
- Adding new bracketed section names ad-hoc. The seven stable + seven variable above are the canonical list. Extensions go through doctrine revision.

## See also

- `doctrines/cache-telemetry.md` — how we measure whether this is working
- `doctrines/hook-event-log.md` — the event log that captures dispatch metadata
- `pipeline.md` §V — the canonical dispatch shape (citation point)
- `references/agent-briefs.md` — existing brief templates conform to this ordering
- `agents/auditor.md` — completeness concern verifies ordering post-hoc
