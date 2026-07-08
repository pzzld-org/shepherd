# v6.3.0 — Dispatch-pin DSL: explore #181, decide

Status: DECIDED. Author: sprint session 2026-07-08. Scope: resolves the explore issue #181
(template/compiler layer for dispatch call-sites) after shipping the narrow #180 fix in this sprint.

## The question (#181)

Instead of hooks catching missing `model:`/`agentType:` pins on `agent()` calls *after* the fact,
could a template/DSL layer + compiler generate dispatch call-sites so the `[models]` wiring is
correct *by construction*? Is #180 (extend the existing `shctx graph compile` to inject pins) the
whole fix, or is a broader DSL covering **every** dispatch call-site warranted?

## Outcome (measurable)

The metric that decides escalation: **`workflow_model_guard.sh` deny events per sprint** (and
`// shepherd:model-pin-override` marker uses), read from `<ns>/logs/hooks/YYYY-MM-DD.jsonl`
(`decision:"deny"`, `hook:"workflow_model_guard"`). A broad DSL is justified only if hand-authored
(non-compiled) dispatch keeps tripping the guard after #180. Baseline before #180: the #178 field
incident (a Fable-5 planter hand-rolling an unpinned deep-audit wave). Target: the guard's deny rate
stays at noise level; if it climbs, escalate to the scaffold step below.

## Two dispatch classes, two mechanisms — both now closed

| Class | Origin | Pin mechanism | Status |
|---|---|---|---|
| **Graph-derived fanout** | `shctx graph compile` → `*.workflow.js` run via `node` | Pin injected **by construction** (`agentType` + `[models]` `model`) + `--verify` `model_pin` invariant | **closed by #180 (this sprint)** |
| **Hand-authored Workflow** | ad-hoc `Workflow({script})` via the native tool | `workflow_model_guard.sh` `PreToolUse(Workflow)` blocks a call missing both pins | **closed by #178 (PR #179)** |

The compile-down path never reaches the `PreToolUse(Workflow)` guard (it runs via `node`, not the
Workflow tool), which is exactly why #180 was needed as a *separate* injection+verify mechanism for
that path. With both shipped, every dispatch that carries a model is now either pin-correct by
construction (compiled) or intercepted before it runs (hand-authored). There is no third,
unguarded class in the current architecture.

## What #180 shipped (this sprint)

`skills/context/scripts/cmd_graph.sh`:
- Fixed the emitted call shape from `agent(s)` (whole object passed positionally as `prompt` — the
  wrong signature, which also carried no pin) to `agent(s.prompt, s.opts)`.
- Injects `opts.agentType = "shepherd:<role>"` and `opts.model` resolved from the `[models]` map
  (`_graph_role_model` → `cfg_section_get models <role>`, defaults mirroring `cmd_models.sh`).
- Extended the `--verify` faithfulness diff with a **model_pin** invariant: pin count must equal the
  expected spawn count, and the legacy opts-less `agent(s)` shape is rejected.
- `skills/context/tests/test_graph_compile.sh` asserts the shape, the pins, and that the emitted
  script would pass `workflow_model_guard.sh` (the "would this pass the guard" bar from #180).

## Decision: do NOT build the broad DSL now

A DSL covering every dispatch call-site (briefs, ad-hoc scripts, everything) is more powerful but a
real lift — compiler correctness, migrating existing skills/agents/doctrine, and more surface for
the compiler to drift from the platform's real `agent()` signature (the exact bug #180 just fixed:
the emitted shape had drifted from `agent(prompt, opts)`). It is not warranted while both dispatch
classes are already covered.

The itch #181 named — hand-authored one-off Workflow scripts that never go through
`shctx graph compile` — is real but is already caught at submission by the #178 guard. Preventing it
at *authoring* time is a convenience, not a correctness gap.

## The cheap next step, if the metric says so

If the guard's deny rate climbs (operators keep hand-rolling unpinned waves), the proportionate
escalation is NOT a full DSL but a **skeleton emitter**: `shctx workflow scaffold <role>...` that
prints a correctly-pinned `agent(prompt, { agentType, model })` block for the dispatcher to paste —
reusing `_graph_role_model` so the pin comes from the same `[models]` source the compiler already
uses. That turns "remember to pin" into "paste the pinned skeleton" without a compiler that must
own an upstream plan graph. Size it only after measuring; do not pre-build it.

## Refs

- #178 / PR #179 — `workflow_model_guard.sh`, the hand-authored-dispatch guard.
- #180 — the narrow compiler fix, shipped this sprint (`cmd_graph.sh`, `run_verify`,
  `test_graph_compile.sh`).
- `skills/harness/references/workflow-templates.md` §Model pin + §Compile-down model — the pin
  invariant (4) and the two-mechanism contract.
- `skills/context/references/model-map.md` — the single `[models]` source both mechanisms resolve.
