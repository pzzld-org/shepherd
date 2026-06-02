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

A flock brief is a **user message** in the dispatched subagent's request. What the
platform actually caches is the **request prefix** — tools → system prompt →
message history — gated by `cache_control` breakpoints (Anthropic prompt caching;
`https://code.claude.com/docs/en/prompt-caching`). Two corollaries the brief author
must internalize (corrected v6.0.5 after a live-docs audit):

1. **The genuinely-cached prefix for a `subagent_type: shepherd:<role>` dispatch is
   the agent system prompt (`agents/<role>.md`) + tools** — injected identically by
   the registry on every dispatch of that role — **not** the brief's internal
   section ordering. Keeping `agents/<role>.md` stable is the load-bearing cache
   win; the dispatch path (`Agent`/`Task`) exposes no `cache_control` knob to the
   brief author, so shepherd cannot set a mid-brief breakpoint.
2. **Ordering the brief still matters, for two real reasons:** (a) *coherence* (the
   dominant benefit — see below), and (b) keeping the leading stable portion of the
   user message **byte-identical** across dispatches so the runtime's
   conversation-prefix cache is reused rather than busted. Hence: **stable framing
   first, variable content last.**

> The earlier framing — "the runtime places implicit cache breakpoints at content
> transitions *inside* the brief" — was inaccurate and is retired (v6.0.5). Caching
> keys on the request prefix + explicit breakpoints, not on transitions the runtime
> auto-detects mid-user-message.

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

The block above (header through the comment line) is the stable leading portion of
the user message — keep it byte-identical across dispatches so the conversation
prefix stays reusable; the variable tail is what changes per lane.

> **Keep the stable block thin (v6.0.5).** `[ROLE]`/`[SKILLS]`/`[PROTOCOL-REMINDERS]`
> deliberately *point at* `agents/<role>.md` rather than restate it — that agent body
> is the genuinely-cached system prefix, so re-emitting its content in the brief only
> adds tail tokens. Emit the minimum needed for coherence + a stable prefix; let the
> agent body carry the framing.

## Why ordering matters

**Coherence is the primary, always-real benefit.** When every dispatch of a role
sees the same `[ROLE]` + `[SKILLS]` + `[PROTOCOL-REMINDERS]` prefix, the model's
behavior on those sections is stable across the sprint — the same skills load, the
same halt codes apply, the same prohibitions hold. When the prefix shuffles, the
model re-reads framing it has already absorbed, burns context on re-orientation, and
produces subtly different behavior dispatch to dispatch. Cache-first ordering
eliminates that variable regardless of what the cache does.

**The token/dollar benefit is real but rides on the request prefix, not the brief's
internals.** The reused prefix is the agent system prompt (`agents/<role>.md`) +
tools at the cache-read rate (≈10% of input); keeping that body stable, and the
brief's leading stable block byte-identical, is what earns that rate across a sprint
of 15–30 dispatches (and dominates an autorun of 200+). The single biggest dollar
lever, though, is **TTL**: a multi-wave run outlives the default **5-minute** cache,
so set **`ENABLE_PROMPT_CACHING_1H=1`** for `--scope >= patch` / long autoruns to
hold the prefix for an hour (Claude subscriptions request 1h automatically). See
`docs/configuration.md §[spawn]` + `doctrines/cache-telemetry.md`.

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
