# Per-Role Loop Template Catalog

Ready-to-use loop templates for each applicable shepherd flock member and meta-orchestrator.
Every template specializes one of the three named Pattern-6 composites defined in
`references/workflow-templates.md` (FOCUS-LOOP, CONVERGENCE-LOOP, WATCH-LOOP). Do not
re-derive a named composite from scratch — reference it by name and parameterize.

Pattern-6 circuit-breaker invariants apply to every template below without exception. See
`doctrines/workflow-patterns.md §Circuit-breaker invariants — Pattern 6` and
`doctrines/loop-templates.md`.

---

## Quick-selection table

| Role | Template name | Composite | Default `--max` | Terminates on |
|------|--------------|-----------|-----------------|---------------|
| `@coder` | CODER-CONVERGENCE | CONVERGENCE-LOOP | 5 | Gate green (`new_findings: false`) |
| `@discovery` | DISCOVERY-EXHAUST | Loop-Until-Done (generic Pattern 6) | 4 | `new_findings: false` |
| `@worker` (state-reconcile) | WORKER-CONVERGENCE | CONVERGENCE-LOOP | 5 | State predicate met |
| `@worker` (monitoring) | WORKER-WATCH | WATCH-LOOP | 20 | Anomaly detected OR cap reached |
| `@worker` (outcome soak, detection-only) | SOAK-LOOP | WATCH-LOOP | 6 | A seeded predicate regressed OR all hold at cap |
| `@worker` PROBE + `@coder` ACT (**authorized supervised self-heal**) | AUTONOMOUS-SENTINEL | WATCH-LOOP (superset of SOAK-LOOP) | 6 | K clean ticks OR N-HF cap OR hard-stop |
| `@auditor` | AUDITOR-REFINE | Loop-Until-Done (generic Pattern 6) | 3 | Confidence plateau (`new_findings: false`) |
| `@engineer` | ENGINEER-PLAN-REFINE | Loop-Until-Done (generic Pattern 6) | 3 | Critic gate green |
| shepherd / conductor | FOCUS-LOOP | FOCUS-LOOP (named composite) | 8 | CLOSE-FINALIZE reached |

---

## @coder loop — CODER-CONVERGENCE

### Intent

Drive a coder to a deterministic gate-green state: all tests pass, linter clean, acceptance
greps satisfied. Generalizes the H ≥ 6 HOT-FIX lane's fix cycle to any scope where code
convergence is needed. Completion is defined by the absence of gate failures, not by a fixed
number of edits.

### Composite

Specializes **CONVERGENCE-LOOP** from `references/workflow-templates.md §CONVERGENCE-LOOP`.
The gate expression is the CONVERGENCE-LOOP's `gate:` field; CODER-CONVERGENCE supplies a
coder-specific brief and idiomatic gate expressions. All CONVERGENCE-LOOP invariants apply:
gate must be declared in the seed before dispatch; no post-hoc gate assembly.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Fix) | `@coder` | Apply one round of code fixes; emit `new_findings: true\|false` where `true` = gate still failing |
| Gate check | Conductor inline | Run deterministic gate (tests / lint / greps); feed failure list into next iteration's brief |
| Terminator | Conductor inline | On green gate OR cap: emit `## CODER-CONVERGENCE summary` |

### Loop body — Probe → Act → Branch

```
Probe:  Run gate expression. Extract failing items.
Act:    Fix failing items (one pass — do not over-fix; scope to gate failures only).
Branch: new_findings: false → LOOP-DONE (gate green)
        new_findings: true, i < max → next iteration with updated gate_failures list
        i >= max → LOOP-DONE-CAPPED; surface LOOP-CAP to operator
```

### Termination predicate

`new_findings: false` when the gate expression returns zero failures. The gate expression
MUST be declared in the seed before any iteration fires — a post-hoc gate is CIRCULAR-RUBRIC.

Common gate expressions:

```yaml
gate: "cargo test --workspace 2>&1 | tail -1 | grep -q 'test result: ok'"
gate: "npm test -- --passWithNoTests && npm run lint -- --max-warnings 0"
gate: "pytest -q && ruff check . --quiet"
gate: "tests-green AND lint-clean"          # abstract; resolve to shell expression in plan
```

### Stage Graph shape

```yaml
CODER-CONVERGENCE-INIT (conductor):
  kind: convergence
  max_iterations: 5           # default; values > 5 require engineer justification; > 10 critic sign-off
  iteration: 0
  gate: <gate-expression>     # declared in seed
  action: shctx loop init --kind=convergence --task="<gate>" --max=5 --agent=coder
  on-start: → CC-FIX

CC-FIX (coder):
  brief: coder-convergence-fix
  gate_failures: $gate_failures   # injected from prior gate run; empty on iteration 1
  iteration: $i
  constraint: fix ONLY items in gate_failures — no scope expansion
  emits: new_findings: true|false
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → CC-FIX (iteration: $i + 1)
  on-empty (new_findings: false):              → CC-LOOP-DONE
  on-cap ($i >= max):                          → CC-LOOP-CAPPED (conductor): surface LOOP-CAP

CC-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## CODER-CONVERGENCE summary" with round count, final gate state, fix inventory
```

### Default `--max`

**5**. Values > 5 require explicit engineer justification in the plan. Values > 10 require
critic sign-off at PLAN-GATE. Per `doctrines/workflow-patterns.md §Pattern 6` and the
CONVERGENCE-LOOP definition.

### Which composite

Specializes **CONVERGENCE-LOOP**. When this template's name appears in a Stage Graph, the
full CONVERGENCE-LOOP definition applies — do not re-derive.

### Anti-patterns

- **Scope expansion inside a convergence iteration.** The coder's brief MUST constrain fixes
  to the current `gate_failures` list. A coder that refactors adjacent code while "fixing"
  tests is scope-creeping — the gate may green while the refactor introduces regressions the
  next sprint will catch. Scope is `gate_failures` only.
- **Omitting the gate expression from the seed.** A gate assembled after observing failures
  is CIRCULAR-RUBRIC. Declare the gate at plant time.
- **Using CODER-CONVERGENCE for known-finite fix lists.** If the set of failing items is
  fully enumerable at loop start (e.g., "fix these 12 specific lint violations"), dispatch
  them as a Fanout-And-Synthesize (Pattern 2) instead — no loop needed.
- **Nesting CODER-CONVERGENCE inside a FOCUS-LOOP Act phase without a separate loop ID.**
  Each loop instance needs its own `loop_id`. Reusing the FOCUS-LOOP ID conflates sprint
  drive with fix convergence and breaks the `shctx loop` record chain.
- **Setting `--max > 10` without critic sign-off.** A hard gate that fails to green in 10
  iterations indicates a structural problem — the loop is not the right tool; escalate to
  the engineer for scope revision.

---

## @discovery loop — DISCOVERY-EXHAUST

### Intent

Drive a discovery agent through successive research sweeps until a question is exhaustively
answered — no new sources, angles, or findings remain. Completion is defined by the absence
of new findings (`new_findings: false`), not by a fixed source count. Each iteration builds
on the prior sweep's findings summary, narrowing toward full coverage.

`@discovery` is **read-only throughout.** No iteration of this loop mutates any state. See
`doctrines/discovery-readonly.md`.

### Composite

