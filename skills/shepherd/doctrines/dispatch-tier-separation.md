# Dispatch tier separation (v5.1.6+; enforcement hardened v6.0.0)

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

## I-bis. Tier ↔ ontology unit ↔ primitive (v6.0.2, #88 / #89)

The three tiers map **one-to-one** onto shepherd's planning ontology and onto the
Claude-native primitives. This is the ontological half of the binding; the canonical
table is `doctrines/primitive-axis-binding.md §I, §IV`.

| Ontology unit | Tier | Native primitive |
|---|---|---|
| **step** (a unit of work within a wave; a plan is N waves × X steps) | Tier 1 (flock) | **subagent** (`subagent_type: "shepherd:<role>"`) |
| **lane** (a vertical slice ACROSS waves; spawn-only, post-plan) | Tier 2 (teammate-conductor) | **Agent Teams** teammate |
| **wave** (a sequential gated stage) | — (seam, not a tier) | conductor-inline gate |

Consequences (enforced by §IV-bis): a **step** is a subagent (`team_name` UNSET); a
**lane** is a teammate-conductor (`team_name` SET, `subagent_type: shepherd:conductor`);
spawning a lane uses **Agent Teams, never a Dynamic Workflow**, and a lane's gate-free
step fan-out **compiles to a Dynamic Workflow, never hand-rolled dispatch**
(`primitive-axis-binding.md §III`). The engineer authors `waves × steps` with **no lane
concept**; lanes are the post-plan spawn projection, and **never nest inside a wave**.

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

## IV-bis. Forbidden dispatch matrix (binding refusal contract; v6.0.0+)

The dispatch matrix in §II describes what each tier MAY do. This section
enumerates the specific Agent-call constructions that MUST be refused on
sight, with their halt codes. Every cited file (`agents/shepherd.md`,
`agents/conductor.md`, `skills/shepherd/flock.md`, `skills/shepherd/SKILL.md`,
`commands/spawn.md`) inlines a one-line cite to this section instead of
re-stating the rules.

The shape of an Agent call under shepherd discipline:

```
Agent({
  subagent_type: "shepherd:<role>",   // MANDATORY for every flock dispatch
  model: "<sonnet|opus>",              // per flock.md table
  prompt: "<task brief>",              // brief only — NOT the agent body
  team_name: <UNSET unless root-level teammate spawn under /shepherd:spawn>
})
```

Any deviation from this shape is one of the violations below.

### IV-bis.1. `DISPATCH-MISSING-SUBAGENT-TYPE`

**Trigger:** any flock dispatch (`@coder`, `@auditor`, `@worker`, `@discovery`,
`@engineer`, `@critic`) that omits `subagent_type`, defaults to
`general-purpose`, or sets `subagent_type` to `Explore` / `Chat` /
`general-purpose` / any other non-shepherd identifier.

**Refusal:** the dispatcher (root in INTRO/CLOSE; teammate-conductor in
BODY) MUST refuse to fire the Agent call. Surface to operator (root) or
escalate (`SendMessage(to: lead, halt_code: DISPATCH-MISSING-SUBAGENT-TYPE,
blocking: true)`, teammate).

**Why:** v5.1.5 and earlier allowed prompt-injected dispatch with
`subagent_type` omitted. v5.1.9 switched to the registry-loaded path. In
between, the permissive fallback let conductors silently degrade to
`general-purpose` agents — which break every framework discipline
(brief contract, dedup-gate, halt codes, model pinning). This refusal is
the load-bearing replacement for the prior implicit enforcement.

### IV-bis.2. `DISPATCH-TEAMMATE-TYPE-MISMATCH`

**Trigger:** a dispatch attempts to stand up a flock role OTHER than
`shepherd:conductor` as a **teammate** — a `team_name`-bearing dispatch (or, on the
live platform, a `TeamCreate` referencing a non-conductor agent type) whose
`subagent_type != "shepherd:conductor"`. *(#93: there is no `team_name` parameter on
`Agent`/`Task` — those spawn subagents; teammates spawn via the `TeamCreate` family
referencing `shepherd:conductor`. The real discriminator is the TOOL FAMILY, so the
`team_name` check is **defence-in-depth** — `dispatch_guard.sh` Check 3 — layered over
the platform's own behavior. The mechanical floor is the `subagent_type` discipline,
§IV-bis.1.)*

