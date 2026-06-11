# DISCOVERY-COMBO-WAVE — body-phase parallel research + audit template

> Added v6.0.8. Operator request: formalize the always-recurring composite of X
> auditors + Y discovery agents + optional workers that fires during BODY waves, so
> conductors stop improvising it as loose sequential sub-dispatches.

## What it is

A named graph node type for BODY-phase sprint work. Dispatches:

- **X `@auditor` lanes** (1–5, concern-split mandatory, read-only audit)
- **Y `@discovery` lanes** (1–5, scope-partitioned, read-only orientation/research)
- **Z `@worker` lanes** (0–2, bounded write ops only — omit entirely if not needed)

…as a **single parallel fan-out** — all lanes concurrent, NOT sequential
sub-dispatches, NOT one big prompt. N simultaneous agents → conductor aggregates
inline.

**Dispatch mechanism (v6.0.x).** DISCOVERY-COMBO-WAVE is a gate-free,
parallel-safe agent-fanout node, so it **compiles to a Dynamic Workflow** via
`shctx graph compile` — the primary execution path, identical to how
WAVE-IMPL / WAVE-AUDIT / CLOSE-SWARM compile (see
`doctrines/workflow-compile-down.md §V`, φ map). The compiler emits all X auditor
+ Y discovery + Z worker lanes as one bounded `Promise.all([...])` batch
(≤ `MAX_CONCURRENT`); the conductor reads the returned result object and runs
`BODY-AGGREGATE` inline (a §VI seam, never inside the workflow). The wave
satisfies the §IV faithfulness contract because every lane is independent
(scope-partitioned discoveries, concern-split auditors, non-waiting workers) and
auditor/discovery spawns are read-only by allowlist (§VII). Hand-rolled
in-context Agent dispatch is the fallback only when the workflow runtime is
unavailable.

```
DISCOVERY-COMBO-WAVE (single parallel batch)
├─ @auditor  — concern: A (code-quality | data-flow | dependency-topology | datastore-state | completeness)
├─ @auditor  — concern: B
├─ @auditor  — concern: N  (X total; max 5)
├─ @discovery — scope: domain-A
├─ @discovery — scope: domain-B
├─ @discovery — scope: domain-M  (Y total; max 5)
└─ @worker   — bounded op: <task>  (Z total; max 2; omit if zero)
     │
     └──► BODY-AGGREGATE (conductor inline) → outputs feed next wave or PLAN-GATE
```

## Why a named template

The core structure is invariant across every sprint that uses it. Formalizing it:

1. Prevents conductors from re-deriving the shape ad-hoc (and getting it wrong — e.g., dispatching agents sequentially, adding a redundant synthesizer `@worker`, or mixing discovery and auditor concerns into the same lane).
2. Makes the plan's Stage Graph legible: `DISCOVERY-COMBO-WAVE` is a single node name, not a prose description of an ad-hoc arrangement.
3. Binds the scaling table to the t-shirt size so engineers don't over- or under-dispatch.

## Canonical Stage Graph node

```yaml
DISCOVERY-COMBO-WAVE (mixed swarm):
  type: DISCOVERY-COMBO-WAVE       # the node TYPE the engineer authors; `shctx graph compile`
                                  # recognizes it (cmd_graph.sh is_compilable) and emits ONE
                                  # Promise.all batch (workflow-compile-down.md §V φ map) —
                                  # NOT sequential sub-dispatches. The compiled artifact is the
                                  # Dynamic Workflow; the node type stays DISCOVERY-COMBO-WAVE.
  agents:
    auditors: <X>                 # int 1–5; concern-split required; see scaling table
    discoveries: <Y>              # int 1–5; scope-partitioned; see scaling table
    workers: <Z>                  # int 0–2; bounded write ops only; omit key if Z=0
  parallel_with: null             # all lanes fire concurrently in one message
  concern_split: [<concern-A>, <concern-B>, ...]    # auditor concern assignments
  scope_partition: [<domain-A>, <domain-B>, ...]   # discovery scope assignments
  on-all-complete: → BODY-AGGREGATE (conductor inline)
  on-critical-finding (auditor severity >= CRITICAL):
    → HALT: surface finding + lane ID to root; await operator decision
  on-stall (any lane > timeout):
    → HALT: enumerate stalled lanes; do not aggregate partial results
```

## Scaling table

| T-shirt | Auditors (X) | Discoveries (Y) | Workers (Z) |
|---------|-------------|-----------------|-------------|
| XS | 1 | 1 | 0 |
| S  | 1–2 | 1–2 | 0–1 |
| M  | 2–3 | 2–3 | 0–1 |
| L  | 3–4 | 3–4 | 1–2 |
| XL | 4–5 | 4–5 | 2 |

Default cap across all lanes: `shepherd.toml [coder].max_parallel_lanes` (default 8).
Total lanes = X + Y + Z must not exceed this cap.

## Concern-split rules (auditor lanes)

Each auditor lane must declare a unique concern from the canonical set (per `flock.md §II @auditor`):

| Concern | Focus |
|---------|-------|
| `code-quality` | idiom, dead code, naming, deprecated markers |
| `data-flow` | money path, gate logic, signal correctness |
| `dependency-topology` | feature gating, package boundary, wrapper-grep |
| `datastore-state` | schema, RLS, migrations, query correctness |
| `completeness` | exit criteria, carry-forwards, GH triage, SUBTRACT |