Specializes **Pattern 6 — Loop-Until-Done** directly (generic, not a named composite). The
iteration body is a `@discovery` read-only sweep; the loop controller is the conductor
inline. Does not use CONVERGENCE-LOOP (no gate to turn green) or WATCH-LOOP (no wall-clock
cadence needed).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Sweep) | `@discovery` | Read-only sweep of remaining sources; emit `new_findings: true\|false` + structured `findings_summary` |
| Loop controller | Conductor inline | Read `new_findings`; inject prior findings summary into next iteration's brief |
| Terminator | Conductor inline | On `new_findings: false` OR cap: emit exhaustive `## Discovery inventory` |

### Loop body — Probe → Act → Branch

```
Probe:  Review prior findings_summary. Identify unexplored sources or open questions
        from the previous iteration's "Suggested follow-ups".
Act:    Sweep unexplored sources only (do not re-read already-covered sources).
        Synthesize new findings per the discovery report schema (doctrines/discovery-readonly.md §Report shape).
Branch: new_findings: false → LOOP-DONE (exhausted)
        new_findings: true, i < max → next iteration; prior findings injected as [DISCOVERY-CONTEXT]
        i >= max → LOOP-DONE-CAPPED; surface LOOP-CAP to operator
```

### Termination predicate

`new_findings: false` when the current sweep surfaces no sources, angles, or findings not
already in the cumulative `findings_summary`. The discovery agent MUST set
`new_findings: false` only when it has actively checked for remaining unexplored avenues and
found none — not merely when it ran out of time or tokens.

### Stage Graph shape

```yaml
DISCOVERY-EXHAUST-INIT (conductor):
  kind: discovery-exhaust
  max_iterations: 4           # default; rarely needs to exceed 4; > 4 justify; > 10 critic sign-off
  iteration: 0
  question: "<research question>"
  action: shctx loop init --kind=loop --task="<question>" --max=4 --agent=discovery
  on-start: → DE-SWEEP

DE-SWEEP (discovery):
  brief: discovery-exhaust-sweep
  question: $question
  iteration: $i
  prior_findings_summary: $cumulative_findings   # empty on iteration 1; injected as [DISCOVERY-CONTEXT] for i > 1
  constraint: read-only; write only to {paths.reports}/<date>-discovery-<loop_id>-iter<i>.md
  emits:
    new_findings: true|false
    findings_summary:               # structured; per discovery-readonly.md §Report shape
      sources_consulted: <N>
      new_findings_this_sweep: [...]
      open_questions: [...]
      confidence: HIGH|MEDIUM|LOW
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → DE-SWEEP (iteration: $i + 1, prior injected)
  on-empty (new_findings: false):              → DE-LOOP-DONE
  on-cap ($i >= max):                          → DE-LOOP-CAPPED (conductor): surface LOOP-CAP

DE-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Discovery inventory" — aggregate all sweep findings_summary entries with iteration attribution
```

### Default `--max`

**4**. Research questions rarely require more than 4 sweeps to exhaust; additional iterations
usually indicate an under-scoped question rather than genuinely new sources. Values > 4
require justification. Values > 10 require critic sign-off.

### Which composite

Generic **Pattern 6 — Loop-Until-Done** (not a named composite). The named composites
(CONVERGENCE-LOOP, WATCH-LOOP) do not apply to read-only research sweeps.

### Anti-patterns

- **Treating DISCOVERY-EXHAUST as a research sprint.** This template drives exhaustive
  coverage of a single scoped question. Wide, ambiguous questions ("research everything about
  X") do not converge — scope the question tightly before looping.
- **Discovery mutations during loop.** No iteration may write outside `{paths.reports}`. If
  an iteration produces a recommendation, it surfaces the fact in `## Suggested follow-ups`;
  the conductor acts on it after the loop terminates. Discovery never mutates mid-loop.
- **Re-reading already-covered sources.** Each iteration's brief MUST inject the prior
  `findings_summary` as `[DISCOVERY-CONTEXT]`. The sweep adds to coverage; it does not
  re-derive it. Redundant source coverage inflates iteration count without improving quality.
- **Cross-sprint discovery reuse ignored.** Before initiating DISCOVERY-EXHAUST, run
  `shctx discovery search --question="<paraphrase>"`. A fresh discovery (< 2 sprints old)
  covering the question is reusable — no loop needed.
- **Looping discovery for monitoring.** Ongoing state observation (CI, deploy health,
  Sentry) belongs to WORKER-WATCH. Discovery is orientation, not surveillance.

---

## @worker loop — WORKER-CONVERGENCE (state-reconciliation variant)

### Intent

Drive a worker to a defined state target: config drift repaired, migration applied, file
organization completed, registry reconciled. Completion is defined by a state predicate
turning true — structurally the same gate-green criterion as CODER-CONVERGENCE but for
non-code tasks. Idempotency is mandatory: each iteration must produce a net-closer result
even if the state predicate has not yet flipped.

### Composite

Specializes **CONVERGENCE-LOOP** from `references/workflow-templates.md §CONVERGENCE-LOOP`.
Same structure as CODER-CONVERGENCE; the Fix node is `@worker` (non-code tasks) instead of
`@coder` (code changes). All CONVERGENCE-LOOP invariants apply.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Fix) | `@worker` | Apply one round of state-reconciling operations; emit `new_findings: true\|false` where `true` = state predicate still failing |
| State check | Conductor inline | Evaluate state predicate deterministically; feed failing items into next brief |
| Terminator | Conductor inline | On predicate met OR cap: emit `## WORKER-CONVERGENCE summary` |

### Loop body — Probe → Act → Branch

```
Probe:  Evaluate state predicate. Extract failing items.
Act:    Apply bounded, idempotent operations to close the gap (do not exceed SCOPE).
Branch: new_findings: false → LOOP-DONE (predicate met)
        new_findings: true, i < max → next iteration with updated failing_items list
        i >= max → LOOP-DONE-CAPPED; surface LOOP-CAP to operator
```

### Termination predicate

`new_findings: false` when the state predicate returns true. The predicate MUST be declared
in the seed. It must be deterministically evaluable without side effects so the conductor can
independently verify the termination claim.

Example predicates:

```yaml
predicate: "shctx doctor --namespace=$ns --check=schema-current → exit 0"
predicate: "gh issue list --state=open --label=critical --json id | jq 'length == 0'"
predicate: "find .artifacts/tmp -name '*.tmp' | wc -l | grep -q '^0$'"
predicate: "git -C .worktrees/$lane diff --stat | wc -l | grep -q '^0$'"
```

### Idempotency requirement

Every operation in the `@worker` brief MUST be safe to repeat. Operations with
non-idempotent side effects (e.g., appending to a file on each iteration) MUST include a
dedup check. The DEDUP-GATE in `commands/loop.md §Step 4` applies to write-capable worker
loops.

### Stage Graph shape

```yaml
WORKER-CONVERGENCE-INIT (conductor):
  kind: convergence
  max_iterations: 5           # default; > 5 requires justification; > 10 critic sign-off
  iteration: 0
  predicate: <state-predicate>    # declared in seed; deterministically evaluable
  action: shctx loop init --kind=convergence --task="<predicate>" --max=5 --agent=worker
  on-start: → WC-FIX

WC-FIX (worker):
  brief: worker-convergence-fix
  failing_items: $failing_items   # injected from prior predicate evaluation
  iteration: $i
  constraint: bounded, idempotent operations on SCOPE only; no scope expansion
  emits: new_findings: true|false
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → WC-FIX (iteration: $i + 1)
  on-empty (new_findings: false):              → WC-LOOP-DONE
  on-cap ($i >= max):                          → WC-LOOP-CAPPED (conductor): surface LOOP-CAP

WC-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## WORKER-CONVERGENCE summary" with round count, final predicate state, operation log
```