**Refusal:** root MUST refuse. Teammate-spawning (a lane) is conductor-only. A coder
(etc.) is an ephemeral **subagent** dispatched BY a conductor, never spawned AS a
teammate.

**Why:** a downstream Rust service (FL03/shepherd #65, 2026-05-26) — root
dispatched 4 coder teammates instead of conductor teammates. Work landed
without conductor-level gates, error recovery, or proper iteration.
Architecturally: a teammate session inherits the lead's permission mode
and runs with the SendMessage channel; the in-process platform constraint
(Anthropic GH #31977) currently denies the Agent tool to in-process
teammates. A coder teammate has no flock to coordinate AND cannot be
substituted for a conductor.

### IV-bis.3. `DISPATCH-OFF-FLOCK`

**Trigger:** an Agent call sets `subagent_type` to any value outside the
closed-flock-six (`shepherd:engineer`, `shepherd:critic`, `shepherd:coder`,
`shepherd:auditor`, `shepherd:worker`, `shepherd:discovery`) and outside
`shepherd:conductor` (for teammate spawns from root). Specialist
exceptions per `doctrines/specialist-dispatch.md` clear this only when
they pass the DISPATCH DECISION TREE §Q1–Q4.

**Refusal:** the dispatcher MUST refuse. The flock is closed at six. Plan
authorship, critic gating, close-time audit grading, and code
implementation are NEVER substitutable.

### IV-bis.4. `TEAMMATE-NESTING-ATTEMPT`

**Trigger:** a teammate-conductor (TEAMMATE mode per §III) constructs any
Agent call with `team_name` set, OR invokes `/shepherd:spawn` from within
its session, OR otherwise attempts to spawn its own teammate-tier.

**Refusal:** the teammate MUST refuse and `SendMessage(to: lead, halt_code:
TEAMMATE-NESTING-ATTEMPT, blocking: true)` to root. Platform forbids
nested teams (D-API §12); shepherd discipline forbids it doctrinally.

### IV-bis.5. `WRONG-TIER-DISPATCH`

**Trigger:** a teammate-conductor attempts to dispatch `@engineer` or
`@critic`. (Detected at the agent boundary: engineer/critic profiles read
the `INVOCATION-CONTEXT.dispatcher` brief field on boot and halt with this
code if the dispatcher is a teammate.)

**Refusal:** teammate surfaces `PLAN-AUTHORSHIP-REQUEST` (engineer needed)
or `PLAN-GATE-REQUEST` (critic needed) escalation to root. Root dispatches
engineer/critic directly and returns the result via resume reply.

### IV-bis.6. `MODE-MISUSE`

**Trigger:** SOLO-mode conductor (under `/shepherd:start` in main chat)
attempts to spawn a teammate. OR: TEAMMATE-mode conductor attempts a
SOLO-mode operation (artifact write, git commit, operator direct-message)
that the §III matrix forbids.

**Refusal:** halt and surface. Mode detection is mandatory at Step 0 of
the conductor protocol per `agents/conductor.md §Conductor modes`. If
mode-detection is ambiguous (some signals positive, others negative),
halt with `MODE-DETECTION-AMBIGUOUS` (separate code, same surface
discipline).

### IV-bis.7. Quick-reference table

| Violation | Halt code | Refused by |
|---|---|---|
| Flock dispatch missing `subagent_type` | `DISPATCH-MISSING-SUBAGENT-TYPE` | root + conductor |
| `team_name` set with `subagent_type ≠ shepherd:conductor` | `DISPATCH-TEAMMATE-TYPE-MISMATCH` | root |
| `subagent_type` outside closed-flock-six (or shepherd:conductor) | `DISPATCH-OFF-FLOCK` | root + conductor |
| Teammate tries to construct `team_name` | `TEAMMATE-NESTING-ATTEMPT` | teammate-conductor |
| Teammate dispatches `@engineer`/`@critic` | `WRONG-TIER-DISPATCH` | engineer/critic on receipt |
| SOLO mode spawning OR TEAMMATE mode running SOLO ops | `MODE-MISUSE` | conductor |
| Mode-detection signals contradict | `MODE-DETECTION-AMBIGUOUS` | conductor |
| Teammate runs git rebase/merge/push/worktree | `TEAMMATE-GIT-WRITE` | teammate-conductor |

These halt codes are **terminal for the offending dispatch**. Root does
NOT auto-resume on `WRONG-TIER-DISPATCH` or `TEAMMATE-NESTING-ATTEMPT` —
the teammate brief is malformed and needs operator review per
`agents/shepherd.md §Halt codes (root-side)`.

### IV-bis.8. TEAMMATE-GIT-WRITE — teammate git custody (v6.0.3 — #99)

A teammate-conductor's git authority is bounded to commits on its OWN worktree branch.
It MUST NOT run `git rebase`, `git merge`, `git push`, or `git worktree` (add/remove) —
those are root-tier operations. Root rebases every lane onto the sprint branch at each
wave-gate; a teammate never rebases itself, even when behind. On reaching for any such
command: STOP and `SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)`.
Cross-ref: `agents/conductor.md §Hard prohibitions #19` + `§Side-effect boundary`.
Propagates the halt code already defined in `commands/spawn.md`.

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

Three failure modes have motivated this doctrine. The first two come from
v5.1.5 (motivated the original tier separation); the third (motivated the
v6.0.0 hard-refusal hardening) comes from a downstream Rust service.

1. **Teammate-conductor engineer dispatch.** A teammate ran `@engineer` mid-
   sprint to re-plan its own wave. This produced two parallel plans (the
   root's and the teammate's), divergent acceptance criteria, and a sprint-
   close audit dispute. Filed as GH issue: failure-mode(v5.1.5).

2. **Teammate context pollution from artifact writes.** Teammate-conductors
   that materialized close reports + handoffs in-session accumulated context
   that contaminated their subsequent wave dispatches. The fresh-context-
   per-wave property (now realized via **lane refresh** — recycling an idle
   lane's teammate at a wave boundary, `primitive-axis-binding.md §II.1`) was
   being eroded.

Tier separation fixes both. Engineer + critic happen ONCE per sprint at root.
Teammate context stays narrow (own wave only). Root absorbs the artifact-
materialization cost and gets the cross-teammate view critic needs.

3. **Permissive-fallback dispatch slippage (v5.1.9 → v6.0.0 regression).**
   Three consecutive `/shepherd:spawn` runs (a downstream Rust service,
   2026-05-25..27) failed in concurrent failure modes: root treated spawn
   like start (did body work directly instead of fanning out conductors);
   when teammates were spawned, lane-**coders** were stood up as teammates
   (a non-conductor, `team_name`-bearing dispatch — see #93 for the verified
   teammate-spawn path: `TeamCreate` referencing `shepherd:conductor`) with no
   conductor coordination; `general-purpose` agents were dispatched
   because `subagent_type` was sometimes omitted entirely. The framework
   describing the correct shape was not enough; the enforcement language
   had been weakened in v5.1.9's dispatch-procedure rewrite without an
   explicit-refusal replacement. §IV-bis above closes that gap by naming
   the violations and pairing each with a halt code that the dispatcher
   self-checks. Filed as FL03/shepherd #65 (teammate type mismatch) and
   #66 (general process violations).

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

- `doctrines/primitive-axis-binding.md` — canonical axis ↔ primitive ↔ unit binding; §I-bis above is its tier-mapping projection (v6.0.2, #88 / #89)
- `doctrines/root-shepherd-orchestration.md` — root-tier responsibilities + modes
- `doctrines/scope-scale-workload.md` — `--scope` flag composition with tiers
- `doctrines/spawn-escalation.md` — escalation channel mechanics
- `agents/shepherd.md` — root profile
- `agents/conductor.md §Conductor modes` — solo vs teammate behavior
- `agents/engineer.md §Hard prohibitions` — WRONG-TIER-DISPATCH halt code
- `doctrines/workflow-compile-down.md` — compiled workflow steps must honor the mandatory-`subagent_type` dispatch contract this doctrine defines
- `agents/critic.md §Hard prohibitions` — WRONG-TIER-DISPATCH halt code
