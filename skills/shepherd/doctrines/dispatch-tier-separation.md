# Dispatch tier separation (v5.1.6+; enforcement hardened v6.0.0)

Under `/shepherd:spawn` the flock runs a **three-tier dispatch hierarchy**
with bounded dispatch authority per tier. This doctrine is the binding
matrix.

Why: context preservation + cost discipline. Expensive lanes (`@engineer`
Opus, `@critic` cross-teammate aggregation, artifact writes) live at root,
once per sprint. Teammate-conductors stay cheap, narrow (own wave only),
write-free. The flock (`@coder`/`@auditor`/`@worker`/`@discovery`) is the
dispatch surface every teammate-conductor owns.

---

## I. The three tiers

```
┌──────────────────────────────────────────────────────┐
│  TIER 3 (root) — agents/shepherd.md    model: inherit │
│  Adopted by main chat under /shepherd:spawn           │
│  Dispatches: @engineer, @critic, @auditor (close),    │
│              @discovery (intro/close), @worker        │
│  Never dispatches: @coder (teammate territory)        │
└──────────────────────────────────────────────────────┘
                    ▲ spawns N
┌──────────────────────────────────────────────────────┐
│  TIER 2 (meta) — agents/conductor.md   model: sonnet  │
│  Adopted by: main chat /shepherd:start (solo) OR a    │
│              teammate session under /shepherd:spawn   │
│  Dispatches (SOLO): all six flock                     │
│  Dispatches (TEAMMATE): @coder, @auditor, @worker,    │
│              @discovery — NOT @engineer or @critic    │
└──────────────────────────────────────────────────────┘
                    ▲ dispatches
┌──────────────────────────────────────────────────────┐
│  TIER 1 (flock — closed at six)                       │
│  coder / auditor / worker / discovery / engineer /    │
│  critic — ephemeral subagents; agent file IS the      │
│  system prompt                                        │
└──────────────────────────────────────────────────────┘

PARALLEL META BRANCH (sibling to conductor, not a tier):
┌──────────────────────────────────────────────────────┐
│  agents/planter.md   model: opus[1m]                  │
│  Adopted by /shepherd:plant; also loaded mid-spawn    │
│  for delegated seed work                              │
│  Dispatches: none — meta-orchestrator only            │
└──────────────────────────────────────────────────────┘
```

**Self-contained engineer exception (v6.2.6, #172).** One carve-out to the
Tier-1 default: `@engineer`. **Classic** mode = ephemeral subagent (root
dispatches it, runs discovery + `@critic`). **Self-contained** mode = ROOT
spawns it as a **named Tier-1 leader teammate** (`mode: self-contained`); it
runs its OWN read-only sub-flock — `@discovery` + intro-`@auditor` + its own
`@critic` — and root runs neither wave. Only non-conductor role that may be
a teammate; dispatches ONLY that read-only trio (never `@coder`/`@worker`,
never a nested `@engineer`). See §IV-bis.5 / .5-bis and
`doctrines/engineer-self-contained-plan.md`.

---

## I-bis. Tier ↔ ontology unit ↔ primitive (v6.0.2, #88 / #89)

The three tiers map **one-to-one** onto shepherd's planning ontology and
the Claude-native primitives (canonical table:
`primitive-axis-binding.md §I, §IV`).

| Ontology unit | Tier | Native primitive |
|---|---|---|
| **step** (a unit of work within a wave; a plan is N waves × X steps) | Tier 1 (flock) | **subagent** (`subagent_type: "shepherd:<role>"`) |
| **lane** (a vertical slice ACROSS waves; spawn-only, post-plan) | Tier 2 (teammate-conductor) | **Agent Teams** teammate |
| **wave** (a sequential gated stage) | — (seam, not a tier) | conductor-inline gate |

Enforced by §IV-bis: a **step** is an ephemeral dispatch; a **lane** is a
teammate-conductor (native teammate-spawn referencing
`subagent_type: shepherd:conductor`, via `SendMessage`) — discriminated by
spawn INTENT, not `team_name` (accepted but ignored since v2.1.178). A lane
spawns via **Agent Teams, never a Dynamic Workflow**; its gate-free step
fan-out **compiles to a Dynamic Workflow, never hand-rolled dispatch**
(`primitive-axis-binding.md §III`). The engineer authors `waves × steps`
with **no lane concept** — lanes are the post-plan spawn projection and
**never nest inside a wave**.

---

## II. Dispatch matrix

| From → To | `@engineer` | `@critic` | `@coder` | `@auditor` | `@worker` | `@discovery` | Another teammate |
|---|---|---|---|---|---|---|---|
| **TIER 3 root (shepherd)** | ✅ | ✅ | ❌ (teammate owns) | ✅ (close + intro swarm) | ✅ (root ledger) | ✅ (intro/close) | ✅ (spawn) |
| **TIER 2 conductor (solo)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no nested spawn) |
| **TIER 2 conductor (teammate)** | ❌ → escalate `PLAN-AUTHORSHIP-REQUEST` | ❌ → escalate `PLAN-GATE-REQUEST` | ✅ (wave) | ✅ (wave) | ✅ (wave) | ✅ (wave) | ❌ (no nested spawn) |
| **TIER 1 flock (any)** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **PARALLEL planter** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