### Default `--max`

**5**. Same as CODER-CONVERGENCE; the same cap and justification requirements apply.

### Which composite

Specializes **CONVERGENCE-LOOP**. When this template appears in a Stage Graph, the full
CONVERGENCE-LOOP definition from `references/workflow-templates.md` applies.

### Anti-patterns

- **Non-idempotent operations.** A worker that appends or creates on every iteration
  diverges instead of converging. All operations must be re-runnable without compounding
  side effects.
- **Ambiguous state predicate.** A predicate like "things look clean" is not evaluable. The
  conductor must be able to run the predicate independently and verify the worker's
  `new_findings: false` claim. Prose predicates are LOOP-REPORT-INVALID candidates.
- **Worker dispatching sub-agents.** Workers are leaf dispatches — they do not compose flock
  work. If reconciliation requires coordination, the conductor owns the loop and the worker
  handles only the bounded fix step per iteration.

---

## @worker loop — WORKER-WATCH (monitoring variant)

### Intent

Bounded, wall-clock-scheduled monitoring: watch a deploy stabilize, poll a Sentry error
stream, check CI status, or observe a service health endpoint at a fixed interval. Terminates
on anomaly detection (alert operator) or iteration cap (monitoring window closed). The
`@worker` probe is bounded, read-only or alert-only — it does not remediate.

### Composite

Specializes **WATCH-LOOP** from `references/workflow-templates.md §WATCH-LOOP`. The
scheduling is delegated to the native `/loop` command. All WATCH-LOOP invariants apply:
`--interval` is mandatory; the native `/loop` 7-day auto-expiry is the outer hard bound;
probe bodies must be simple (no inner fanout). `@discovery` is NOT a valid probe iterator
for this template — use `@worker` exclusively per the WATCH-LOOP agent binding.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Probe iterator | `@worker` (bounded, read-only or alert-only) | On each tick: query target; emit `new_findings: true\|false` where `true` = anomaly |
| Interval scheduler | Native `/loop` | Emits wake event on cadence; auto-expires after 7 days |
| Terminator | Conductor inline | On anomaly: surface alert. On cap/expiry: emit `## Watch summary` |

### Loop body — Probe → Act → Branch

```
Probe:  Query target (endpoint, log stream, CI status, Sentry). Collect observations.
Act:    Classify observations: nominal or anomalous per the anomaly_criteria declared in seed.
Branch: new_findings: false (nominal) → yield to next /loop tick
        new_findings: true (anomaly)  → WATCH-ALERT; surface to operator; terminate loop
        i >= max OR /loop expiry      → WATCH-LOOP-DONE; emit Watch summary
```

### Termination predicate

`new_findings: true` when the probe observations match the declared `anomaly_criteria`.
`new_findings: false` means this tick is nominal — the scheduler drives the next wake.
Cap-or-expiry terminates regardless of findings.

The `anomaly_criteria` MUST be declared in the seed before the loop starts. The probe
worker is not expected to define "anomaly" — it classifies against the supplied criteria.

Example anomaly criteria:

```yaml
anomaly_criteria: "HTTP /health returns non-200 OR response_time_ms > 2000"
anomaly_criteria: "Sentry error_rate > 5/min for project:my-project env:prod"
anomaly_criteria: "CI run status != 'success' on branch main"
anomaly_criteria: "deploy status != 'running' in fly.io app my-app"
```

### Stage Graph shape

```yaml
WORKER-WATCH-INIT (conductor):
  kind: watch
  max_iterations: 20          # default for monitoring window; also bounded by native /loop 7-day expiry
  interval: <duration>        # MANDATORY — e.g. '5m', '15m', '1h'; delegated to native /loop
  target: <endpoint-or-query>
  anomaly_criteria: <criteria>    # declared in seed
  action: shctx loop init --kind=watch --task="monitor <target>" --max=20 --interval=<dur> --agent=worker
  on-start: → WATCH-PROBE (via native /loop scheduling)

WATCH-PROBE (worker):
  brief: worker-watch-probe
  target: $target
  anomaly_criteria: $anomaly_criteria
  iteration: $i
  constraint: read-only or alert-only; no remediation
  emits: new_findings: true|false   # true = anomaly matches criteria; false = nominal
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-empty (new_findings: false, $i < max):  → WATCH-PROBE (iteration: $i + 1, via /loop tick)
  on-findings (new_findings: true):          → WATCH-ALERT (conductor): surface anomaly to operator; terminate
  on-cap ($i >= max):                        → WATCH-LOOP-DONE
  on-expiry (native /loop expired):          → WATCH-LOOP-DONE

WATCH-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Watch summary" with observation count, anomalies (if any), final status
```

### Default `--max`

**20**. Monitoring windows are longer-horizon by nature. The 7-day native `/loop` auto-expiry
is the outer hard bound regardless of `--max`. For short monitoring windows (e.g., watch a
30-minute deploy), set `--max` to match the expected window at the configured interval.

### Which composite

Specializes **WATCH-LOOP**. When this template appears in a Stage Graph, the full WATCH-LOOP
definition from `references/workflow-templates.md` applies.

### Anti-patterns

- **WORKER-WATCH without `--interval`.** A watch loop without wall-clock scheduling is
  structurally WORKER-CONVERGENCE. Select the correct template.
- **Probe body dispatching remediation.** The loop's job is detection and surfacing.
  Remediation is the operator's decision. Embedding a CODER-CONVERGENCE or WORKER-CONVERGENCE
  inside a WORKER-WATCH anomaly handler violates the WATCH-LOOP leaf-composite constraint and
  exceeds the depth-3 composition limit (`doctrines/workflow-patterns.md §Composition depth
  limit`).
- **`@discovery` as probe iterator.** Discovery is sprint-orientation read-only; it is not a
  monitoring agent. Use `@worker` for all WORKER-WATCH probe iterations — explicitly stated
  in the WATCH-LOOP definition.
- **Monitoring horizon beyond 7 days in a single loop.** The native `/loop` auto-expiry is
  non-overridable. For longer horizons, re-initialize a new WORKER-WATCH loop after expiry.

---

## @worker loop — SOAK-LOOP (post-delivery outcome re-verification variant)

### Intent

Confirm that a *closed* sprint's seeded **outcomes** stay true after delivery. Shepherd is
strong at landing code and green gates, but a gate-green close is not proof the seeded outcome
holds — a deploy can regress p99, a migration can drop a row count, an error rate can climb a
day later. SOAK-LOOP re-runs the sprint's seeded **acceptance predicates** (`seed §6`,
`doctrines/outcome-enforcement.md`) against live state on a post-close interval (e.g. T+1d,
T+7d) and surfaces any predicate that *was promised true and is now false*. It is the
detection half of outcome-enforcement that runs **after** the close gate, on wall-clock time.

### Composite

