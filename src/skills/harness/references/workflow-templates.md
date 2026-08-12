---
description: Compile-down model, native-coordination replacement matrix, the workflow self-check, and the six-pattern + composite template library. Use when authoring or reviewing a Stage Graph.
---

# Workflow templates — compile-down, self-check, and the pattern library

Every Stage Graph is built from the six patterns below, projected via
compile-down onto a compiled Dynamic Workflow — at ROOT, at a
teammate-`@conductor`, and at a self-contained `@engineer` alike, on
whichever construct's own `WORKFLOW-VEHICLE-PROBE`
(`skills/harness/SKILL.md §Tool presence`) finds the literal token
`Workflow` present in its visible tool list: a live Agent-Teams teammate
substrate, never a matter of tier (#263). The 6.3.9-era reading — that a
teammate-conductor projects the identical pattern shape via in-context
`Agent()` dispatch INSTEAD, because `Workflow` was read as unconditionally
denied inside any spawned role (#220, CC 2.1.212) — is RETIRED as the
standing instruction: that platform message is true only of an Agent-tool
subagent, never of a teammate on a live substrate. In-context `Agent()`
fan-out is the correct and ONLY vehicle on a subagent substrate — not a
downgrade to apologize for — and is filed with a `fanout_downgrade_reason`
for traceability either way (#263).
`skills/harness/SKILL.md §Workflow tool`/`§Tool presence` own the platform
facts (tool, ≤16/1000 caps, presence test); this file owns the compile
contract, the self-check, and the template vocabulary.

## Pattern library

| # | Pattern | Select when | Key flock binding |
|---|---------|-------------|-------------------|
| 1 | Classify-And-Act | Task nature unknown or spans multiple agent types | `@discovery` → branch edge → target agent |
| 2 | Fanout-And-Synthesize | Independent, parallel, non-overlapping units | parallel `@coder`/`@worker` → synthesizer |
| 3 | Adversarial Verification | High-stakes artifact needs independent challenge | producer → `@auditor` swarm / `@critic` |
| 4 | Generate-And-Filter | Multiple approaches; an absolute rubric selects | parallel generators → `@critic` gate |
| 5 | Tournament | Comparative ranking beats absolute scoring | N attempts → bracket of `@critic` pairs |
| 6 | Loop-Until-Done | Completion = absence of new findings | `@worker`/`@discovery` → check → back-edge |

Patterns compose (sequence or nest); the selection tree, legal/illegal
compositions, and circuit-breaker halt codes live in
`skills/shepherd/references/pipeline.md §Dispatch patterns` — this table is
the index only.

1. **Classify-And-Act.** `@discovery` emits a `classification` field; the
   conductor branches on it. `@worker` is NEVER a valid classifier; `@critic`
   and `@engineer` are gates and plan authors, not routers. A classification
   with no matching branch MUST surface to the operator — never guess.
2. **Fanout-And-Synthesize.** Fanout is bounded by `[coder].max_parallel_lanes`.
   Synthesis is all-or-nothing — never synthesize on partial completion (a
   HOTFIX path exists for that). `@discovery` MUST NOT fan out for write work.
3. **Adversarial Verification.** Verifier count scales with sprint size: XS/S
   → 1, M → 2–3, L/XL → 4–5; close-mode swarms need a minimum of 3. Concern
   split is mandatory — two verifiers on the same concern are redundant.
   Verifiers MUST NOT share intermediate results before filing; the producer
   MUST NOT also verify its own artifact in the same sprint.
4. **Generate-And-Filter.** Use only when the rubric is absolute (comparative
   ranking is Pattern 5). Generators MUST run identical briefs except the
   variant seed. The rubric MUST be declared in the seed before dispatch — a
   rubric assembled after seeing outputs is circular. Generators MUST run
   `parallel_with`, no cross-read — a generator anchored on a sibling's
   visible output is not independent. Implement only the winner, never all
   candidates.
5. **Tournament.** N MUST be ≥ 2; N = 2 degenerates to a single `@critic`
   pairwise — use Pattern 3 instead. Works cleanest at N = 4 or 8. Odd N
   requires a declared bye. Each judge sees only its own pair — no
   cross-match contamination. `@auditor` is NEVER a valid tournament judge.
6. **Loop-Until-Done.** `max_iterations` is mandatory — an unbounded loop is
   a framework violation. Default ceiling is 5; values above 5 require
   engineer justification in the plan. The iterator MUST emit a structured
   `new_findings: true|false` field every iteration; unstructured prose is
   not a valid termination signal. Cap-exceeded is a halt, never a silent
   stop.

**Composition index** — patterns combine along these axes; the selection
tree and legal/illegal compositions are
`skills/shepherd/references/pipeline.md §Dispatch patterns`:

| Composition | Worked example |
|---|---|
| Prefix routing | Classify-And-Act → any |
| Sequential pipeline | Generate-And-Filter → Fanout-And-Synthesize |
| Layered verification | Fanout-And-Synthesize → Adversarial Verification |
| Nested iteration | Loop-Until-Done containing Fanout-And-Synthesize |
| Competitive implementation | Tournament → Fanout-And-Synthesize |
| Routed competition | Classify-And-Act → Tournament |

## Named composites

`INTRO-COMBO-WAVE` and `DISCOVERY-COMBO-WAVE` are Pattern-2 specializations
defined in `skills/shepherd/references/pipeline.md §Combo waves` — not
restated here. `FOCUS-LOOP` (the orchestrator's own wake/act/probe/yield
cycle) is owned by `skills/motivation/SKILL.md §FOCUS-HEARTBEAT`; this file
only names it as the Pattern-6 instance driving a sprint end to end. The
two composites below are canonical here. A Stage Graph MUST cite a named
composite by name, never re-derive it from scratch.

| Name | Phase | Structure | Defined in |
|---|---|---|---|
| `INTRO-COMBO-WAVE` | INTRODUCTION | N `@discovery` + M `@auditor` | `skills/shepherd/references/pipeline.md §Combo waves` |
| `DISCOVERY-COMBO-WAVE` | BODY | X `@auditor` + Y `@discovery` + Z `@worker` | `skills/shepherd/references/pipeline.md §Combo waves` |
| `FOCUS-LOOP` | INTRODUCTION → CLOSE | orchestrator iterator; wake→act→probe | `skills/motivation/SKILL.md §FOCUS-HEARTBEAT` |
| `CONVERGENCE-LOOP` | BODY / CLOSE | `@coder`/`@worker` iterator; fix→gate-check | this file |
| `WATCH-LOOP` | BODY / POST-CLOSE | `@worker` probe iterator; wall-clock interval | this file |

### CONVERGENCE-LOOP — fix-until-gate-green

Generalizes the HOT-FIX rework cycle. Iterator: `@coder` (code) or `@worker`
(config/script). Each round emits `new_findings: true|false` where `true`
means the gate still fails. `max_iterations` default 5; values above 5
require engineer justification, above 10 require critic sign-off; no cap is
a preflight halt. The gate expression MUST be declared in the seed before
dispatch — assembling it after observing failures is a rubric violation.
CONVERGENCE-LOOP is Loop-OUTER: it follows Fanout-And-Synthesize (fanout
completes, then the loop drives to green) and never nests inside a Fanout
iteration body. Each nested loop instance (e.g. inside a FOCUS-LOOP Act
phase) MUST carry its own loop ID — never reuse the parent's. Known-finite
fix lists belong to Fanout-And-Synthesize + Adversarial Verification instead
— no loop needed when failing items are already enumerable.

### WATCH-LOOP — interval monitoring via native `/loop`

Bounded, wall-clock-scheduled monitoring (deployment, error stream, health
endpoint). Probe iterator: `@worker` only — `@discovery` is orientation-only,
NEVER a valid probe iterator. `interval` is mandatory; without it the
composite is indistinguishable from CONVERGENCE-LOOP. The native `/loop`
7-day auto-expiry is a non-overridable outer bound; `max_iterations` is an
independent inner cap — both MUST be declared. Each probe emits
`new_findings: true|false` where `true` means an anomaly. WATCH-LOOP is
always a leaf composite: no inner loop or fanout runs inside its probe
body, and it NEVER dispatches remediation — on anomaly it terminates and
surfaces to the operator. (A rails-gated, opt-in-twice-over exception that
DOES remediate is `skills/motivation/SKILL.md §Sentinel`.)

## Model pin (mandatory, #178)

Every `agent()` call in a hand-authored Workflow script MUST carry an explicit
`model:` or `agentType: "shepherd:<role>"` resolved from the single `[models]`
map (`skills/context/references/model-map.md`) — omitting BOTH silently
inherits the main-loop model instead (the platform's own stated default),
mechanically blocked by `hooks/scripts/workflow_model_guard.sh`
(`PreToolUse(Workflow)`, `WORKFLOW-MODEL-PIN-MISSING`, `skills/harness/
SKILL.md §Workflow tool`). This governs the native Workflow tool only — the
`shctx graph compile` output below runs its own `node <segment>.workflow.js`
execution path (a Bash invocation, not the Workflow tool), out of this
guard's reach; its faithfulness diff (§Compile-down model, below) is that
path's correctness mechanism instead. The compiler injects both
`agentType: "shepherd:<role>"` and the `[models]`-resolved `model:` into every
emitted spawn and the `--verify` **model_pin** invariant asserts it, so a
compiled segment is pin-safe by construction and would pass this guard even
though it never reaches it (#180).

## Compile-down model

Compile-down (`shctx graph compile`) is the execution path for gate-free
agent-fanout segments, run on a live Agent-Teams teammate substrate (#263)
— hand-rolled in-context dispatch is a subagent substrate's ONLY option,
confirmed when its OWN `WORKFLOW-VEHICLE-PROBE` (`skills/harness/SKILL.md
§Tool presence`) finds the tool genuinely absent — never a tier-based
fallback. Root compiles gate-free fanout to a Dynamic Workflow
(cross-lane/root-tier segments, `/shepherd:start`) via `shctx graph
compile --segment=<entry> --verify` → run the emitted script → `shctx
graph mark`. A teammate-conductor or self-contained engineer on a live
Agent-Teams substrate (`@conductor`/`@engineer` `tools:` frontmatter grants
the same access, #233) compiles its OWN lane's fanout to a Dynamic
Workflow the same way — `shctx graph compile --segment=<lane-entry>
--verify` where the lane maps to a compilable segment, or a hand-authored
script held to the same four faithfulness invariants (below) where it
doesn't — and calls `Workflow` directly. The pre-#263 reading, "a
teammate-conductor NEVER calls `Workflow`" (formerly #220, CC 2.1.212), is
RETIRED as the standing instruction: that denial is real only for an
Agent-tool subagent, never for a teammate on a live substrate; `--verify`
still validates the intended batch shape before dispatch either way, and
now gates a `Workflow` call rather than merely an in-context one on the
substrate where the tool actually works.

**The compile unit** is a maximal subgraph of agent-fanout nodes bounded by
(a) operator-approval boundaries (`PLAN-GATE`, `PAUSE` — segment boundaries,
never in-workflow nodes) and (b) conductor-inline filesystem/git nodes (no
direct FS/shell access from the script). The conductor stitches segments and
owns the seam.

**Faithfulness invariants** — for `S = compile(G_seg)`, every implementation
MUST guarantee:
1. **Soundness** — the script MUST NOT invent a dispatch; every spawned
   agent MUST map to a node in the segment's graph.
2. **Completeness** — every must-fire node MUST appear in `S`; the compiler
   MUST NOT skip or reorder a declared `parallel_with` pair.
3. **Determinism** — identical predicate evaluations MUST fix the same
   dispatch sequence.
4. **Pinned** (#180) — every emitted spawn MUST call `agent(prompt, opts)`
   (the real Workflow signature — prompt string first, opts object second) with
   an explicit `agentType: "shepherd:<role>"` AND a `[models]`-resolved `model:`
   pin. A bare `agent(prompt)` / opts-less spawn silently inherits the runtime's
   main-loop model — the #178 trap, one level removed. `--verify` asserts a pin
   count equal to the expected spawn count and rejects the legacy `agent(s)`
   shape.

These four invariants describe `compile(G_seg)`, the literal compiler
output at whichever tier runs it (#263). A teammate-conductor's or
engineer's in-context `Agent()` batch — now strictly the DOWNGRADE path,
taken only on a confirmed genuine `Workflow` absence — is held to the SAME
four properties by shape-equivalence (§Compile-down model) even though, in
that downgraded instance, it never runs the compiler and never calls
`Workflow`; `--verify` MAY check the intended batch against them before
dispatch.

Bounded dynamism is permitted (a HOTFIX batch's coder count read from a
prior agent's cluster analysis); unbounded dynamism is NEVER permitted. A
`@critic`/`@auditor` MAY diff `compile(G)` against the about-to-run script —
a mismatch is a compiler bug, not a plan defect.

**Node → script mapping.** `WAVE-IMPL`/`WAVE-AUDIT`/`CLOSE-SWARM` compile to
a bounded `Promise.all` (≤16 concurrent); combo waves compile to one bounded
`Promise.all` with read-only enforced by tool allowlist; `DISCOVERY`
(single or parallel, including plant-mode's 1–3 lanes) compiles to parallel
read-only spawns → a research bundle — plant-mode compiles to the SAME batch
shape; `WORKER-IO` (bounded, non-competing) compiles to a `Promise.all` of
worker agents; a sequential edge compiles to `await` + a predicate check;
`HOTFIX-DYNAMIC` compiles to a loop whose count is read from upstream
analysis. `SEED-VERIFY`, `CHAIN-REPAIR`, `PLAN-GATE`, `DEDUP-GATE`,
`WAVE-GATE`, `LANE-CLOSE`, `CANONICAL-TYPES-REFRESH`, `CLOSE-FINALIZE`,
`RELEASE`, `PAUSE*`, `RESUME-LANE`, and `HARD-STOP` are NEVER compiled — this
is the full seam-node set; none of the 12 may ever appear inside a compiled
script, only between segments at the conductor.

**Two compile targets, one source.** The GH-issue-tree compiler (dispatch
nodes → issues) and this Workflow-script compiler (agent-fanout nodes →
script steps) are two projections of one `shctx plan extract` source graph.
Neither compiler MAY invent or drop a node the other lacks.

**The seam.** Canonical state NEVER moves into the runtime: SQLite and git
stay conductor-owned; operator gates run between segments, never inside
one; all git/shell execution happens at the conductor. Runtime resume is
within-session only — exiting restarts the workflow fresh, so a fresh
session recompiles from the conductor's durable state, not the runtime's
progress.

**Negative-match rule.** A compiled segment MUST NOT contain a `PAUSE`,
`heartbeat`, or `PAUSE-FOR-DEPENDENCY` construct — `skills/context/tests/
test_graph_compile.sh` asserts this by negative match, the parity proof a
compiled dependency is realized by in-script ordering, never a
halt-and-resume dance.

**Anti-patterns.** Writing the orchestration script ad hoc instead of
`compile(G)` bypasses `PLAN-GATE` and breaks soundness. Compiling a whole
sprint into one workflow ignores the operator-gate and FS/shell seams.
Granting edit tools to an audit-type step defeats the read-only allowlist
invariant (`skills/harness/SKILL.md §Capability enforcement`) — enforce
read-only in the brief and tool allowlist, never in permission mode.
Treating runtime progress as canonical instead of SQLite/git repeats the
same mistake in reverse. Leads run at `ultracode` (`[spawn].lead_effort`) to
drive per-segment fan-out, but orchestration SHAPE stays the critic-gated
`G`'s — effort raises throughput, never the authority for what to dispatch;
a whole sprint compiled into one workflow (above) is forbidden regardless of
effort. Building a second graph reader for this projection instead of sharing
`shctx plan extract` (the #27 extractor) — one graph reader, not two.

## Native coordination

Three coordination axes, all native: a lead's fan-out ordering runs on
Dynamic Workflow `await` + bounded `Promise.all` on a live Agent-Teams
teammate substrate — root via `shctx graph compile`; a teammate-conductor
or self-contained engineer via its own compiled (or shape-equivalent
hand-authored) lane script, once its own probe confirms `Workflow`
present. This is a substrate fact, never a tier assignment (#263). The
pre-#263 reading — that a teammate-conductor's fan-out ordering ran on
in-context `Agent()` dispatch + `await`, the same shape, NEVER a compiled
script (formerly #220, CC 2.1.212) — is RETIRED as the standing
instruction: that reading held only for an Agent-tool subagent, where
in-context dispatch remains correct and the only option; teammate
state/cross-lane messaging still runs on Agent Teams `SendMessage`; the
worker primitive is still the subagent (`subagent_type: "shepherd:<role>"`)
— the closed flock, unchanged. Execution and teammate-state axes are
orthogonal and compose: a teammate-conductor's Agent Teams lane compiles
its OWN fanout to a Dynamic Workflow the same way root does, whenever its
substrate is live — in-context `Agent()` dispatch is the correct vehicle
only on a confirmed subagent substrate, recorded for traceability, never a
shortcut on a live one (#263); neither axis subsumes the other — canonical
binding `skills/shepherd/references/pipeline.md §Lane law`.

**Retired mechanics, replaced.** Three mechanics shepherd used to hand-roll
are retired, each replaced by a native primitive `skills/context/tests/
test_graph_compile.sh` demonstrates:
- **pause-for-dependency** — replaced by in-script `await` ordering on a
  graph edge (batch A runs, awaited, then batch B — no halt, no satellite);
  by Agent Teams `SendMessage` for a genuine cross-teammate hand-off; and by
  a finding or GH issue filed at close for out-of-sprint work — never a
  mid-lane pause.
- **heartbeat auto-relay** — a shared-file edit becomes one ordered step:
  the segment sequences the dependent edits via `await`, or the conductor
  owns the write at the seam. No relay round-trips, no broker.
- **idle-teammate pruning** — moot under out-of-context execution: a
  compiled workflow holds no idle teammates, since each spawn returns and
  exits. Team mode still runs existing Agent Teams cleanup at lane close.

**Subagent primitive confirmed.** Compiled workflows orchestrate subagents
only — every spawn is `agent(prompt, { agentType: "shepherd:<role>", model, ... })`
(the real Workflow signature; #180). The mandatory-`agentType` contract (refusal on
omission, `general-purpose`, or `Explore`) is unchanged: the compiler emits only
`shepherd:<role>` types + a `[models]`-resolved `model` pin; the tool allowlist keeps a
compiled audit step read-only even though the runtime auto-approves edits.

## Worked template — lane fan-out as a Dynamic Workflow

One WAVE-IMPL clique (Pattern 2, Fanout-And-Synthesize), compiled by a
teammate-conductor on a live Agent-Teams substrate (#263) — every
`agent()` call routed through the guarded wrapper (`skills/shepherd/
SKILL.md §Dispatch law`), both pins present:

```js
function flockAgent(prompt, opts = {}) {
  if (!opts.agentType?.startsWith("shepherd:"))
    throw new Error("DISPATCH-MISSING-SUBAGENT-TYPE: agentType must be shepherd:")
  if (!opts.model)
    throw new Error("DISPATCH-MODEL-UNPINNED: Workflow agent() bypasses [models]")
  return agent(prompt, opts)   // real signature: agent(prompt, opts)
}

const wave = parallel([
  flockAgent(brief("lane-3", "step-7"), { agentType: "shepherd:coder", model: "sonnet" }),
  flockAgent(brief("lane-3", "step-8"), { agentType: "shepherd:coder", model: "sonnet" }),
])
```

Dispatch this script via `Workflow`; record the returned `runId` + the
run's `journal.jsonl` absolute path at dispatch time, then poll
`${CLAUDE_PLUGIN_ROOT}/scripts/journal-status.sh <journal.jsonl>` as the canonical wave-return
signal (#213) — never a task notification, which can misroute to root
instead of the dispatching lane (`agents/conductor.md §Defensive poll`,
#224). On PASS, the lane's `WAVE-COMPLETE` carries `workflow_tool:
"present"`, `fanout: "workflow"`, `fanout_downgrade_reason: null`,
`workflow_run_ids: ["<runId>"]` — the EXPECTED values at this tier now,
graded correct, not a regression (`agents/conductor.md §WAVE-COMPLETE +
resume`).

## Workflow self-check

`skills/harness/SKILL.md §Tool presence` owns the platform fact (the
visible-tool-list probe, never `ToolSearch` — `WORKFLOW-VEHICLE-PROBE`,
#263). This section owns what a lead does with that fact when a Stage
Graph (or a lane's own sub-graph) is in play. **This self-check runs on
EVERY substrate, never gated by tier (#263):** root, a teammate-`@conductor`,
and a self-contained `@engineer` alike each probe their own visible tool
list before compiling their first gate-free segment, because the probe is
what tells them which substrate they are actually on. The 6.3.9-era reading
— that the check was ROOT-ONLY (formerly #220, CC 2.1.212) because
`Workflow` was unconditionally denied inside any spawned role, so a
teammate-conductor had nothing to check and nothing to compile and always
dispatched its lane's gate-free fanout in-context via `Agent()` — is
RETIRED as the standing instruction: that denial is real for an Agent-tool
subagent, never for a teammate on a live Agent-Teams substrate. A
teammate-conductor MUST NOT skip this check; skipping it and defaulting
straight to in-context `Agent()` dispatch WITHOUT confirming the substrate
is the exact `FANOUT-VEHICLE-DOWNGRADE` failure this section exists to
prevent — a finding only when the substrate the role skipped confirming
turns out to have been live.

**Record once per session, per lead.** On the first `/shepherd:*` turn (or
the first turn a teammate-conductor/engineer owns a lane), the lead records
its own `workflow_tool: present: true|false` (the `agent_fillin.workflow_tool`
boolean field) in orientation, and surfaces it in its own status line as
`workflow_tool=present|absent`. It does not change mid-session. A
teammate-conductor's `WAVE-COMPLETE` payload now carries its own probe
result and vehicle choice — `workflow_tool: "present"`, `fanout:
"workflow"`, `fanout_downgrade_reason: null` (non-null only when `fanout ==
"in-context"`), and `workflow_run_ids: [...]` for journal-status polling
(#213) — the SAME fields root's own payload carries; this supersedes the
pre-#263 payload that certified `workflow_tool: "absent"` /
`fanout: "in-context"` as EXPECTED for every teammate regardless of
substrate. Each lead's compile-vs-fallback state is tracked solely against
that lead's OWN segments/lane, and reflects that lead's OWN substrate.

**First-action placement.** Each lead performs its own check before
compiling any gate-free segment it owns — root before its first
cross-lane/root-tier segment, a teammate-conductor or engineer before its
first lane segment. The check is meaningless before that first compile
decision and never repeats after, per lead.

**Compiling is every lead's own benefit, not a tax.** When present,
compiling keeps intermediate agent results out of the conversation (they
live in script variables), runs agents in parallel while the lead stays
responsive, and stays mechanically faithful to the critic-gated graph.
Choosing the in-context fallback while the tool is present — i.e. while
confirmed on a live Agent-Teams substrate — is a wave-review finding
regardless of which lead does it (#263): `PRIMITIVE-INVERSION`
(`skills/shepherd/references/pipeline.md §Lane law`) at root, and
`FANOUT-VEHICLE-DOWNGRADE` (`skills/harness/SKILL.md §Tool presence`) at a
teammate-conductor or engineer — both reached only on confirmed runtime
failure with a recorded reason, never as a shortcut and never silently.
Choosing in-context on a CONFIRMED subagent substrate is not this
violation at all — it is the only vehicle that substrate has. The
pre-#263 reading — that a teammate-conductor's in-context `Agent()`
dispatch was NEVER this violation, at any time, because it was the
required mode regardless of `Workflow` presence (formerly #220) — is
RETIRED as a blanket claim; it survives only as the true, narrower claim
about a genuine subagent substrate.

**Degrade cleanly when genuinely absent.** Same flock, same briefs, same
graph — the lead walks it in-context instead of compiling, whenever its
own probe comes back absent, i.e. whenever it is actually running as an
Agent-tool subagent. Never retry the presence check, never report the
feature broken; record `present: false` and proceed, with
`fanout_downgrade_reason` set. Reaching for `ToolSearch` on the Workflow
tool instead of the visible tool list is the forbidden move
(`WORKFLOW-SELFCHECK-TOOLSEARCH`): `ToolSearch` resolves deferred tools
only, and `Workflow` is top-level, never a `ToolSearch` target by
construction, so a null result is a FALSE NEGATIVE BY CONSTRUCTION — it
establishes nothing, neither presence nor absence. Past failure: a session
`ToolSearch`'d "workflow," found nothing, and wrongly concluded the tool
was absent.

## See also

- `skills/shepherd/references/pipeline.md §Stage Graph` — node taxonomy and walk algorithm
- `skills/shepherd/references/pipeline.md §Lane law` — the axis ↔ primitive ↔ ontology-unit binding
- `skills/shepherd/references/pipeline.md §Combo waves` — INTRO-COMBO-WAVE, DISCOVERY-COMBO-WAVE
- `skills/shepherd/references/pipeline.md §Dispatch patterns` — selection tree, legal/illegal compositions, circuit-breaker halt codes
- `skills/motivation/SKILL.md §FOCUS-HEARTBEAT` — FOCUS-LOOP, the orchestrator's own drift guard
- `skills/motivation/SKILL.md §Loop discipline` — per-role loop invariants
- `skills/harness/references/loop-templates.md` — per-role loop invocations that specialize CONVERGENCE-LOOP / WATCH-LOOP
- `skills/harness/SKILL.md §Workflow tool` / `§Tool presence` / `§Capability enforcement` — platform facts this file builds on