Legend: ✅ permitted · ❌ forbidden (process error) · ❌ → escalate —
forbidden, but the tier-2 teammate has a defined escalation path back to
root (`PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST`, §IV).

**Leader carve-outs.** The flock's all-❌ row is *standard*; two roles are
elevated to leaders with a bounded, read-only dispatch grant (mechanized by
`hooks/tests/lint_agent_capabilities.sh`):

- **PARALLEL planter** MAY dispatch `@discovery` — the bounded plant-mode
  orientation wave (`agents/planter.md §Step 2-bis`).
- **Self-contained `@engineer`** (ROOT-spawned NAMED teammate, `mode:
  self-contained`) MAY dispatch its read-only sub-flock — `@discovery` +
  intro `@auditor` + its OWN `@critic` (tagged `dispatcher:
  engineer-self-contained`) — and NOTHING else. Never `@coder`/`@worker`,
  never nested `@engineer`, never a teammate
  (`doctrines/engineer-self-contained-plan.md`). A teammate **conductor**
  still may not dispatch `@engineer`/`@critic`.

---

## III. Mode-detection for tier-2 conductors

`agents/conductor.md` is adopted by both `/shepherd:start` (solo) and
`/shepherd:spawn` teammates. It must self-detect its mode to know whether
`@engineer`/`@critic` dispatch is permitted.