Specializes **WATCH-LOOP** from `references/workflow-templates.md §WATCH-LOOP`. SOAK-LOOP is
WORKER-WATCH re-pointed from "anomaly criteria" to "the seeded acceptance predicates" — the
target is the sprint's own promises rather than a generic health signal. All WATCH-LOOP
invariants apply: `--interval` is mandatory; the native `/loop` 7-day auto-expiry is the outer
hard bound; the probe body is simple (run the predicates, classify, yield) with no inner
fanout; `@worker` is the only valid probe iterator.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Probe iterator | `@worker` (bounded, read-only) | On each tick: re-run each seeded acceptance predicate against live state; emit `new_findings: true\|false` where `true` = a predicate regressed |
| Interval scheduler | Native `/loop` | Emits wake event on cadence (`--interval`); auto-expires after 7 days |
| Terminator | Conductor / root inline | On regression: surface `OUTCOME-REGRESSION` to operator. On all-hold-at-cap: emit `## Soak summary` |

### Loop body — Probe → Act → Branch

```
Probe:  Run each seeded acceptance predicate at live HEAD / live service (the same checks the
        seed §6 declared and the close auditor ran — greps, row counts, latency/error queries).
Act:    Classify each predicate result against its promised truth value from the seed.
Branch: new_findings: false (all predicates still hold) → yield to next /loop tick
        new_findings: true (a predicate regressed)      → SOAK-ALERT; surface OUTCOME-REGRESSION; terminate
        i >= max OR /loop expiry                         → SOAK-LOOP-DONE; emit Soak summary
```

### Termination predicate

`new_findings: true` when any seeded predicate that was promised true now returns false — i.e.
an outcome **regressed** after close. `new_findings: false` means every predicate still holds
this tick; the scheduler drives the next wake. Cap-or-expiry terminates regardless.

The predicates are NOT authored by the soak worker — they are the seed's own acceptance
checks, carried forward from `seed §6` (and re-run by the close auditor per
`doctrines/outcome-enforcement.md`). A soak loop that invents new checks is scope creep; it
verifies the *promised* outcomes only.

Example predicate sets (carried from the seed, not invented here):

```yaml
soak_predicates:
  - "grep -rc 'impl Trait for' crates/ | awk -F: '{s+=$2} END{exit !(s==5)}'"   # struct count == 5
  - "curl -fsS https://app/health | jq -e '.p99_ms < 100'"                       # latency SLO holds
  - "sentry error_rate project:app env:prod < 1/min"                             # error budget intact
```

### Stage Graph shape

```yaml
SOAK-LOOP-INIT (conductor / root):
  kind: watch
  max_iterations: 6           # default for a T+1d / T+7d soak window; bounded by native /loop 7-day expiry
  interval: <duration>        # MANDATORY — e.g. '1d', '6h'; delegated to native /loop
  soak_predicates: <list>     # carried from the closed sprint's seed §6 — NOT invented here
  action: shctx loop init --kind=watch --task="soak outcomes <sprint>" --max=6 --interval=<dur> --agent=worker
  on-start: → SOAK-PROBE (via native /loop scheduling)

SOAK-PROBE (worker):
  brief: worker-soak-probe
  soak_predicates: $soak_predicates
  iteration: $i
  constraint: read-only; re-run the seeded predicates ONLY; no remediation, no new checks
  emits: new_findings: true|false   # true = a promised-true predicate now returns false
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-empty (new_findings: false, $i < max):  → SOAK-PROBE (iteration: $i + 1, via /loop tick)
  on-findings (new_findings: true):          → SOAK-ALERT (root): surface OUTCOME-REGRESSION; terminate
  on-cap ($i >= max):                        → SOAK-LOOP-DONE
  on-expiry (native /loop expired):          → SOAK-LOOP-DONE

SOAK-LOOP-DONE (conductor / root):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Soak summary" with predicate roster, per-predicate pass/fail history, final verdict
```

### Default `--max`

**6**. A soak window is typically a handful of post-close checkpoints (e.g. T+1d, T+3d, T+7d),
not continuous monitoring. The 7-day native `/loop` auto-expiry is the outer hard bound; for a
T+7d soak, re-initialize the loop after the first expiry. Set `--max` to the number of planned
checkpoints at the chosen interval.

### Which composite

Specializes **WATCH-LOOP**. When SOAK-LOOP appears in a Stage Graph, the full WATCH-LOOP
definition from `references/workflow-templates.md` applies, with the anomaly target bound to
the seeded acceptance predicates.

### Anti-patterns

- **Soaking outcomes that were never declared.** SOAK-LOOP re-runs `seed §6` predicates. If
  the seed declared no machine-checkable outcomes, there is nothing to soak — fix that at the
  seed/plan-gate (`doctrines/outcome-enforcement.md`), not by inventing checks in the loop.
- **Remediating inside the probe — UNLESS explicitly authorized.** By default, like
  WORKER-WATCH, the probe detects and surfaces; it does not fix. A regression opens a *new*
  hotfix/sprint decision for the operator — embedding a CODER-CONVERGENCE in the alert handler
  violates the depth-3 composition limit. The **one** authorized exception is the
  **AUTONOMOUS-SENTINEL** template below (the supervised superset of this one): when the seed
  carries `close: autonomous-sentinel` **and** a complete `sentinel_rails` block, an ACT stage
  is permitted between CLASSIFY and the next tick. Without that explicit gate, remediation inside
  a soak probe remains the anti-pattern. See `§AUTONOMOUS-SENTINEL` and
  `doctrines/autonomous-sentinel.md`.
- **Soak as a substitute for the close gate.** Outcome-enforcement is verified *at close*
  first (`doctrines/outcome-enforcement.md §Seam 2`); the soak loop catches *post-close* drift.
  A sprint that skips the close-gate predicate run and "leaves it to soak" has shipped an
  unverified outcome.
- **`@discovery` or a teammate-conductor as probe iterator.** Use `@worker` — a soak probe is
  a bounded read-only tick, not orientation research and not a lane.

---

## @worker PROBE + @coder ACT loop — AUTONOMOUS-SENTINEL (authorized supervised self-heal variant)

### Intent

The **supervised-remediation superset of SOAK-LOOP**. SOAK-LOOP (and WORKER-WATCH) are
*detection-only* by design — the probe surfaces an `OUTCOME-REGRESSION` and the operator decides
whether to fix it. That is the correct default. AUTONOMOUS-SENTINEL is for the **explicitly
authorized** case: an operator who has read the rails, accepted the blast radius, and empowered
the conductor to **FIX** a live regression during a soak/close window rather than wait a tick to
be asked. Everything SOAK-LOOP does (re-run the seeded acceptance predicates on wall-clock time)
**plus** an `ACT` stage that dispatches a bounded hotfix through the **existing hotfix-dispatch
ladder**, re-probes, and converges or hard-stops.

It can **NEVER** fire by default. It is gated three times over: the config key
`[close].autonomous_sentinel` must be `"on"` (default `"off"`), the seed must declare
`close: autonomous-sentinel`, AND the seed must carry a complete `sentinel_rails` block. Absence
of any one means the default detection-only SOAK-LOOP runs. The full rails contract, the
audit-trail requirement, and the relationship to hotfix-dispatch live in
`doctrines/autonomous-sentinel.md` (origin v6.2.0).

### Composite

