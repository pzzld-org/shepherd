---
title: engineer-self-contained-plan
status: binding
introduced: v6.2.5
description: |
  The engineer exists for ONE thing: turn the seed + current context into an
  executable, multi-phase, vertically-lane-sliced plan. When root spawns the
  engineer as a TEAMMATE (self-contained mode), the engineer owns its whole
  planning pipeline in-session — an in-session @discovery wave, an embedded
  adversarial critic pass, and at least one revision — and returns a plan plus
  an irrefutable critic-proof. Root does NOT re-critique: it runs a thin,
  mechanical acceptance gate (shctx seed verify + shctx plan verify + lane
  sanity) and proceeds to LANE-INTEGRATE. Behavioral wiring + one CLI verb
  (shctx plan verify/record-critique); the critic-proof is a hash-tied artifact,
  not trust.
---

# Engineer self-contained plan — plan construction is the whole point, and a teammate carries its own proof (#169)

## Why the engineer exists

Plan construction is the single highest-leverage act in a sprint. A plan that is
complete, decomposed, and drift-resistant is the difference between 4-5 parallel
coders converging and diverging. The engineer's entire reason to exist is to take
the **seed + current context** and produce **one actionable, executable,
multi-phase plan**:

- Each **phase** holds N granular tasks/stages (`steps`), each ≈ one subagent's
  unit of work.
- Stages are **conditionally linked** — the plan emits a `## Stage Graph` whose
  edges (`on-*` predicates) make execution near-automatic (`doctrines/stage-graph.md`).
- The finished, critic-gated plan is then sliced **vertically into independent
  lanes** — a lane is a vertical slice across phases, file-disjoint from its
  siblings (`doctrines/primitive-axis-binding.md §II`).
- Root maps **each lane to a team led by a conductor**, who runs dynamic
  workflows dispatching **coder/worker waves** with **auditor self-review**
  (`doctrines/flock-output-review.md`).

Everything downstream inherits the plan's quality. That is why this role runs on
the most expensive model and why its output is gated before a single coder fires.

## Two dispatch topologies

The plan body is **mode-agnostic** (`waves × steps`, never lanes —
`doctrines/primitive-axis-binding.md`). What differs is who runs discovery + the
critic:

- **Classic (root-tier subagent, or `/shepherd:start` solo).** Root runs the
  discovery wave *before* the engineer (INTRO-COMBO-WAVE,
  `doctrines/intro-combo-wave.md`) and dispatches the **distinct `@critic`**
  *after*. Highest independence; unchanged by this doctrine.
- **Self-contained (teammate).** Root spawns the engineer as its OWN teammate.
  The engineer owns the full pipeline in-session and returns a finished plan +
  critic-proof. Root does no separate discovery-review or critic pass.

## What self-contained mode runs in-session

1. **Discovery wave — in-session `@discovery` subagents.** The engineer dispatches
   `@discovery` (Agent tool, scoped to `shepherd:discovery` ONLY — the same
   read-only bound the planter carries, `agents/planter.md §Step 2-bis`; a
   teammate dispatching `@discovery` is permitted by `hooks/scripts/dispatch_guard.sh`).
2. **Embedded adversarial critic pass.** A teammate **cannot** dispatch `@critic`
   or `@engineer` — that is `dispatch_guard.sh` Check 4 / `doctrines/dispatch-tier-separation.md`
   ("@engineer and @critic run ONCE at root"), and it stays. So in self-contained
   mode the critic is an **embedded pass**: the engineer applies the `@critic`
   adversarial rubric (`agents/critic.md`) to its OWN plan as a dedicated
   reasoning turn, surfaces findings, and **revises at least once**. This trades a
   measure of independence for lane autonomy; the critic-proof is the compensating
   control (below), and classic mode remains the higher-independence path.
3. **Emit the critic-proof.** After the revision, record the proof.

