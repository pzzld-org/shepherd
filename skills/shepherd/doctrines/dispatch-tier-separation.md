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

**Self-contained engineer exception (v6.2.6, #172).** The Tier-1 "ephemeral
subagent" default has one carve-out: `@engineer`. In **classic** mode it is an
ephemeral subagent as drawn (root dispatches it; root also runs the discovery wave
and dispatches `@critic`). In **self-contained** mode ROOT spawns it as a **named
Tier-1 leader teammate** (native teammate-spawn, brief `mode: self-contained`); it
then runs its OWN read-only sub-flock — `@discovery` + intro-`@auditor` + its own
`@critic` — in its window, and root runs neither wave itself. This is the only
non-conductor role that may be a teammate, and it dispatches ONLY the read-only
trio (never `@coder`/`@worker`, never a nested `@engineer`). See §IV-bis.5 / .5-bis
and `doctrines/engineer-self-contained-plan.md`.

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

Consequences (enforced by §IV-bis): a **step** is a subagent (an ephemeral `Agent`/`Task`
dispatch); a **lane** is a teammate-conductor (a long-lived teammate spawned via the native
teammate-spawn referencing `subagent_type: shepherd:conductor`, addressed via `SendMessage`).
The discriminator is the spawn INTENT, not a `team_name` field (`team_name` is accepted but
ignored since v2.1.178). Spawning a lane uses **Agent Teams, never a Dynamic Workflow**, and a lane's gate-free
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

**Leader carve-outs (a flock role elevated to a leader runs its own read-only
sub-flock).** The "TIER 1 flock (any) → all ❌" row is the *standard* contract; two
roles are deliberately elevated to leaders and carry a bounded, read-only dispatch
grant defined in their profiles (mechanized by `hooks/tests/lint_agent_capabilities.sh`):

- **PARALLEL planter** MAY dispatch `@discovery` — the bounded plant-mode
  orientation wave (`agents/planter.md §Step 2-bis`).
- **Self-contained `@engineer`** (spawned by ROOT as a NAMED teammate, brief
  `mode: self-contained`) MAY dispatch its read-only sub-flock — `@discovery` +
  intro-mode `@auditor` (the INTRO-COMBO-WAVE it runs in-session) + its OWN
  `@critic` (its adversarial self-gate, brief-tagged `dispatcher:
  engineer-self-contained`) — and NOTHING else. NEVER `@coder`/`@worker` (no code
  in this phase), NEVER a nested `@engineer`, NEVER a teammate
  (`doctrines/engineer-self-contained-plan.md`). This is distinct from a teammate
  **conductor**, which still may not dispatch `@engineer`/`@critic` (below).

---

## III. Mode-detection for tier-2 conductors

The `agents/conductor.md` profile is adopted by both `/shepherd:start` (main
chat solo) and `/shepherd:spawn` teammates. The conductor must self-detect
which mode it's in to know whether `@engineer`/`@critic` dispatch is
permitted.

**Detection signals** (any one positive → teammate mode). The reliable signals are
the shepherd-controlled ones (#1–2); the env vars are documented-dead and must NOT
be load-bearing — this ordering matches `agents/conductor.md §mode-detection` and
`commands/spawn.md` Check 0:

1. The current session `cwd` is under a shepherd `.worktrees/` path (filesystem — reliable).
2. The boot prompt contains `INVOCATION-CONTEXT.dispatcher: teammate-conductor`, or `ROOT-SESSION-NAME: shepherd-root @ ...` (boot prompt — reliable).
3. `$CLAUDE_AGENT_TEAMMATE_NAME` / `$CLAUDE_PROJECT_SESSION_TYPE` set — **legacy env convention; reads EMPTY on the live platform (GH #93, 2026-05-29); do NOT rely on it.** Retained only as a cheap belt-and-suspenders check.

Any one positive signal → teammate mode; all negative → solo mode.

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

The shape of a subagent dispatch under shepherd discipline:

```
Agent({
  subagent_type: "shepherd:<role>",   // MANDATORY for every flock dispatch
  model: "<sonnet|opus>",              // per flock.md table
  prompt: "<task brief>"               // brief only — NOT the agent body
  // NO team_name — Agent/Task spawn subagents; `team_name` is accepted but
  // ignored (v2.1.178) and never makes a teammate.
})
```

Teammate-conductors (lanes) are NOT dispatched this way — root spawns them via the native
teammate-spawn (a natural-language instruction referencing the `shepherd:conductor` agent
type; no `TeamCreate` tool — removed v2.1.178), then talks to them via `SendMessage`. Any
deviation from these shapes is one of the violations below.

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
`shepherd:conductor` as a **teammate** — i.e. a native teammate-spawn referencing a
non-conductor agent type. *(#93 / v2.1.178: teammates spawn via the native teammate-spawn
referencing `shepherd:conductor`; there is no `TeamCreate` tool — removed v2.1.178 — and the
`team_name` parameter on `Agent`/`Task` is accepted but ignored, so it is NOT a usable
discriminator. The real distinction is the spawn INTENT: `shepherd:conductor` is spawned
as a teammate (a lane), and `shepherd:engineer` in self-contained mode is spawned as a
named leader teammate (§I "Self-contained engineer exception"); every other flock role is
an ephemeral subagent. The `team_name`-keyed
`dispatch_guard.sh` Check 3 is now vestigial defence-in-depth. The mechanical floor is the
`subagent_type` discipline, §IV-bis.1.)*

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

**Trigger:** a teammate-**conductor** attempts to dispatch `@engineer` or
`@critic`. (Detected at the agent boundary: engineer/critic profiles read
the `INVOCATION-CONTEXT.dispatcher` brief field on boot and halt with this
code if the dispatcher is a teammate-conductor.) Also enforced mechanically:
`hooks/scripts/dispatch_guard.sh` Check 4 blocks a teammate → `@engineer`
**unconditionally** (no nested/phantom engineer) and a teammate → `@critic`
**unless** the brief carries `dispatcher: engineer-self-contained`.

**Carve-out — the self-contained engineer's own critic self-gate is NOT this
violation.** A self-contained `@engineer` teammate dispatching its OWN `@critic`
(brief-tagged `dispatcher: engineer-self-contained`) is the adversarial gate every
leader runs on its output — permitted (`doctrines/engineer-self-contained-plan.md`).
The rule here is scoped to a teammate **conductor** re-authoring/re-gating a fixed
plan. A nested `@engineer` from any teammate is always forbidden.

**Refusal:** teammate-conductor surfaces `PLAN-AUTHORSHIP-REQUEST` (engineer needed)
or `PLAN-GATE-REQUEST` (critic needed) escalation to root. Root dispatches
engineer/critic directly and returns the result via resume reply.

### IV-bis.5-bis. `ENGINEER-TOPOLOGY-MISMATCH`

**Trigger:** `@engineer` is dispatched as an Agent/Task **subagent** while its
brief carries `mode: self-contained`. A self-contained engineer is a NAMED
teammate (native teammate-spawn), never a subagent — this is the "unnamed subagent
engineer" v6.2.5 failure. Mechanized: `dispatch_guard.sh` Check 4b.

**Refusal:** spawn the engineer as a teammate, OR drop `mode: self-contained` to
run classic (root runs discovery + `@critic`). Root never repairs by re-dispatch.

### IV-bis.5-ter. `ENGINEER-SUBFLOCK-VIOLATION`

**Trigger:** a dispatch tagged `dispatcher: engineer-self-contained` (the
self-contained engineer's leader signature on every sub-flock dispatch) targets a
`subagent_type` outside the read-only trio `{shepherd:discovery, shepherd:auditor,
shepherd:critic}` — e.g. `@coder`/`@worker` (this phase touches no code) or a nested
`@engineer`. Mechanized: `dispatch_guard.sh` Check 4c. A conductor lane carries no
such marker, so its legitimate `@coder`/`@worker` fan-out is unaffected.

**Refusal:** the engineer files a plan step for the conductor's coder/worker wave
instead of dispatching a writer itself. Its sub-flock is closed at the three
read-only roles.

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
| Non-conductor agent type spawned as a teammate (`subagent_type ≠ shepherd:conductor`) | `DISPATCH-TEAMMATE-TYPE-MISMATCH` | root |
| `subagent_type` outside closed-flock-six (or shepherd:conductor) | `DISPATCH-OFF-FLOCK` | root + conductor |
| Teammate tries to construct `team_name` | `TEAMMATE-NESTING-ATTEMPT` | teammate-conductor |
| Teammate-conductor dispatches `@engineer`/`@critic` (not the engineer's own tagged critic self-gate) | `WRONG-TIER-DISPATCH` | `dispatch_guard.sh` Check 4 + engineer/critic on receipt |
| Self-contained `@engineer` dispatched as a subagent (must be a named teammate) | `ENGINEER-TOPOLOGY-MISMATCH` | `dispatch_guard.sh` Check 4b |
| Engineer sub-flock (marked) dispatch to a non-read-only role (`@coder`/`@worker`/nested `@engineer`) | `ENGINEER-SUBFLOCK-VIOLATION` | `dispatch_guard.sh` Check 4c |
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

- `@engineer` (Opus) — plan authorship. Not dispatchable by a teammate-conductor under spawn; dispatched by root as a subagent (classic) OR spawned by root as a self-contained leader teammate (§I exception, #172).
- `@critic` (Sonnet) — adversarial gate. Dispatched by root (classic) OR by the self-contained `@engineer` teammate against its own plan (tagged `dispatcher: engineer-self-contained`); never by a teammate-conductor re-gating a fixed plan.
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

Tier separation fixes both. Engineer + critic happen ONCE per sprint — at root in
classic mode, or in the self-contained engineer's own teammate window (§I exception,
#172), never re-run by a teammate-conductor. Teammate context stays narrow (own wave
only). Root absorbs the artifact-materialization cost and gets the cross-teammate
view critic needs (in classic mode; a self-contained plan arrives pre-critiqued with
a hash-tied proof).

3. **Permissive-fallback dispatch slippage (v5.1.9 → v6.0.0 regression).**
   Three consecutive `/shepherd:spawn` runs (a downstream Rust service,
   2026-05-25..27) failed in concurrent failure modes: root treated spawn
   like start (did body work directly instead of fanning out conductors);
   when teammates were spawned, lane-**coders** were stood up as teammates
   (a non-conductor agent type spawned as a teammate — see #93 / v2.1.178 for the
   verified teammate-spawn path: the native teammate-spawn referencing
   `shepherd:conductor`, no `TeamCreate` tool) with no
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