Two auditors with the same concern in the same wave is redundant — re-partition or drop one.
For X = 1, the single auditor receives the full concern scope but must narrow hypothesis focus.

## Scope-partition rules (discovery lanes)

Each discovery lane must declare a non-overlapping domain. Domain split is sprint-specific but the engineer must:

1. State each domain explicitly in the plan — "discovery" without a scope is not a valid lane.
2. Ensure domains are non-overlapping: if two discovery agents read the same files independently, that wastes the dispatch. Partition by module, subsystem, external API, doc surface, or GH issue cluster.
3. Domains must be read-only research targets — never write, never audit. If the discovery agent needs to file findings, it uses `@auditor` instead.

## Worker lanes (optional)

Workers in DISCOVERY-COMBO-WAVE are strictly bounded write ops that:
- Cannot wait for auditor or discovery output to begin (they fire in parallel)
- Produce a discrete, verifiable artifact (file created, dep installed, schema migrated)
- Do NOT synthesize auditor or discovery reports

If a worker needs the wave's audit/discovery output before it can act → it is not a DISCOVERY-COMBO-WAVE worker. Move it to the next wave after BODY-AGGREGATE.

## BODY-AGGREGATE (conductor inline)

After all lanes complete, the conductor aggregates inline — no additional `@worker` dispatch:

```
## Discovery Wave Report — <sprint-slug>

### Audit findings
<per-concern: concern name, severity distribution, top findings>

### Research synthesis
<per-domain: domain name, key facts surfaced, open questions>

### Worker results (if any)
<per-worker: task, artifact path, verification status>

### Gate recommendation
PROCEED | HALT-FOR-REVIEW | HOTFIX-REQUIRED
<one-line rationale>
```

CRITICAL or HIGH audit findings with `HALT-FOR-REVIEW` or `HOTFIX-REQUIRED` gate recommendations block the next wave. Conductor surfaces to root; root decides.

## Distinction from INTRO-COMBO-WAVE

| | INTRO-COMBO-WAVE | DISCOVERY-COMBO-WAVE |
|--|---|---|
| **Phase** | INTRODUCTION (before MESH) | BODY (during sprint execution) |
| **Purpose** | Prior-state ingestion; feeds engineer's Phase-0 mesh | Research + audit during active work; feeds next implementation wave |
| **Workers allowed** | No | Yes (Z = 0–2) |
| **Feeds** | Engineer's `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` blocks | `BODY-AGGREGATE` → next wave or PLAN-GATE |
| **Trigger** | Always-on under `/shepherd:spawn` (except XS) | Declared explicitly in plan by engineer |
| **Defined in** | `doctrines/intro-combo-wave.md` | This file |

## When to declare DISCOVERY-COMBO-WAVE in the plan

The engineer declares it when a BODY wave needs simultaneous:
- Audit of code produced by a prior wave
- Research/orientation synthesis (API docs, GH issues, dep freshness, domain state)
- Optional bounded prep work that can start before the audit/research lands

Common triggers:
- Wave N implementation produced substantial output → Wave N+1 needs to audit it while also researching the next surface
- A PLAN-AMEND narrowed scope mid-sprint → a re-orientation wave is needed before the next coder wave
- Dependency upgrade path is unknown → discovery maps the upgrade while auditors check the current dep surface

## Anti-patterns

1. **Sequential dispatch.** Dispatching auditor-1, waiting for it, then dispatching discovery-1, then waiting — that is sequential, not DISCOVERY-COMBO-WAVE. All lanes must fire as one parallel batch — the compiled `Promise.all` (`shctx graph compile`), or, on runtime fallback, one Agent message. Authoring the fan-out ad hoc instead of compiling it is `workflow-compile-down.md` anti-pattern X.1.
2. **Synthesizer `@worker`.** Adding a `@worker` lane whose only job is to aggregate the auditor/discovery reports. The conductor aggregates inline. A synthesis worker is waste + an extra dispatch.
3. **Discovery lane writing.** A discovery agent that creates files, edits code, or installs deps is not discovery — it is a `@worker`. Reclassify.
4. **Auditor lane researching.** An auditor that spends its brief doing orientation synthesis rather than filing hypothesis-driven findings is not an auditor. Reclassify as `@discovery`.
5. **Unlimited workers.** Z > 2 is a DISPATCH-OVERFLOW. Workers in this wave are bounded ops — if you have 3+ distinct write tasks, split across multiple waves.
6. **Cross-lane context before BODY-AGGREGATE.** Auditor-1's findings must not be in discovery-2's brief (they fire in parallel — the brief is authored before dispatch). If one lane needs another's output, they are not parallel — restructure as sequential waves.

## See also

- `doctrines/intro-combo-wave.md` — sprint-open equivalent (INTRODUCTION phase)
- `doctrines/workflow-compile-down.md §V` — DISCOVERY-COMBO-WAVE is a φ-map compile target (gate-free mixed fan-out → `Promise.all`)
- `references/workflow-templates.md` — Pattern 2 (Fanout-And-Synthesize) is the underlying structure
- `doctrines/workflow-patterns.md` — Pattern 2 circuit-breaker invariants apply
- `doctrines/pattern-b-overlap.md` — Pattern 2 specialization: audit ∥ next implementation wave
- `flock.md §II` — per-agent brief contracts, concern-split rules, parallel-safety
- `doctrines/auditor-hypothesis-driven.md` — auditor brief discipline
- `doctrines/discovery-readonly.md` — discovery read-only contract
