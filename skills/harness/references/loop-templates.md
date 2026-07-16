---
description: Ready-to-use per-role loop templates specializing FOCUS-LOOP / CONVERGENCE-LOOP / WATCH-LOOP. Use when dispatching, auditing, or authoring any `/shepherd:loop` invocation.
---

# Loop Template Catalog

Nine loop templates, one per flock role plus the orchestrator, each specializing
CONVERGENCE-LOOP or WATCH-LOOP (`skills/harness/references/workflow-templates.md`), generic
Loop-Until-Done, or FOCUS-LOOP (named there; owned by `skills/motivation/SKILL.md
§FOCUS-HEARTBEAT`). NEVER re-derive a composite from scratch — reference it by name and
parameterize.

Pattern-6 circuit-breaker invariants, owned by `skills/motivation/SKILL.md §Loop discipline`,
bind every template: `max_iterations` MUST be set before the first iteration (missing =
`PLAN-MISSING-LOOP-CAP`); every iterator MUST emit structured `new_findings: true|false`
(unstructured prose = `LOOP-REPORT-INVALID`); cap-exceeded MUST halt as `LOOP-CAP`, NEVER a
silent exit.

## Skeleton (stated once — do not repeat per template)

Every template below follows this 8-part shape; only the ~15% that differs (agent,
gate/predicate, default `--max`, anti-patterns) appears in its entry:

1. **Intent** — one-line purpose.
2. **Composite** — named composite (or generic Pattern 6) specialized.
3. **Flock agent binding** — iterator, checker, terminator roles.
4. **Loop body** — Probe → Act → Branch.
5. **Termination predicate** — exact condition for `new_findings: false`.
6. **Stage Graph shape** — `<NAME>-INIT` → iterator node(s) → `<NAME>-LOOP-DONE`; every
   `on-cap ($i >= max)` edge is a `LOOP-CAP` halt, NEVER a silent terminal state.
7. **Default `--max`** — a numeral + escalation thresholds.
8. **Anti-patterns** — top violations for this role.

`new_findings` (lowercase field, values `true|false`) MUST be emitted by every iterator on
every tick — the universal termination-signal contract, test-enforced by
`skills/context/tests/test_loop_lifecycle.sh` and `test_dash.sh`. Unstructured prose in its
place is a framework violation.

## Quick-selection table

| Role | Template name | Composite | Default `--max` | Terminates on |
|------|--------------|-----------|-----------------|---------------|
| `@coder` | CODER-CONVERGENCE | CONVERGENCE-LOOP | 5 | Gate green (`new_findings: false`) |
| `@discovery` | DISCOVERY-EXHAUST | Loop-Until-Done | 4 | `new_findings: false` |
| `@worker` (state-reconcile) | WORKER-CONVERGENCE | CONVERGENCE-LOOP | 5 | State predicate met |
| `@worker` (monitoring) | WORKER-WATCH | WATCH-LOOP | 20 | Anomaly OR cap |
| `@worker` (outcome soak) | SOAK-LOOP | WATCH-LOOP | 6 | Predicate regressed OR all hold at cap |
| `@worker` PROBE + `@coder` ACT | AUTONOMOUS-SENTINEL | WATCH-LOOP (SOAK-LOOP superset) | 6 | K clean ticks OR hf_cap OR hard-stop |
| `@auditor` | AUDITOR-REFINE | Loop-Until-Done | 3 | Confidence plateau (`new_findings: false`) |
| `@engineer` | ENGINEER-PLAN-REFINE | Loop-Until-Done | 3 | Critic gate green |
| shepherd / conductor | FOCUS-LOOP | FOCUS-LOOP | 8 | CLOSE-FINALIZE reached |

## Pacing — orthogonal to the template

Every wall-clock template delegates its wake clock to native `/loop`; the template picks
*what* runs, pacing picks *when*:

- **self-paced** (`--self-paced`) — ends early on `new_findings: false`. Convergent templates
  only (DISCOVERY-EXHAUST canonically, plus CODER-CONVERGENCE/WORKER-CONVERGENCE/
  AUDITOR-REFINE/ENGINEER-PLAN-REFINE).
- **fixed interval** (`--interval <dur>`) — MANDATORY for watch templates (WORKER-WATCH,
  SOAK-LOOP, AUTONOMOUS-SENTINEL), which terminate on `true` — end-early-on-`false` would be
  wrong.
- **in-session** (neither flag) — shepherd drives `wake → act → probe → yield` directly.

Native invocation: `shctx loop native-cmd --id=<loop-id>` — NEVER hand-reconstructed
(`commands/loop.md §Pacing modes`).

## CODER-CONVERGENCE

Drive `@coder` to gate-green: tests pass, lint clean, greps satisfied. Specializes
CONVERGENCE-LOOP (`workflow-templates.md §CONVERGENCE-LOOP`).

- **Gate expression** MUST be declared in the seed BEFORE dispatch — a post-hoc gate is
  CIRCULAR-RUBRIC.
