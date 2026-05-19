# Dispatch tier separation (v5.1.6+)

The shepherd flock now operates on a **three-tier dispatch hierarchy** when
`/shepherd:spawn` is active. Each tier has bounded dispatch authority. This
doctrine is the binding matrix.

The motivation: context preservation + cost discipline. The expensive lanes
(`@engineer` Opus, `@critic` aggregating cross-teammate findings, artifact
materialization) live at the root tier where they happen once per sprint.
Teammate-conductors stay cheap (Sonnet), narrow (their wave only), and
write-free (no artifact materialization). The flock — `@coder` /
`@auditor` / `@worker` / `@discovery` — is the dispatch surface every
teammate-conductor owns.

---

## I. The three tiers

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 3 (root)                                                  │
│  agents/shepherd.md          model: inherit                     │
│  Adopted by: main chat under /shepherd:spawn                    │
│  Dispatches: @engineer, @critic, @auditor (close-swarm),        │
│              @discovery (intro/close), @worker (root ledger)    │
│  Never dispatches: @coder (teammate territory)                  │
└─────────────────────────────────────────────────────────────────┘
                              ▲ spawns N
                              │
┌─────────────────────────────────────────────────────────────────┐
│  TIER 2 (meta)                                                  │
│  agents/conductor.md         model: sonnet                      │
│  Adopted by:                                                    │
│    - main chat under /shepherd:start (solo mode → unchanged)    │
│    - teammate session under /shepherd:spawn (teammate mode)     │
│  Dispatches (SOLO):    all six flock                            │
│  Dispatches (TEAMMATE): @coder, @auditor (wave), @worker,       │
│                         @discovery — NOT @engineer or @critic   │
└─────────────────────────────────────────────────────────────────┘
                              ▲ dispatches
                              │
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1 (flock — closed at six)                                 │
│  agents/coder.md      agents/auditor.md   agents/worker.md       │
│  agents/discovery.md  agents/engineer.md  agents/critic.md       │
│  Ephemeral subagents; system prompt is the agent file body      │
└─────────────────────────────────────────────────────────────────┘

PARALLEL META BRANCH (not a tier — sibling to conductor at meta level):
┌─────────────────────────────────────────────────────────────────┐
│  agents/planter.md           model: opus[1m]                    │
│  Adopted by: main chat under /shepherd:plant; ALSO loaded by    │
│              shepherd profile mid-spawn for delegated seed work │
│  Dispatches: none — meta-orchestrator only                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## II. Dispatch matrix

| From → To | `@engineer` | `@critic` | `@coder` | `@auditor` | `@worker` | `@discovery` | Another teammate |
|---|---|---|---|---|---|---|---|
| **TIER 3 root (shepherd)** | ✅ | ✅ | ❌ (teammate owns) | ✅ (close + intro swarm) | ✅ (root ledger) | ✅ (intro/close) | ✅ (spawn) |
| **TIER 2 conductor (solo)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no nested spawn) |
| **TIER 2 conductor (teammate)** | ❌ → escalate `PLAN-AUTHORSHIP-REQUEST` | ❌ → escalate `PLAN-GATE-REQUEST` | ✅ (wave) | ✅ (wave) | ✅ (wave) | ✅ (wave) | ❌ (no nested spawn) |
| **TIER 1 flock (any)** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **PARALLEL planter** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

Legend:
- ✅ — dispatch permitted under standard contract
- ❌ — dispatch forbidden; violation is a process error
- ❌ → escalate — dispatch forbidden BUT the tier-2 teammate has a defined
  escalation path back to root (the `PLAN-AUTHORSHIP-REQUEST` /
  `PLAN-GATE-REQUEST` patterns)

---

## III. Mode-detection for tier-2 conductors

The `agents/conductor.md` profile is adopted by both `/shepherd:start` (main
chat solo) and `/shepherd:spawn` teammates. The conductor must self-detect
which mode it's in to know whether `@engineer`/`@critic` dispatch is
permitted.

**Detection signals** (any one of these triggers teammate mode):

1. `$CLAUDE_AGENT_TEAMMATE_NAME` environment variable is set.
2. `$CLAUDE_PROJECT_SESSION_TYPE == "teammate"` (or equivalent platform flag).
3. The boot prompt contains `INVOCATION-CONTEXT.dispatcher: teammate-conductor`.
4. The boot prompt contains `ROOT-SESSION-NAME: shepherd-root @ ...`.

Any one positive signal → teammate mode; all four negative → solo mode.

Conductor MUST verify mode at session-start (Step 0 of mandatory protocol)
and surface it explicitly in the orientation:

```
[SESSION-START] branch={sprint_branch} | mode={solo|teammate} | seed={path}
```

---

## IV. The escalation patterns (teammate → root)