Specializes **WATCH-LOOP** from `references/workflow-templates.md §WATCH-LOOP`, as the **superset
of SOAK-LOOP**: SOAK-LOOP's `PROBE → CLASSIFY → yield` with an `ACT` stage spliced between CLASSIFY
and the next tick. Strip the ACT stage and the rails block and you are left with exactly SOAK-LOOP.
All WATCH-LOOP invariants apply: `--interval` is mandatory; the native `/loop` 7-day auto-expiry is
the outer hard bound; the PROBE/CLASSIFY body is `@worker` read-only. The ACT stage is **not** a
worker step — it dispatches `@coder` through `doctrines/hotfix-dispatch.md`, exactly as a
gate-failure hot-fix would (NOT a bespoke mechanism).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Probe iterator | `@worker` (bounded, read-only) | On each tick: re-run each seeded acceptance predicate; CLASSIFY each as HOLD / REGRESSED / NEW; emit `new_findings: true\|false` where `true` = a predicate REGRESSED |
| Remediator (ACT) | `@coder` via `doctrines/hotfix-dispatch.md` | For each REGRESSED cluster (≤S, file-disjoint): one `@coder` HF (`H=1`) or one batched dynamic workflow (`(1,3]`, ≤3 concurrent); gates-before-deploy; auto-rollback on red |
| Interval scheduler | Native `/loop` | Emits wake event on cadence (`--interval`); auto-expires after 7 days |
| Terminator | Conductor / root inline | On K clean ticks: `## Sentinel summary`. On rail trip / HF cap / scope exceed: hard-stop to operator |

`NEW` failures (a failure with no seeded baseline) are **detection-only** — surfaced, never
auto-remediated. Only `REGRESSED` predicates enter ACT scope.

### Loop body — Probe → Classify → Act → Branch

```
Probe:    Run each seeded acceptance predicate at live HEAD / live service (same checks as SOAK-LOOP).
Classify: HOLD (promised-true, still true) / REGRESSED (promised-true, now false) / NEW (no seeded baseline).
Act:      For each REGRESSED cluster (NEW is detection-only):
            severity gate ≤S → else SENTINEL-SCOPE-EXCEEDED hard-stop
            dispatch via hotfix-dispatch ladder (H=1 → 1 @coder; (1,3] → batched, ≤3 concurrent)
            gates-before-deploy → failed gate = AUTO-ROLLBACK (revert, no deploy)
            deploy/promote ONLY if gates green AND rails permit a live flip (paper-only default)
            re-probe the regressed predicate to confirm the fix held
Branch:   all HOLD this tick (no REGRESSED)          → new_findings: false; yield to next /loop tick
          REGRESSED remediated + re-probe HOLD        → ACT done; yield to next tick
          K consecutive clean ticks (all HOLD)        → SENTINEL-DONE (converged)
          N total hot-fixes dispatched                → SENTINEL-HF-CAP hard-stop
          regression exceeds ≤S OR any rail tripped    → SENTINEL-HARD-STOP / SENTINEL-SCOPE-EXCEEDED
          i >= max OR /loop expiry (regression open)   → SENTINEL-LOOP-CAP (LOOP-CAP shape)
```

### Termination predicate

`new_findings: false` means this tick is all-HOLD (no REGRESSED predicate). The loop converges on
**K consecutive clean ticks** (`SENTINEL-DONE`), not on a single clean tick — a self-heal that just
remediated must prove the fix holds across K ticks before declaring done. Cap-or-expiry while a
regression is still open terminates as `SENTINEL-LOOP-CAP` (the `LOOP-CAP` shape). The seeded
predicates are NOT authored by the sentinel — they are the seed's own `§6` acceptance checks,
identical to SOAK-LOOP; a sentinel that invents new checks is scope creep.

### Required rails — declared in the seed's `sentinel_rails` block

Every rail is mandatory; a `close: autonomous-sentinel` seed missing any rail is rejected at
PLAN-GATE with `SENTINEL-RAILS-MISSING`. Full table in `doctrines/autonomous-sentinel.md §The hard rails`:

```yaml
sentinel_rails:
  gates_before_deploy: true        # full gate set runs on every fix BEFORE deploy — no deploy on red
  auto_rollback: true              # failed gate reverts the fix automatically (SENTINEL-ROLLBACK, logged)
  max_severity: S                  # every remediation cluster ≤S; larger = SENTINEL-SCOPE-EXCEEDED
  max_concurrent: 3                # ≤3 concurrent @coder clusters per ACT (standing HOTFIX cap)
  hf_cap: 3                        # ≤N total hot-fixes across the window; N+1 = SENTINEL-HF-CAP
  no_destructive_db_ops: true      # never DROP/TRUNCATE/irreversible migration, regardless of authorization
  live_flip: paper-only            # paper-only (default) | authorized — never flip to live unless authorized
  operator_override_each_tick: true # operator HALT honored before the next ACT; native /loop is cancelable
  audit_trail: full                # every PROBE/CLASSIFY/ACT/gate/deploy/re-probe recorded (shctx loop record + hook event log)
```

### Stage Graph shape

```yaml
AUTONOMOUS-SENTINEL-INIT (conductor / root):
  kind: watch
  gate: close.autonomous_sentinel == "on"   # config gate; default "off" → fall back to SOAK-LOOP
  seed_declaration: close: autonomous-sentinel   # MANDATORY; absent → SOAK-LOOP
  sentinel_rails: <block>     # MANDATORY; incomplete → SENTINEL-RAILS-MISSING at PLAN-GATE
  max_iterations: 6           # default soak window; bounded by native /loop 7-day expiry
  clean_ticks_to_converge: 2  # K — consecutive all-HOLD ticks required to declare SENTINEL-DONE
  interval: <duration>        # MANDATORY — e.g. '1d', '6h'; delegated to native /loop
  soak_predicates: <list>     # carried from the closed sprint's seed §6 — NOT invented here
  action: shctx loop init --kind=watch --task="sentinel <sprint>" --max=6 --interval=<dur> --agent=worker
  on-start: → SENTINEL-PROBE (via native /loop scheduling)

SENTINEL-PROBE (worker):
  brief: worker-soak-probe        # identical to SOAK-LOOP's probe — read-only, re-run seeded predicates only
  soak_predicates: $soak_predicates
  iteration: $i
  constraint: read-only; re-run seeded predicates ONLY; CLASSIFY HOLD/REGRESSED/NEW; no remediation here
  emits: new_findings: true|false   # true = a promised-true predicate REGRESSED this tick
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-empty (new_findings: false):  → SENTINEL-TICK-CLEAN (increment clean-tick counter)
  on-findings (new_findings: true): → SENTINEL-ACT

SENTINEL-ACT (conductor / root → @coder via hotfix-dispatch ladder):
  trigger: one or more REGRESSED predicates (NEW excluded — surfaced only)
  vehicle: doctrines/hotfix-dispatch.md   # H=1 → one @coder; (1,3] → batched dynamic workflow, ≤3 concurrent
  severity_gate: every cluster ≤S         # else → SENTINEL-SCOPE-EXCEEDED (hard-stop)
  gates_before_deploy: full gate set on the fix BEFORE any deploy
  on-gate-red:  → SENTINEL-ROLLBACK (revert fix; no deploy; log; count toward hf_cap)
  on-gate-green: deploy ONLY if rails.live_flip == authorized; else stop at gate-green artifact
  re-probe: re-run the regressed predicate(s); REGRESSED-still → failed ACT cycle
  on-hf-cap ($hf_dispatched >= hf_cap):    → SENTINEL-HF-CAP (hard-stop)
  on-done: reset clean-tick counter to 0; → yield to next /loop tick

SENTINEL-TICK-CLEAN (conductor):
  on-converge ($clean_ticks >= K):  → SENTINEL-DONE
  on-continue ($clean_ticks < K, $i < max): → SENTINEL-PROBE (next /loop tick)
  on-cap ($i >= max):               → SENTINEL-LOOP-CAP

SENTINEL-DONE (conductor / root):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Sentinel summary" — predicate roster, per-tick CLASSIFY history, every ACT cycle
        (dispatch → gate → deploy/rollback → re-probe), final verdict
```