**Detection signals** (any one positive → teammate mode; matches
`agents/conductor.md §mode-detection` / `commands/spawn.md` Check 0):
(1) session `cwd` under a shepherd `.worktrees/` path (reliable); (2) boot
prompt carries `INVOCATION-CONTEXT.dispatcher: teammate-conductor` or
`ROOT-SESSION-NAME: shepherd-root @ ...` (reliable); (3)
`$CLAUDE_AGENT_TEAMMATE_NAME`/`$CLAUDE_PROJECT_SESSION_TYPE` set — **legacy,
reads EMPTY on the live platform (GH #93), do NOT rely on it**.

All negative → solo mode. Conductor MUST verify mode at session-start
(Step 0) and surface it explicitly:

```
[SESSION-START] branch={sprint_branch} | mode={solo|teammate} | seed={path}
```

---

## IV. The escalation patterns (teammate → root)

When a teammate conductor needs root-tier-exclusive work, it returns a
structured escalation payload via `SendMessage(to: lead, ...)` (schema:
`doctrines/spawn-escalation.md §III`).

### `PLAN-AUTHORSHIP-REQUEST`

Trigger: the teammate's plan is insufficient/stale — a fresh `@engineer`
pass is needed (SEED-DRIFT, scope amendment, dependency rotation
invalidating a lane). Payload: `halt_code, phase, blocking: true,
context_files: [<sprint_slug>.plan.md, <sprint_slug>.seed.md],
amendment_summary`. Root response: dispatch `@engineer`, materialize
revised plan, resume with new plan path.

### `PLAN-GATE-REQUEST`

Trigger: a revised plan or design question needs `@critic` review before
the teammate resumes. Payload: `halt_code, phase, blocking: true,
context_files: [<plan>.md], gate_question`. Root response: dispatch
`@critic`, materialize verdict, resume with verdict.

### `WRONG-TIER-DISPATCH`

Trigger: NOT teammate-initiated — the code an `@engineer`/`@critic`
surfaces when it detects (via `[INVOCATION-CONTEXT]`) it was dispatched by
a teammate-conductor; a process violation by the teammate. Root response:
do NOT auto-resume — surface to operator with the failing teammate's
identity, patch its brief discipline or end the session.

---

## IV-bis. Forbidden dispatch matrix (binding refusal contract; v6.0.0+)

§II describes what each tier MAY do; this section enumerates the specific
Agent-call constructions that MUST be refused on sight, with halt codes.
Callers (`agents/shepherd.md`, `agents/conductor.md`,
`skills/shepherd/flock.md`, `skills/shepherd/SKILL.md`, `commands/spawn.md`)
cite this section instead of re-stating the rules.

Shape of a subagent dispatch under shepherd discipline:

```
Agent({
  subagent_type: "shepherd:<role>",   // MANDATORY for every flock dispatch
  model: "<sonnet|opus>",              // per flock.md table
  prompt: "<task brief>"               // brief only — NOT the agent body
  // NO team_name — accepted but ignored (v2.1.178); never makes a teammate.
})
```

Teammate-conductors (lanes) are NOT dispatched this way — root spawns them
via the native teammate-spawn (no `TeamCreate` tool, removed v2.1.178),
then talks via `SendMessage`. Any deviation is one of the violations below.

### IV-bis.1. `DISPATCH-MISSING-SUBAGENT-TYPE`

**Trigger:** any flock dispatch (`@coder`, `@auditor`, `@worker`,
`@discovery`, `@engineer`, `@critic`) that omits `subagent_type`, defaults
to `general-purpose`, or sets it to `Explore`/`Chat`/`general-purpose`/any
other non-shepherd identifier.

**Refusal:** the dispatcher (root in INTRO/CLOSE; teammate-conductor in
BODY) MUST refuse to fire the call — surface to operator (root) or
escalate (`SendMessage(to: lead, halt_code:
DISPATCH-MISSING-SUBAGENT-TYPE, blocking: true)`, teammate). *(Replaces a
pre-v5.1.9 permissive fallback that silently degraded to
`general-purpose`.)*

### IV-bis.2. `DISPATCH-TEAMMATE-TYPE-MISMATCH`

**Trigger:** a dispatch attempts to stand up a flock role OTHER than
`shepherd:conductor` as a **teammate**. Teammates spawn only via native
teammate-spawn referencing `shepherd:conductor`; `team_name` is accepted
but ignored, so it's not a usable discriminator — the real distinction is
spawn INTENT (`shepherd:conductor` = a lane; self-contained
`shepherd:engineer` = a named leader teammate, §I; everything else =
ephemeral subagent). `dispatch_guard.sh` Check 3 is vestigial
defence-in-depth; the mechanical floor is `subagent_type` (§IV-bis.1).

**Refusal:** root MUST refuse. Teammate-spawning (a lane) is
conductor-only; a coder (etc.) is an ephemeral **subagent** dispatched BY a
conductor, never spawned AS a teammate. *(FL03/shepherd #65: root once
spawned 4 coder teammates with no conductor gates or error recovery.)*

### IV-bis.3. `DISPATCH-OFF-FLOCK`

**Trigger:** an Agent call sets `subagent_type` outside the closed-flock-six
(`shepherd:engineer/critic/coder/auditor/worker/discovery`) and outside
`shepherd:conductor` (teammate spawns from root). Specialist exceptions
(`doctrines/specialist-dispatch.md`) clear this only after passing the
DISPATCH DECISION TREE §Q1–Q4.

**Refusal:** the dispatcher MUST refuse — the flock is closed at six; plan
authorship, critic gating, close-time grading, and code implementation are
never substitutable.

### IV-bis.4. `TEAMMATE-NESTING-ATTEMPT`

**Trigger:** a teammate-conductor (per §III) constructs any Agent call with
`team_name` set, invokes `/shepherd:spawn` from within its session, or
otherwise attempts to spawn its own teammate-tier.

**Refusal:** refuse and `SendMessage(to: lead, halt_code:
TEAMMATE-NESTING-ATTEMPT, blocking: true)` to root. Platform forbids nested
teams (D-API §12); doctrine forbids it too.

### IV-bis.5. `WRONG-TIER-DISPATCH`

**Trigger:** a teammate-**conductor** attempts to dispatch `@engineer` or
`@critic`. Detected at the agent boundary: engineer/critic profiles read
`INVOCATION-CONTEXT.dispatcher` on boot and halt if the dispatcher is a
teammate-conductor. Mechanized: `dispatch_guard.sh` Check 4 blocks teammate
→ `@engineer` **unconditionally**, and teammate → `@critic` **unless** the
brief carries `dispatcher: engineer-self-contained`.

**Carve-out:** a self-contained `@engineer` teammate dispatching its OWN
`@critic` (tagged `dispatcher: engineer-self-contained`) is the permitted
adversarial self-gate (`doctrines/engineer-self-contained-plan.md`) — this
rule targets a teammate **conductor** re-gating a fixed plan; a nested
`@engineer` from any teammate is always forbidden.

**Refusal:** teammate-conductor surfaces `PLAN-AUTHORSHIP-REQUEST` (engineer
needed) or `PLAN-GATE-REQUEST` (critic needed) to root, which dispatches
directly and returns the result via resume reply.

### IV-bis.5-bis. `ENGINEER-TOPOLOGY-MISMATCH`

**Trigger:** `@engineer` dispatched as a **subagent** while its brief
carries `mode: self-contained` — that mode is always a NAMED teammate, never
a subagent (v6.2.5 "unnamed subagent engineer" failure). Mechanized:
`dispatch_guard.sh` Check 4b.

**Refusal:** spawn as a teammate, or drop `mode: self-contained` to run
classic. Root never repairs by re-dispatch.

### IV-bis.5-ter. `ENGINEER-SUBFLOCK-VIOLATION`

**Trigger:** a dispatch tagged `dispatcher: engineer-self-contained` targets
a `subagent_type` outside the read-only trio (`shepherd:discovery`,
`shepherd:auditor`, `shepherd:critic`) — e.g. `@coder`/`@worker` or a
nested `@engineer`. Mechanized: `dispatch_guard.sh` Check 4c. A conductor
lane carries no such marker, so its `@coder`/`@worker` fan-out is
unaffected.

**Refusal:** the engineer files a plan step for the conductor's
coder/worker wave instead of dispatching a writer itself. Its sub-flock is
closed at the three read-only roles.

### IV-bis.6. `MODE-MISUSE`

**Trigger:** SOLO-mode conductor attempts to spawn a teammate, OR
TEAMMATE-mode conductor attempts a SOLO-mode operation (artifact write,
git commit, operator direct-message) the §III matrix forbids.

**Refusal:** halt and surface. Mode detection is mandatory at Step 0 per
`agents/conductor.md §Conductor modes`. Ambiguous signals → halt with
`MODE-DETECTION-AMBIGUOUS` (same surface discipline).

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

These halt codes are **terminal for the offending dispatch** — root does
NOT auto-resume on `WRONG-TIER-DISPATCH` or `TEAMMATE-NESTING-ATTEMPT`;
the brief needs operator review per `agents/shepherd.md §Halt codes
(root-side)`.

### IV-bis.8. TEAMMATE-GIT-WRITE — teammate git custody (v6.0.3 — #99)

A teammate-conductor's git authority is bounded to commits on its OWN
worktree branch. MUST NOT run `git rebase`, `git merge`, `git push`, or
`git worktree` (add/remove) — root-tier operations; root rebases every lane
at each wave-gate, a teammate never rebases itself even when behind. On
reaching for such a command: STOP and `SendMessage(to: lead, halt_code:
TEAMMATE-GIT-WRITE, blocking: true)`. Cross-ref: `agents/conductor.md
§Hard prohibitions #19` + `§Side-effect boundary`.

---

## V. The flock contract (unchanged)

The closed-at-six flock contract remains binding:

- `@engineer` (Opus) — plan authorship. Never a teammate-conductor dispatch; root only (classic subagent, or self-contained leader teammate, §I exception).
- `@critic` (Sonnet) — adversarial gate. Root only (classic), or the self-contained `@engineer` teammate self-gating (tagged `dispatcher: engineer-self-contained`); never a teammate-conductor re-gate.
- `@coder` (Sonnet) — implementation. Any tier-2 conductor.
- `@auditor` (Sonnet) — read-only review. Tier-3 (close + intro swarm), tier-2 teammate (wave-mid), or tier-2 solo.
- `@worker` (Sonnet) — bounded execution. Any tier.
- `@discovery` (Sonnet) — read-only orientation. Any tier.

Specialist agents (per `doctrines/specialist-dispatch.md`) follow the same
tier rules: a teammate-conductor needing a specialist for plan-grade work
must surface `PLAN-AUTHORSHIP-REQUEST` first.

---

## VI. Why this discipline matters

Three real failures drove this doctrine: (1) a teammate re-ran `@engineer`
mid-sprint, producing two divergent plans and a close-audit dispute
(v5.1.5); (2) teammate-materialized close reports/handoffs polluted
subsequent wave context, eroding fresh-context-per-wave (now fixed via
**lane refresh**, `primitive-axis-binding.md §II.1`); (3) a permissive
dispatch fallback let lane-coders stand up as teammates and
`general-purpose` fire on omitted `subagent_type` (FL03/shepherd #65, #66) —
closed by §IV-bis's named violations + self-checked halt codes.

Tier separation fixes all three: engineer + critic run ONCE per sprint,
never re-run by a teammate-conductor; teammate context stays narrow (own
wave only); root alone absorbs artifact-materialization cost.

---

## VII. Solo-mode exemption

`/shepherd:start` in main chat is solo mode. The conductor retains its full
dispatch surface (engineer + critic + four-lane flock) — tier separation
does NOT apply; there's only one conductor and no cross-conductor
divergence risk. Backward-compatible; existing solo workflows are
unaffected. Tier separation activates only under `/shepherd:spawn`.

---

## VIII. See also

- `doctrines/primitive-axis-binding.md` — canonical axis ↔ primitive ↔ unit binding; §I-bis is its tier-mapping projection
- `doctrines/root-shepherd-orchestration.md` — root-tier responsibilities + modes
- `doctrines/scope-scale-workload.md` — `--scope` flag composition with tiers
- `doctrines/spawn-escalation.md` — escalation channel mechanics
- `agents/shepherd.md` — root profile
- `agents/conductor.md §Conductor modes` — solo vs teammate behavior
- `agents/engineer.md §Hard prohibitions`, `agents/critic.md §Hard prohibitions` — WRONG-TIER-DISPATCH halt code
- `doctrines/workflow-compile-down.md` — compiled workflow steps honor the mandatory-`subagent_type` contract this doctrine defines
