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

## Brief assembly checklist (7 steps, every dispatch)

A mechanical recipe — follow it line by line and the cache invariant holds
without thinking. Re-derive nothing; copy verbatim from prior dispatches in
the same sprint wherever possible.

1. Emit `[ROLE]` — copy verbatim from `agents/<role>.md` frontmatter. Same text every dispatch in the session.
2. Emit `[SKILLS]` — deterministic per role (computed from `[skills.detection]` against `[FILE-SCOPE]` is downstream; the role-default list is the cacheable header).
3. Emit `[DOCTRINES]` — sprint-stable list (project + framework). Recompute only on sprint open, then reuse.
4. Emit `[PROTOCOL-REMINDERS]` — role-stable halt codes and hard prohibitions. NEVER customize per dispatch.
5. Emit the variable block in fixed order: `[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` (and `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]` for coders).
6. Verify byte-identity of steps 1–4 against the most recent dispatch of the same role in this sprint (visual diff or `diff <(sed -n '/\[ROLE\]/,/\[FILE-SCOPE\]/p' brief-old) <(...) `).
7. Dispatch. Telemetry (`doctrines/cache-telemetry.md`) measures whether the cache actually hit.

**Cache-stable header — copy-paste verbatim for every coder dispatch in a sprint.** Only the trailing variable block changes per lane. This is the byte-identical prefix the runtime caches:

```text
[ROLE]
@coder — implementation lane. Sonnet. Parallel-safe. Owns a single non-overlapping
[FILE-SCOPE]. Read agents/coder.md for the binding system prompt.

[SKILLS]
- code-style (mandatory per shepherd.toml [skills.mandatory])
- code-style:<lang> (auto-attached per [FILE-SCOPE] languages)
- language-mastery skill(s) per [FILE-SCOPE]
- superpowers:test-driven-development
- superpowers:verification-before-completion

[DOCTRINES]
- doctrines/zero-duplicate-tolerance.md (DEDUP-GATE; coder Step 3 re-runs greps)
- doctrines/wrapper-must-earn.md (JUSTIFY-NEW for wrapper types)
- doctrines/subtract-dont-add.md (every addition pays for itself)
- doctrines/agent-excellence.md (greatness is the bar)
- doctrines/worktree-confinement.md (writes confined to the assigned worktree)
- doctrines/coder-brief-format-shared-artifacts.md (shared ctx files need partition rule)

[PROTOCOL-REMINDERS]
- Greatness is the bar. Mediocrity is a halt code.
- READ before writing. REUSE before creating.
- Step 2 (read canonical-types) is mandatory. Step 3 (dedup grep) is mandatory.
- Halt codes are first-class: BRIEF-AMENDMENT, SCOPE OVERFLOW, BASE-DRIFT, WORKTREE-DRIFT. Express cross-lane dependencies as graph-edge await ordering (engineer-composed); for genuine cross-teammate hand-off use Agent Teams `SendMessage`; out-of-sprint work → file a finding at close. (PAUSE-FOR-DEPENDENCY retired v6.0.1 #70, per `doctrines/native-coordination.md`.)
- Writes confined to the assigned worktree. Do NOT cd; use git -C <path>.
- Conserve tokens — every line you write into the report is a paid line.

# --- variable block follows ---

[FILE-SCOPE]
...
```

The block above (header through the comment line) is the cacheable prefix.
A coder dispatched twice in the same sprint sees this exact text twice; the
runtime caches it once, replays the cache breakpoint on the second dispatch,
and only pays full input rate on the variable tail.

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

- `doctrines/cache-telemetry.md` — how we measure whether this is working (per-role hit-rate ranges, alarm thresholds)
- `doctrines/agent-excellence.md` — Rule 6 "Conserve tokens" cites this doctrine as the structural complement to per-brief trimming
- `skills/shepherd/SKILL.md §Token + cache discipline` — operator-facing surface of this doctrine
- `doctrines/hook-event-log.md` — the event log that captures dispatch metadata
- `pipeline.md` §V — the canonical dispatch shape (citation point)
- `references/agent-briefs.md` — existing brief templates conform to this ordering
- `agents/auditor.md` — completeness concern verifies ordering post-hoc