The engineer still NEVER writes source, NEVER commits, NEVER spawns a nested
teammate (structurally impossible + `doctrines/dispatch-tier-separation.md`), and
dispatches ONLY `@discovery` — never `@coder`/`@auditor`/`@critic`/`@engineer`.

## The critic-proof — irrefutable, not trust

The critic-proof is a hash-tied artifact written ALONGSIDE the plan
(`<plan-slug>.critic-proof.json`), so root can accept the plan mechanically
instead of re-reading it:

```
pre_critic_hash   sha256 of the plan BEFORE the critic pass
post_critic_hash  sha256 of the plan AFTER the revision
edited            post != pre   (proves ≥1 edit happened)
critic.verdict    the critic pass verdict (not a hard FAIL)
critic.iterations ≥1
```

- Engineer writes it: `shctx plan record-critique --plan <p> --pre <hash> --verdict <v> --iterations <n>`
  (capture `--pre` with `shctx plan hash <p>` BEFORE the critic pass).
- Root verifies it: `shctx plan verify --plan <p>` (mirrors the v6.2.1
  `shctx seed verify` gate). It re-hashes the CURRENT plan bytes and requires
  `post_critic_hash` to match — so a stale or hand-forged proof cannot pass.

The latent critic pass produces findings; the deterministic hash-proof + verifier
make "the plan was critiqued AND edited at least once" **provable**, not asserted
(the latent→deterministic split, CLAUDE.md).

## Root's thin acceptance gate — no re-critique

On receiving a self-contained engineer teammate's plan, root runs ONLY:

1. `shctx seed verify <seed>` (the existing v6.2.1 seed gate), and
2. `shctx plan verify --plan <plan>` (the critic-proof gate), and
3. a lane-count sanity check (≥1 lane; count within the T-shirt band,
   `agents/engineer.md §Lane-count guidance`).

All green → root proceeds to `LANE-INTEGRATE`
(`doctrines/teammate-integration-authority.md`). Root does **not** re-run the
critic on a self-contained plan. A failed gate returns the named code
(`CRITIC-PROOF-MISSING` / `PLAN-UNEDITED` / `CRITIC-PROOF-STALE` /
`PLAN-UNCRITIQUED`) to the engineer teammate for a fresh pass — root never repairs
the plan itself.

## Mechanical teeth

- `shctx plan verify` is deterministic and exit-coded; root's thin gate is a
  mechanical call, not a judgment.
- The proof's `post_critic_hash` is checked against the live plan bytes, so the
  gate cannot be satisfied by an unedited plan or a proof describing an older one.
- Coverage row: `doctrines/invariant-enforcement-matrix.md`.
- The engineer's `Agent` grant is pinned to the `shepherd:discovery` scope bound
  by `hooks/tests/lint_agent_capabilities.sh` (the same pin the planter carries).

## Anti-patterns

- Root re-critiquing (dispatching `@critic` on) a plan that already carries a
  valid critic-proof — the context bloat this doctrine exists to remove.
- Recording a critic-proof with `edited=false` (no revision) — `shctx plan verify`
  fails it (`PLAN-UNEDITED`).
- An engineer teammate trying to dispatch `@critic` — blocked by `dispatch_guard.sh`;
  use the embedded critic pass instead.
- The engineer using its `Agent` grant for anything other than `@discovery`.

## See also

- `doctrines/primitive-axis-binding.md` — waves × steps; lanes as a post-plan projection.
- `doctrines/dispatch-tier-separation.md` — why a teammate cannot dispatch @engineer/@critic.
- `doctrines/stage-graph.md` — the binding dispatch contract + conditional edges.
- `doctrines/intro-combo-wave.md` — the discovery wave the engineer consumes/runs.
- `doctrines/teammate-integration-authority.md` — LANE-INTEGRATE.
- `doctrines/flock-output-review.md` — the lane's coder-output review the conductor runs.
- `doctrines/model-map.md` — the model each tier dispatches with.
- `agents/critic.md` — the adversarial rubric the embedded critic pass applies.
