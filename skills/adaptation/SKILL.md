---
name: adaptation
description: "Self-improvement loop every flock agent runs: harvest-store-inject-cite, the INSIGHTS taxonomy, and the excellence bar. Use before any plan, seed, dispatch, or audit."
---

# Adaptation — the self-improvement loop every flock agent runs

The flock MUST NOT relearn the same failure twice; "barely passes" is a halt code. Canonical home of the harvest→store→inject→cite loop, the `## INSIGHTS` taxonomy, and the excellence bar every dispatch reads first.

## Loop contract

Registry = the project DB (`${SHEPHERD_WORKDIR}/root.db`, default `.shepherd/root.db`, `.artifacts/root.db` legacy) — canonical per `skills/context/SKILL.md`. NEVER hand-edit; NEVER reintroduce a markdown registry file.

**Three tables, one view** (`shctx adapt report [--md|--json]`):

| Store | Written by | Holds |
|---|---|---|
| `sprint_metrics` | `adapt roll` @ CLOSE-FINALIZE | grade, size, lane/wave counts, LOC delta, wall_minutes, api_calls |
| `audit_findings` | `audit insert` (auditor) | per-finding concern/severity — the harvest source |
| `mem_entries(kind='prior')` | `adapt roll`, from HIGH/CRITICAL findings | one deduped lesson per concern |

**Harvest (close).** Conductor (solo) / root shepherd (spawn) MUST run exactly one `roll` per close, after CLOSE-SWARM and before PAUSE:

```
shctx adapt roll --sprint=<branch> --grade=<G> [--size=XS|S|M|L|XL] [--lanes=N] [--waves=N] [--loc-add=N] [--loc-del=N] [--wall-min=R] [--api=N]
```

`roll` is atomic: (1) idempotent `INSERT OR REPLACE` of the metrics row; (2) per HIGH/CRITICAL `audit_findings` row, upsert one `mem_entries(kind='prior')` lesson titled `prior: <concern>`, deduped by title — one prior per recurring concern, never per occurrence (info/low/medium never promoted). Row: `title="prior: <concern>"`, `body="[<severity>] sprint <branch>: <gist>"`, `tags=[<concern>]`. A `roll` failure goes in the close report anomalies and MUST NOT block CLOSE-FINALIZE.

**Inject (open).** `shctx inject <role>` appends `adapt priors --lessons --md` + `--metrics --md` to `[DB-CONTEXT]` for **engineer** (Phase-0 mesh) and **planter** (seed time) ONLY. Empty store emits nothing (engineer: "no pattern history yet"; seed: "none (first cycle)"). A concern recurring across priors is systemic risk: engineer gives it a dedicated lane, planter a MUST-LAND CRITICAL lane earliest slot. `n≥1` sizes lanes/waves against `avg_lane_count`/`avg_sprint_minutes`; else static defaults. Spawn Check 8 reads the same metrics — `skills/shepherd/references/spawn-flags.md §--scope`.

**Cite (measure).** A plan or seed acting on a prior MUST cite its id — `prior:<mem_id>`, or `metrics(N sprints)` for sizing — in the rationale. This IS the measurement signal: no citation across several non-empty-store sprints means the read protocol is being skipped.

**Trend + decay.** Before PAUSE, `shctx adapt report --trends` — mechanized, never eyeballed — reads the last 3 sprints, emits an informational **TREND ALERT** on: a HIGH/CRITICAL concern recurring across all 3; grade trending strictly downward (A→B→C); cost rising ≥1.5× (newest vs oldest `wall_minutes`/`api_calls`); <3 closes emits nothing. `shctx adapt recommend` turns the same averages into a lane/t-shirt/watch-concern RECOMMENDATION. Every recurrence refreshes a prior's `updated_at`; unpinned and unseen across `SHCTX_ADAPT_DECAY_SPRINTS` closes (default **6**) prunes next `roll`. Pinned priors are NEVER pruned.

**Feedback classification.** Mid-sprint `feedback_*.md` memory MUST classify: project-specific → project memory; framework-generic → flagged in the close report as a doctrine-promotion candidate. Conductor NEVER pushes doctrine changes to the shepherd repo.

**Invariants:** bounded (dedup-by-title, HIGH/CRITICAL-only, decay-6), graceful-empty (empty store == cold start), idempotent (re-running a `roll` never duplicates the row or re-harvests a prior).

**Not:** an issue tracker (chronic items still get GH issues/labels, `skills/shepherd/references/pipeline.md §CLOSE`); auto-applied (surfaced, never silent-mutates a plan); a log (full record stays in `audit_findings`); an override of operator decisions.

## INSIGHTS

Any agent's report MAY append an OPTIONAL `## INSIGHTS` block — cross-lane discovery, separate from `[ACCEPTANCE]`. Never required; empty/absent is correct.

Exact shape `agent_insight_capture.sh` parses:

```
## INSIGHTS

- kind: relocation
  subject: crates/store/src/util.rs::normalize_id
  observation: Used by 3 lanes' upstream callers; belongs in crates/common.
  rationale: Reduces the dep cycle from store→web back to common→{store,web}.
```

**Taxonomy (canonical, exactly these six kinds):**

| kind | means | consuming actor |
|---|---|---|
| `relocation` | thing lives in the wrong module/crate | engineer adds a lane next sprint |
| `extension` | extend this thing while we're here | engineer scopes this-sprint or next |
| `duplication` | N copies of this pattern exist | engineer adds a consolidation lane; auditor evidence |
| `consolidation` | two things could merge / dead code present | auditor SUBTRACT input |
| `gap` | something the plan didn't anticipate | engineer: amendment, next-sprint lane, or accepted |
| `nit` | minor stylistic/naming observation | captured, actioned only if 3+ accumulate |