When a teammate conductor needs work that's root-tier-exclusive, it returns
a structured escalation payload via `SendMessage(to: lead, ...)`. The
payload schema is defined in `doctrines/spawn-escalation.md §III`. The
specific halt codes for tier-separation escalations:

### `PLAN-AUTHORSHIP-REQUEST`

When triggered: the teammate's existing plan is insufficient or stale; a
fresh `@engineer` pass is required. (Examples: SEED-DRIFT — substantive,
mid-sprint operator amendment changes a coder lane scope, dependency
rotation invalidates a lane.)

Payload:
```yaml
halt_code: PLAN-AUTHORSHIP-REQUEST
phase: <current phase>
blocking: true
context_files:
  - {paths.plans}/<sprint_slug>.plan.md
  - {paths.plans}/<sprint_slug>.seed.md
amendment_summary: |
  <one-paragraph description of what changed and why a re-plan is needed>
```

Root response: dispatch `@engineer` with the amendment context, materialize
revised plan, return resume reply with new plan path.

### `PLAN-GATE-REQUEST`

When triggered: a revised plan or a substantive design question needs
`@critic` review before the teammate can resume.

Payload:
```yaml
halt_code: PLAN-GATE-REQUEST
phase: <current phase>
blocking: true
context_files:
  - {paths.plans}/<sprint_slug>.plan.md (or the revised plan)
gate_question: |
  <specific question the critic must answer>
```

Root response: dispatch `@critic`, materialize verdict, return resume reply
with verdict.

### `WRONG-TIER-DISPATCH`

When triggered: this is NOT a teammate-initiated escalation. It's the halt
code an `@engineer` or `@critic` agent surfaces when it detects it was
dispatched by a teammate-conductor (via the `[INVOCATION-CONTEXT]` brief
field). This is a process violation by the teammate.

Root response: do NOT auto-resume. Surface to operator with the failing
teammate's identity. Patch the teammate's brief discipline OR end the
teammate session if it cannot reliably observe the tier-separation rule.

---

## V. The flock contract (unchanged)

The closed-at-six flock contract from prior versions remains binding:

- `@engineer` (Opus) — plan authorship. Now root-tier-exclusive under spawn.
- `@critic` (Sonnet) — adversarial gate. Now root-tier-exclusive under spawn.
- `@coder` (Sonnet) — implementation. Dispatched by ANY tier-2 conductor.
- `@auditor` (Sonnet) — read-only review. Dispatched by tier-3 (close +
  intro swarm) or tier-2 teammate (wave-mid audit) or tier-2 solo.
- `@worker` (Sonnet) — bounded execution. Dispatched at any tier.
- `@discovery` (Sonnet) — read-only orientation. Dispatched at any tier.

Specialist agents (per `doctrines/specialist-dispatch.md`) follow the same
tier rules: a teammate-conductor that needs a specialist for plan-grade
work must surface `PLAN-AUTHORSHIP-REQUEST` first.

---

## VI. Why this discipline matters

Two failure modes from v5.1.5 motivated this doctrine:

1. **Teammate-conductor engineer dispatch.** A teammate ran `@engineer` mid-
   sprint to re-plan its own wave. This produced two parallel plans (the
   root's and the teammate's), divergent acceptance criteria, and a sprint-
   close audit dispute. Filed as GH issue: failure-mode(v5.1.5).

2. **Teammate context pollution from artifact writes.** Teammate-conductors
   that materialized close reports + handoffs in-session accumulated context
   that contaminated their subsequent wave dispatches. The fresh-context-
   per-wave guarantee of `--auto` was being eroded.

Tier separation fixes both. Engineer + critic happen ONCE per sprint at root.
Teammate context stays narrow (own wave only). Root absorbs the artifact-
materialization cost and gets the cross-teammate view critic needs.

---

## VII. Solo-mode exemption

`/shepherd:start` in main chat is solo mode. The conductor profile retains
its full dispatch surface (engineer + critic + four-lane flock). Tier
separation does NOT apply — there's only one conductor, no teammates, and
no risk of cross-conductor divergence.

This is the backward-compatibility path. Existing solo workflows are
unaffected. Tier separation activates only under `/shepherd:spawn`.

---

## VIII. See also

- `doctrines/root-shepherd-orchestration.md` — root-tier responsibilities + modes
- `doctrines/scope-scale-workload.md` — `--scope` flag composition with tiers
- `doctrines/spawn-escalation.md` — escalation channel mechanics
- `agents/shepherd.md` — root profile
- `agents/conductor.md §Conductor modes` — solo vs teammate behavior
- `agents/engineer.md §Hard prohibitions` — WRONG-TIER-DISPATCH halt code
- `agents/critic.md §Hard prohibitions` — WRONG-TIER-DISPATCH halt code