- **Default `--max`: 5.** >5 requires engineer justification; >10 requires critic sign-off.
- **Anti-patterns**: scope expansion beyond the current `gate_failures` list; using this for a
  finite fix list (use Fanout-And-Synthesize instead); nesting inside a FOCUS-LOOP Act phase
  without a distinct `loop_id`.

## DISCOVERY-EXHAUST

Drive `@discovery` through successive read-only sweeps until no new sources, angles, or
findings remain. Specializes generic Loop-Until-Done — no gate, no cadence. `@discovery` is
read-only throughout (`skills/shepherd/references/flock.md §@discovery`).

- **Termination**: `new_findings: false` only after actively checking for remaining unexplored
  avenues and finding none — NEVER merely because time or tokens ran out.
- **Default `--max`: 4.** >4 requires justification; >10 requires critic sign-off.
- **Anti-patterns**: a wide/ambiguous question instead of a tight one; writing outside
  `{paths.reports}`; re-reading sources already in `[DISCOVERY-CONTEXT]`; skipping
  `shctx discovery search --question="<paraphrase>"` first — a fresh discovery (< 2 sprints
  old) covering the question is reusable, no loop needed; using this for ongoing monitoring
  (that's WORKER-WATCH).

## WORKER-CONVERGENCE (state-reconciliation)

Drive `@worker` to a defined state target (config drift, migration, registry reconciliation).
Specializes CONVERGENCE-LOOP; identical shape to CODER-CONVERGENCE with a state predicate
instead of a gate expression.

- **Predicate** MUST be deterministically evaluable, side-effect-free, and declared in the
  seed BEFORE dispatch — one assembled after observing failures is CIRCULAR-RUBRIC.
- **Default `--max`: 5** — same cap and justification thresholds as CODER-CONVERGENCE.
- **Idempotency**: every operation MUST be repeat-safe; non-idempotent side effects require a
  dedup check (`skills/shepherd/references/pipeline.md §DEDUP-GATE`).
- **Anti-patterns**: non-idempotent operations that diverge instead of converge; a prose
  predicate ("things look clean") — unverifiable, LOOP-REPORT-INVALID; `@worker` dispatching
  sub-agents (workers are leaf dispatches).

## WORKER-WATCH (monitoring)

Bounded, wall-clock-scheduled monitoring: a deploy, error stream, CI status, or health
endpoint. Specializes WATCH-LOOP (`workflow-templates.md §WATCH-LOOP`). Probe is
read-only/alert-only — NEVER remediates.

- **`--interval` is MANDATORY** — without it this is WORKER-CONVERGENCE.
- **`anomaly_criteria`** MUST be declared in the seed before the loop starts (e.g. a health
  endpoint's non-200/latency bound).
- **Default `--max`: 20.** The native `/loop` 7-day auto-expiry is the outer hard bound.
- **Anti-patterns**: probe dispatching remediation — violates the WATCH-LOOP leaf-composite
  constraint and depth-3 limit, `COMPOSITION-TOO-DEEP`
  (`skills/shepherd/references/pipeline.md §Dispatch patterns`); `@discovery` as probe
  iterator — NEVER valid, use `@worker`; monitoring beyond 7 days in one loop.

## SOAK-LOOP (post-delivery outcome re-verification)

Re-runs a closed sprint's seeded acceptance predicates (seed §6) against live state on a
post-close interval (e.g. T+1d, T+7d) — detection-only, re-pointing WATCH-LOOP's anomaly
target to the sprint's own promises. Full seam-4 contract: `skills/motivation/SKILL.md §SOAK`.

- **Predicates** are carried from the closed seed's §6 — NEVER invented in the loop.
- **Default `--max`: 6** (e.g. T+1d/T+7d checkpoints); 7-day native `/loop` expiry is the outer
  bound.
- **Regression** surfaces `OUTCOME-REGRESSION` (`skills/shepherd/references/pipeline.md §Gates`)
  and terminates the loop.
- **Anti-patterns**: soaking undeclared outcomes; remediating inside the probe UNLESS the
  seed authorizes AUTONOMOUS-SENTINEL; substituting soak for the close gate (close verifies
  FIRST); `@discovery`/teammate-conductor as probe iterator.

## AUTONOMOUS-SENTINEL (authorized supervised self-heal)

SOAK-LOOP's supervised-remediation superset: `@worker` PROBE plus a `@coder` ACT stage per
REGRESSED predicate via the hotfix-dispatch ladder
(`skills/shepherd/references/pipeline.md §Hotfix ladder`). NEVER fires by default — requires
ALL THREE: config `[close].autonomous_sentinel == "on"` (default `"off"`), seed declaration
`close: autonomous-sentinel`, AND a complete `sentinel_rails` block. Rails, `SENTINEL-*`
codes, ALL-THREE detail: `skills/motivation/SKILL.md §Sentinel` (canonical).

- **Default `--max`: 6**, `clean_ticks_to_converge` (K) = **2**, `hf_cap` = **3**.
- **Anti-patterns**: `@discovery` as PROBE iterator — NEVER valid (same rule as
  WORKER-WATCH/SOAK-LOOP); remediating a NEW failure — only REGRESSED enters ACT scope; a
  bespoke remediation path instead of the hotfix-dispatch ladder; widening scope past ≤S.

## AUDITOR-REFINE

Progressive audit deepening across hypothesis-generation sweeps. **Rare** — auditors normally
run as a Pattern-3 swarm (`skills/shepherd/references/flock.md §@auditor`); use only for
inherently sequential audit questions (causal-chain tracing, data-flow).

| Situation | Use |
|---|---|
| Independent concerns | Pattern-3 swarm |
| Single auditor, XS scope | Direct dispatch |
| Sequential hypothesis refinement | AUDITOR-REFINE |
| Re-audit after hotfix | Direct dispatch, or CODER-CONVERGENCE if still open |

- **Termination**: `new_findings: false` at confidence plateau — no hypothesis this sweep
  survived falsification. LOW-confidence findings belong in `## Open questions`, NEVER in the
  set justifying another iteration.
- **Default `--max`: 3.** >3 requires justification; >10 requires critic sign-off.
- **Anti-patterns**: using this loop when concerns decompose independently (use a swarm);
  filing LOW-confidence findings to inflate iteration count; skipping prior-findings
  carry-forward context; grading in intro/carry-forward mode (auditors grade in close mode only).

## ENGINEER-PLAN-REFINE

Iterative plan refinement when `@critic` returns REJECT-STRUCTURAL and single-pass
`PLAN-AMEND` is insufficient. **Root-tier-exclusive** (`skills/shepherd/SKILL.md §Dispatch
law`) — teammate-conductors MUST NOT use it; surface `PLAN-AUTHORSHIP-REQUEST` /
`PLAN-GATE-REQUEST` (`skills/shepherd/references/escalation.md §Halt-code index`).

- **Termination**: `new_findings: false` when `@critic` returns PASS on the amended plan
  (WARN-level items may remain).
- **Default `--max`: 3.** >3 requires explicit operator acknowledgement BEFORE the loop
  starts — not critic sign-off, unlike every other template.
- **Anti-patterns**: using this as the default plan path (single-pass is default); a
  teammate-conductor invoking it; scope expansion during an amendment round beyond the
  structural issues `@critic` identified; running the loop without surfacing its intent and
  cap to the operator first — even at the default cap, an unannounced multi-round dialogue
  violates operator consent regardless of the `>3` threshold.

## FOCUS-LOOP (shepherd / conductor)

The orchestrator's own loop across a sprint: Wake (read focus record + rehydration digest) →
Act (dispatch/coordinate/advance the Stage Graph cursor) → Probe (check CLOSE-FINALIZE). A
**parameterization of the named FOCUS-LOOP composite**, not a new template — FOCUS-LOOP is
only named (not defined) in `skills/harness/references/workflow-templates.md §Named
composites`; the full definition is owned by `skills/motivation/SKILL.md §FOCUS-HEARTBEAT`.

- **Default `--max`: 8**, from `[focus].loop_max_default`. >10 requires critic sign-off.
- **Termination**: `new_findings: false` when CLOSE-FINALIZE is reached across all lanes
  (`v_teammates_live == 0` and every WAVE-COMPLETE payload materialized).
- **Re-anchor cadence**: the deterministic `[focus].heartbeat_interval` leg (native `/loop`
  clock) is the ONLY leg guaranteeing a re-anchor; the soft `[focus].heartbeat_actions` leg is
  a latent self-estimate, NEVER a counted guarantee. Full mechanics + block format:
  `skills/motivation/SKILL.md §FOCUS-HEARTBEAT`.
- **Compaction safety**: `[compaction].precompact_snapshot` MUST be `"on"` (default) —
  non-optional. A PreCompact hook snapshots the focus record; `SessionStart(source=compact)`
  rehydrates it before the next wake. Canonical mechanism: `skills/motivation/SKILL.md §Focus
  record`.
- **Anti-patterns**: running without a focus record; nesting FOCUS-LOOP inside another loop
  (give inner work its own `loop_id`); passive-wait between waves with an idle
  teammate (`coordinate_drive_guard` enforces this); root self-drift over a long ACT
  stretch with no wake to re-anchor.

## See also

- `skills/harness/references/workflow-templates.md` — CONVERGENCE-LOOP / WATCH-LOOP, Pattern 6
- `commands/loop.md` — `/shepherd:loop`; `--agent`; pacing modes
- `skills/shepherd/references/pipeline.md §Hotfix ladder`, `§DEDUP-GATE`, `§Gates`,
  `§Dispatch patterns` — dispatch vehicle, idempotency, `COMPOSITION-TOO-DEEP`
- `skills/shepherd/references/flock.md §@auditor`/`§@discovery`/`§@worker`,
  `skills/shepherd/SKILL.md §Dispatch law`, `skills/shepherd/references/escalation.md
  §Halt-code index` — root-tier rules, `PLAN-AUTHORSHIP-REQUEST`/`PLAN-GATE-REQUEST`
- `skills/motivation/SKILL.md §Sentinel`, `§SOAK`, `§FOCUS-HEARTBEAT`, `§Focus record`