### Default `--max`

**6**. Same window as SOAK-LOOP — a handful of post-close checkpoints, not continuous monitoring.
The 7-day native `/loop` auto-expiry is the outer hard bound. The `K` clean-ticks-to-converge
default is **2** (a self-heal proves a fix holds across at least two ticks before declaring done).
The `hf_cap` default is small (e.g. 3) — the sentinel is bounded remediation, not a rescue sprint.

### Halt codes

| Code | Trigger | Resolution |
|------|---------|-----------|
| `SENTINEL-RAILS-MISSING` | `close: autonomous-sentinel` seed without a complete `sentinel_rails` block | `@critic` rejects at PLAN-GATE; planter/operator completes the rails block |
| `SENTINEL-SCOPE-EXCEEDED` | A REGRESSED cluster exceeds the ≤S severity cap | Hard-stop; surface to operator; never widen — a bigger fix is a sprint decision |
| `SENTINEL-HF-CAP` | Total hot-fixes dispatched reaches `hf_cap` | Hard-stop; operator decides extend / accept / escalate to a sprint |
| `SENTINEL-ROLLBACK` | A fix failed gates-before-deploy | Auto-revert (rails working as designed); logged, counts toward `hf_cap`; loop continues |
| `SENTINEL-HARD-STOP` | Any rail tripped (destructive DB op, unauthorized live flip, etc.) | Loop stops; operator decision; no auto-widen / auto-flip |
| `SENTINEL-LOOP-CAP` | `--max` ticks reached with a regression still open | `LOOP-CAP` shape; surface inventory; operator extends / accepts / escalates |

### Which composite

Specializes **WATCH-LOOP** as the **superset of SOAK-LOOP**. When AUTONOMOUS-SENTINEL appears in a
Stage Graph, the full WATCH-LOOP definition applies, with the anomaly target bound to the seeded
acceptance predicates AND the authorized ACT stage spliced in. The ACT vehicle is
`doctrines/hotfix-dispatch.md` — the sentinel narrows the ladder's upper bound (its `hf_cap` is
smaller than a lane), so the `H ≥ 6` dedicated-lane band does NOT apply: a regression that would
need a dedicated lane has exceeded the sentinel's scope and hard-stops.

### Anti-patterns

- **Firing without authorization.** Detection-only (SOAK-LOOP) is the default and stays the
  default. Without `[close].autonomous_sentinel = "on"` + `close: autonomous-sentinel` in the seed
  + a complete `sentinel_rails` block, the loop is SOAK-LOOP and the depth-3 remediation-inside-a-watch
  anti-pattern still binds.
- **Remediating a NEW failure.** Only `REGRESSED` predicates (promised-true, now-false against a
  seeded baseline) are in ACT scope. A NEW failure is surfaced for an operator decision, never auto-fixed.
- **Deploying on red / flipping to live without authorization.** Gates-before-deploy and
  paper-only are mandatory rails. A live flip requires `live_flip: authorized`; otherwise the
  sentinel stops at the gate-green artifact.
- **Inventing a bespoke remediation mechanism.** ACT dispatches through `doctrines/hotfix-dispatch.md`
  — one `@coder` (`H=1`) or one batched dynamic workflow (`(1,3]`). A hand-rolled fix path bypasses
  the ladder's caps and the audit trail.
- **Widening scope to fix a big regression.** A regression exceeding ≤S is `SENTINEL-SCOPE-EXCEEDED`
  — surfaced, never widened.
- **Converging on a single clean tick.** A self-heal must prove the fix holds across `K` consecutive
  clean ticks (default 2) before `SENTINEL-DONE`. One clean tick right after an ACT is not convergence.

---

## @auditor loop — AUDITOR-REFINE

### Intent

Progressive deepening of audit coverage across successive hypothesis-generation sweeps,
where each sweep's falsification results inform the next round of hypotheses. Each iteration
adds confidence to the cumulative findings set, and the loop terminates when marginal
confidence gain drops below threshold (operationalized as `new_findings: false`).

**This template is rare.** Auditors normally run as a swarm (Adversarial Verification,
Pattern 3) — multiple auditors in parallel, each with an independent concern split, no shared
context before filing. Use AUDITOR-REFINE only when the audit question is inherently
sequential: each sweep's evidence is needed before the next hypothesis can be formed (e.g.,
tracing a causal chain in a dependency graph, progressive data-flow analysis). If the audit
question can be decomposed into independent concerns, use a Pattern-3 swarm instead.

### When a loop is appropriate vs. a swarm

| Situation | Use |
|-----------|-----|
| Multiple independent concerns (code-quality, data-flow, dependency-topology, etc.) | Pattern-3 CLOSE-SWARM |
| Single auditor, XS scope, no parallelism benefit | Single direct dispatch (no loop) |
| Audit question requires sequential hypothesis refinement (chain tracing, causal analysis) | AUDITOR-REFINE loop |
| Re-audit after hotfix to verify fix landed | Single direct dispatch (no loop); or CODER-CONVERGENCE if the fix cycle is still open |
| Deep progressive analysis where each finding opens a new angle | AUDITOR-REFINE loop |

### Composite

Specializes **Pattern 6 — Loop-Until-Done** directly. The iteration body is an `@auditor`
hypothesis-driven sweep per `doctrines/auditor-hypothesis-driven.md`. The termination signal
is confidence plateau — the auditor reports `new_findings: false` when no hypothesis
generated this sweep survived falsification. Each iteration uses the per-finding evidence
contract (Hypothesis + Falsification + Confidence) from `doctrines/auditor-hypothesis-driven.md`.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Sweep) | `@auditor` | One hypothesis-generation + falsification sweep; emit structured findings + `new_findings` |
| Loop controller | Conductor inline | Inject prior findings as carry-forward context; route on `new_findings` |
| Terminator | Conductor inline | On confidence plateau OR cap: emit `## Audit inventory` |

### Loop body — Probe → Act → Branch

```
Probe:  Review prior findings set. Generate new hypotheses conditioned on unresolved areas
        or follow-on angles from prior falsification results.
Act:    Execute falsification attempts for each hypothesis. Discard disproved hypotheses.
        File only confirmed findings with full evidence contract.
Branch: new_findings: false → LOOP-DONE (confidence plateau)
        new_findings: true, i < max → next sweep; prior findings injected
        i >= max → LOOP-DONE-CAPPED; surface LOOP-CAP
```

### Termination predicate