**Mechanization.** Hook `hooks/scripts/agent_insight_capture.sh` (`PostToolUse(Agent|Task)`) greps for the `## INSIGHTS` header, splits entries on `- kind:`, validates against the six kinds, writes `<ns>/insights/<sprint>/<id>.json`. `shctx insights list|show|export|clear` reads it back.

**Consumption — engineer Phase-0 mesh row 13:** `shctx insights export --sprint=<prev> --md`. `relocation`/`extension`/`consolidation`/`duplication`/`gap` → scope a lane, or record the decision not to; `nit` → record only unless 3+ accumulate; unactioned insights surface under "Cross-lane insights NOT scoped this sprint".

**Boundaries.** Read-only awareness, NEVER a mutation channel — an agent MUST NOT act on a sibling's insight mid-wave; does not replace `[DO-NOT-DUPLICATE]` greps; the engineer decides which insights become lanes. `[SIBLING-LANES]` brief mechanics live in `skills/shepherd/references/flock.md §Brief assembly` — this skill owns the report/registry half, not the dispatch-brief half.

## Excellence bar

**Greatness is the bar. Mediocrity is a halt code.** Every invocation answers one question: did this agent produce work the operator would defend as good? "Barely passes" is wrong.

Every flock agent's system prompt MUST open with this block verbatim, or its equivalent:

```
> Greatness is the bar. Mediocrity is a halt code.
> - READ before writing. REUSE before creating. Justify additions with documented invariants.
> - The lazy path through duplication is more work, not less — refuse it.
> - Honor language idioms; refuse "all code in one file."
> - Halt early rather than ship sub-standard work.
> - Conserve tokens — every line you write is a paid line. See skills/shepherd/references/flock.md §Brief assembly + skills/context/SKILL.md §Cache telemetry.
> See skills/adaptation/SKILL.md §Excellence bar.
```

A missing block in an agent file is a process violation the code-quality auditor greps for at close.

**Seven rules:**

1. **Read before writing, reuse before creating.** DEDUP-GATE greps run pre-dispatch and again at the coder's Step 3; `hooks/scripts/dedup_write_guard.sh` BLOCKS Write/Edit on a hit. Response is REUSE, EXTEND, or JUSTIFY — never silent proceed. Cite `prior:<mem_id>` (§Loop contract) when a harvested lesson shapes a plan, seed, or lane.
2. **The lazy path is more work, not less.** A duplicated symbol costs seconds; reconciling it costs an order of magnitude more. When `[FILE-SCOPE]` misses a needed file: **BRIEF-AMENDMENT REQUEST** (brief is wrong, conductor re-dispatches), a close-time finding for an out-of-scope dependency (never pause — retired), or halt with **SCOPE OVERFLOW**. NEVER silently expand scope, add a TODO, or duplicate.
3. **Honor language idioms.** Rust `impl_*.rs`/`pub(crate)`; Python re-export discipline, 300+ LOC god-files smell; TypeScript barrel exports; Go package-per-concept + `internal/`; Shell one function per concern, `_lib.sh` helpers. Load `code-style:<language>` plus the language-mastery skill at dispatch; project doctrine wins on conflict.
4. **Justify additions.** New wrapper/dep/abstraction lands on the subtract-don't-add budget (`skills/shepherd/SKILL.md §Principles`): wrapper → cite the invariant (`skills/shepherd/references/flock.md §@auditor`); dep → GH issue plus conductor approval; abstraction → ≥3 concrete use cases. Cannot justify in one sentence → does not belong.
5. **Halt rather than ship sub-standard work.** Work below the patch-grade bar (`skills/shepherd/SKILL.md §Sprint contract`) halts for amendment — halt codes are first-class.
6. **Conserve tokens.** One line per fact; cite, don't restate; acceptance as runnable greps, not prose. The bigger lever is delegation: push bulk work to bounded subagents (`@discovery`/`@worker`, `@coder`, `@auditor`/`@critic`) and compile gate-free fan-out to a Dynamic Workflow (`skills/harness/references/workflow-templates.md`).
7. **Deterministic work is code, not a model reply.** If the same question asked twice gives, by definition, the same correct answer — arithmetic, date math, file lookups, CSV/JSON, regex, hashing, counts, ETA — write the script once. Full treatment: `skills/shepherd/references/operating-philosophy.md`. Sibling: prose is not an acceptance predicate (`skills/shepherd/references/pipeline.md §Gates`).

**Per-agent application:**

| Agent | Application |
|---|---|
| `@engineer` | Patch-grade plan; bullet mesh recap; acceptance sized from `adapt priors --metrics` |
| `@critic` | Verdict first (GREEN/YELLOW/RED), one sentence per concern; bounces unrunnable acceptance |
| `@coder` | Canonical-types + dedup grep mandatory; `JUSTIFY-NEW` on overlap; report = work + grep output |
| `@auditor` | Hypothesis-driven; LOW-confidence → `## Open questions`, NEVER a finding; re-runs the predicate verbatim |
| `@worker` | Bounded deliverable and budget; scripts the metric |
| `@discovery` | Synthesis not summary; one cited claim per line |

**Anti-patterns:** silent scope expansion (grade-caps C+); a HIGH finding with no falsification; an 800-line god module; a duplicate past DEDUP-GATE; `JUSTIFY-NEW` absent where dedup would hit; the preamble missing from an agent file.

**Not:** "always write more code" (subtract-don't-add rules); "refuse all duplication mechanically" (Rule-2 exits exist); perfectionism (patch-grade, operator-defensible, not academic exhaustiveness).