`new_findings: false` when the sweep generates no hypotheses that survive falsification — no
new confirmed findings this iteration. An auditor that runs out of hypotheses to test MUST
set `new_findings: false` rather than filing low-confidence findings to avoid triggering
another iteration. Per `doctrines/auditor-hypothesis-driven.md`, LOW-confidence findings
belong in `## Open questions`, not in the findings set.

### Stage Graph shape

```yaml
AUDITOR-REFINE-INIT (conductor):
  kind: auditor-refine
  max_iterations: 3           # default; rarely beneficial beyond 3 passes; justify > 3; critic sign-off > 10
  iteration: 0
  concern: <concern>          # scope declaration for this progressive audit
  action: shctx loop init --kind=loop --task="progressive-audit:<concern>" --max=3 --agent=auditor
  on-start: → AR-SWEEP

AR-SWEEP (auditor):
  brief: auditor-refine-sweep
  concern: $concern
  iteration: $i
  prior_findings: $cumulative_findings    # injected as carry-forward context; empty for i=1
  methodology: hypothesis-driven          # per doctrines/auditor-hypothesis-driven.md
  emits:
    new_findings: true|false
    findings_summary:
      confirmed_findings: [...]           # full evidence contract per each
      open_questions: [...]
      verifications: [...]               # disproved hypotheses (no-finding record)
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → AR-SWEEP (iteration: $i + 1)
  on-empty (new_findings: false):              → AR-LOOP-DONE
  on-cap ($i >= max):                          → AR-LOOP-CAPPED (conductor): surface LOOP-CAP

AR-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Audit inventory" — all confirmed findings across sweeps with iteration attribution
```

### Default `--max`

**3**. Three hypothesis-driven sweeps are sufficient for most causal-chain analysis; marginal
returns diminish rapidly. Values > 3 require justification. Values > 10 require critic
sign-off. If the question requires more than 3 sweeps, revisit the concern scope — it may be
better decomposed into a Pattern-3 swarm of independent concerns.

### Which composite

Generic **Pattern 6 — Loop-Until-Done**. Not a named composite. Unlike CODER-CONVERGENCE
and WORKER-CONVERGENCE, AUDITOR-REFINE does not specialize CONVERGENCE-LOOP because the
termination condition is confidence accumulation, not a deterministic gate-green state.

### Anti-patterns

- **Using AUDITOR-REFINE when a swarm is appropriate.** If the audit question decomposes
  into independent concerns, use Pattern 3 (Adversarial Verification with multiple parallel
  auditors). AUDITOR-REFINE is for inherently sequential hypothesis chains only.
- **Filing LOW-confidence findings to trigger another iteration.** An auditor setting
  `new_findings: true` on LOW-confidence findings that should be `## Open questions` is
  inflating the iteration count. Terminate at confidence plateau, not at "I still have
  suggestions."
- **Prior findings not injected.** Each sweep MUST receive the cumulative prior findings as
  carry-forward context. A sweep that re-derives findings already in the prior set wastes
  iterations and produces duplicates.
- **Auditor grading in intro mode inside a loop.** If AUDITOR-REFINE is embedded in the
  INTRODUCTION phase, the auditor is in regression/carry-forward mode — it surfaces findings
  but does NOT assign grades. Grade only in close mode.

---

## @engineer loop — ENGINEER-PLAN-REFINE

### Intent

Iterative plan refinement when `@critic` returns REJECT-STRUCTURAL on a plan that requires
non-trivial amendment — not a simple correction but a genuine plan/critic dialogue where
each amendment round surfaces a new structural issue that requires re-evaluation. This is
rare: single-pass critic feedback with targeted amendments (`PLAN-AMEND`) is the normal path.

**This template is strongly discouraged except for genuine plan/critic ping-pong.**
Single-pass is always preferred; the ENGINEER-PLAN-REFINE loop should appear in a Stage Graph
only when the engineer and conductor both agree the plan requires iterative structural
convergence and the operator has acknowledged the additional cost.

This template is **root-tier-exclusive** under `/shepherd:spawn` per
`doctrines/dispatch-tier-separation.md`. Teammate-conductors MUST NOT use it — they surface
`PLAN-AUTHORSHIP-REQUEST` and `PLAN-GATE-REQUEST` escalations instead. Under
`/shepherd:start` solo mode this restriction does not apply (solo conductor IS root).

### Composite

Specializes **Pattern 6 — Loop-Until-Done** directly. The termination predicate is critic
gate-green (`new_findings: false` = critic passes the plan). Not a named composite.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Amend) | `@engineer` (root-tier only) | Revise plan in response to critic findings; emit amended plan |
| Gate check | `@critic` inline (root-tier only) | Re-evaluate amended plan; emit `new_findings: true\|false` where `true` = structural issues remain |
| Terminator | Conductor inline | On critic pass OR cap: emit plan final state |

### Loop body — Probe → Act → Branch

```
Probe:  Read critic findings from prior iteration. Identify structural issues that remain.
Act:    Amend plan to address structural issues — minimal, targeted; no scope expansion.
        Surface amended plan to critic.
Branch: new_findings: false → LOOP-DONE (critic passes; proceed to BODY)
        new_findings: true, i < max → next amendment round
        i >= max → LOOP-DONE-CAPPED; escalate to operator
```

### Termination predicate

`new_findings: false` when `@critic` returns PASS on the amended plan. `@critic` sets
`new_findings: false` only when no structural REJECT issues remain (WARN-level items may
remain). Per `doctrines/dispatch-tier-separation.md`, this gate fires only in root tier.

### Stage Graph shape

```yaml
ENGINEER-PLAN-REFINE-INIT (conductor, root-tier only):
  kind: plan-refine
  max_iterations: 3           # default; single-pass is norm; > 3 requires operator acknowledgement
  iteration: 0
  justification: <why single-pass is insufficient>   # required in plan if loop is used
  action: shctx loop init --kind=loop --task="plan-refine" --max=3 --agent=engineer
  on-start: → EPR-AMEND

EPR-AMEND (engineer, root-tier only):
  brief: engineer-plan-refine
  critic_findings: $prior_critic_findings    # injected from prior critic run
  iteration: $i
  constraint: minimal targeted amendments only; no scope expansion from the amendment round
  emits: amended_plan: <plan artifact path>
  action: shctx loop record --id=$loop_id --iteration=$i

EPR-GATE (critic, root-tier only):
  brief: plan-gate
  input: amended_plan from EPR-AMEND
  emits: new_findings: true|false   # true = structural issues remain; false = PASS
  on-findings (new_findings: true, $i < max):  → EPR-AMEND (iteration: $i + 1, critic findings injected)
  on-empty (new_findings: false):              → EPR-LOOP-DONE
  on-cap ($i >= max):                          → EPR-LOOP-CAPPED: escalate to operator; operator decides amend/abort

EPR-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: plan approved after $i rounds; advance to BODY entry node
```

### Default `--max`

**3**. If a plan cannot converge in 3 critic passes, the issue is likely scope, not plan
wording — escalate to the operator rather than extending the cap. Values > 3 require explicit
operator acknowledgement before the loop starts.

### Which composite

Generic **Pattern 6 — Loop-Until-Done**. Not a named composite. The closest named composite
would be CONVERGENCE-LOOP but the termination condition (critic gate) and the root-tier
restriction make this a distinct template.

### Anti-patterns

- **Using ENGINEER-PLAN-REFINE as the default plan path.** Single-pass `PLAN-AMEND` is
  the default. The loop is the exception, not the rule.
- **Teammate-conductors using this template.** Root-tier only. A teammate-conductor that
  authors a plan and loops on critic feedback is exceeding its dispatch tier. Surface
  `PLAN-AUTHORSHIP-REQUEST` instead.
- **Scope expansion during amendment.** Each amendment round targets ONLY the structural
  issues the critic identified. Expanding scope to "improve the plan overall" while fixing a
  structural issue is a process violation — the critic's next pass gates on the structural
  fix, not on general quality.
- **Running this loop without operator acknowledgement.** The operator chose
  `/shepherd:spawn` or `/shepherd:start`; they expect a plan, not a multi-round plan
  dialogue without consent. Surface the loop intent and cap before starting.

---

## shepherd / conductor loop — FOCUS-LOOP

### Intent

The orchestrator (root shepherd under `/shepherd:spawn`, solo conductor under
`/shepherd:start`) runs FOCUS-LOOP across an entire sprint to maintain drive continuity
through compaction, teammate events, and wave boundaries. Each iteration: Wake (read focus
record + rehydration digest), Act (dispatch / coordinate / advance Stage Graph cursor), Probe
(check whether CLOSE-FINALIZE has been reached). This is the runtime shape of the
`wake → act → probe → yield` coordinate cycle from `doctrines/coordinate-active-drive.md`.

This template is a **parameterization of the FOCUS-LOOP named composite** — not a new
template. All FOCUS-LOOP invariants from `references/workflow-templates.md §FOCUS-LOOP`
apply. This section shows how the orchestrator configures and enters the composite.

### Composite

**FOCUS-LOOP** (named composite, `references/workflow-templates.md §FOCUS-LOOP`). Do not
re-derive — reference the composite by name in the Stage Graph and parameterize via the
fields below.

### Parameterization

```yaml
FOCUS-LOOP-INIT (conductor):
  kind: focus
  max_iterations: 8                    # from shepherd.toml [focus].loop_max_default; justify > 10
  interval: <null | duration>          # null = in-session drive; set to e.g. '5m' for interval mode
  focus_record_fields:                 # written at three mandatory boundaries:
    - SEED-VERIFY: {objective, invariants}
    - each WAVE-GATE: {active_node, ready_set, obligations}
    - CLOSE-FINALIZE: {terminal_state}
  compaction_safety: precompact_snapshot_on   # shepherd.toml [compaction].precompact_snapshot must be "on"
```

### How the orchestrator enters the loop

**Solo `/shepherd:start`:**

```
1. Load SKILL.md and shepherd.toml.
2. shctx loop init --kind=focus --task="sprint-drive-<sprint_slug>" --max=8 --agent=orchestrator
   (emits loop_id)
3. Write initial focus record: shctx focus write --id=$loop_id --stage=SEED-VERIFY
4. Enter FOCUS-WAKE: read focus record + rehydration digest.
5. Proceed through FOCUS-ACT (dispatch / coordinate). At each WAVE-GATE, refresh focus record.
6. On CLOSE-FINALIZE: new_findings: false → FOCUS-LOOP-DONE.
```

**Root shepherd under `/shepherd:spawn`:**

```
1. Load shepherd.md profile (root tier).
2. Run INTRODUCTION: engineer → critic → PLAN-GATE → operator approval.
3. shctx loop init --kind=focus --task="sprint-drive-<sprint_slug>" --max=8 --agent=orchestrator
4. Write initial focus record at SEED-VERIFY.
5. TeamCreate: spawn teammate-conductors per the plan's lane structure.
6. Confirm liveness per doctrines/coordinate-active-drive.md §III.
7. Enter coordinate cycle: FOCUS-WAKE → FOCUS-ACT (drain mailbox, prune idle, advance cursor)
   → FOCUS-PROBE (liveness + drift sweep) → FOCUS-YIELD (to events, not operator).
8. On CLOSE-FINALIZE across all lanes: new_findings: false → FOCUS-LOOP-DONE.
```

### Termination predicate

`new_findings: false` when CLOSE-FINALIZE is reached (all lanes closed, close report
committed, sprint branch on origin). In `/shepherd:spawn` mode, this requires
`v_teammates_live == 0` and all WAVE-COMPLETE payloads materialized. In solo mode, this
requires the solo conductor's CLOSE-FINALIZE node.

### Default `--max`

**8** (from `shepherd.toml [focus].loop_max_default`). Values > 10 require critic sign-off
at PLAN-GATE per the FOCUS-LOOP definition. The FOCUS-LOOP also has a secondary hard ceiling
via the native `/loop` 7-day auto-expiry when `interval` is set.

### Anti-patterns

Refer to `references/workflow-templates.md §FOCUS-LOOP §Anti-patterns` for the full list.
Key highlights:

- **Running FOCUS-LOOP without a focus record.** The compaction rehydration path has nothing
  to inject without the `focus` table record. A bare loop counter is generic Pattern 6, not
  FOCUS-LOOP.
- **Nesting FOCUS-LOOP inside another loop.** Restructure as a single FOCUS-LOOP whose Act
  phase dispatches inner convergence work (each inner loop gets its own `loop_id`).
- **Root passive-wait between waves.** FOCUS-LOOP's Act phase drains all actionable state;
  yielding with undrained mailbox or idle teammates is the passive-wait bug per
  `doctrines/coordinate-active-drive.md §II`. The `coordinate_drive_guard.sh` Stop hook
  mechanically enforces this.

---

## See also

- `references/workflow-templates.md` — full named composite definitions (FOCUS-LOOP,
  CONVERGENCE-LOOP, WATCH-LOOP) with Stage Graph shapes, flock agent bindings, and anti-patterns
- `commands/loop.md` — `/shepherd:loop` command; `--agent` flag selects the iterator; all
  templates are invocable via this command
- `doctrines/loop-templates.md` — binding doctrine: principle, circuit-breaker invariants,
  cross-references; introduced v6.1.2
- `doctrines/workflow-patterns.md §Pattern 6` — selection decision tree; circuit-breaker
  invariants; enforcement surface
- `doctrines/workflow-patterns.md §Circuit-breaker invariants — Pattern 6` — `max_iterations`
  mandatory; structured `new_findings` field mandatory; cap-exceeded is HALT not silent exit
- `doctrines/coordinate-active-drive.md` — `wake → act → probe → yield` cycle (FOCUS-LOOP runtime)
- `doctrines/worker-patterns.md` — `@worker` patterns for loop body executor
- `doctrines/discovery-readonly.md` — `@discovery` read-only contract; report shape
- `doctrines/auditor-hypothesis-driven.md` — per-finding evidence contract for AUDITOR-REFINE
- `doctrines/dispatch-tier-separation.md` — root-tier-exclusive restriction on ENGINEER-PLAN-REFINE
- `doctrines/autonomous-sentinel.md` — binding doctrine for the AUTONOMOUS-SENTINEL template (v6.2.0); when it may fire (NEVER by default), the hard rails, the audit-trail requirement, and its relationship to SOAK-LOOP (superset) + hotfix-dispatch (the ACT vehicle)
- `doctrines/hotfix-dispatch.md` — the cardinality ladder the AUTONOMOUS-SENTINEL ACT stage dispatches through
- `doctrines/outcome-enforcement.md §Seam 4` — the detection-only post-close soak AUTONOMOUS-SENTINEL supersets
