---
title: workflow-tool-self-check
status: binding
introduced: v6.1.6
description: |
  The operational front-end for the native Workflow tool. ONE first-action
  self-check, run once at session/lane open, that determines and RECORDS whether
  the Workflow tool is present (the visible-tool-list test — never ToolSearch),
  then branches: present → compile gate-free fan-out and run it out-of-context
  (the conductor's OWN benefit); absent → degrade to in-context Agent(...). Folds
  the scattered guidance (glossary §1, capability-discovery §V, workflow-compile-
  down, primitive-axis-binding §IV) into a single crisp checklist an agent cannot
  miss. The compile MODEL is owned by workflow-compile-down.md; this doctrine owns
  the DETECTION-AND-BENEFIT seam that kept getting skipped.
---

# Workflow-tool self-check — detect, record, then benefit

> **Why this doctrine exists.** The framework already says, in four places, that
> the native `Workflow` tool is never a `ToolSearch` target and that gate-free
> fan-out compiles down to it. It still gets skipped. A v0.3.5 sprint stalled
> when teammates heard "dynamic workflow", ran `ToolSearch`, got nothing, and
> gave up. On 2026-06-15 *this framework's own maintenance session*, running
> under `/effort ultracode` with an explicit "use the Workflow tool" instruction,
> did the identical thing — `ToolSearch select:Workflow` → nothing → "confirmed
> absent." **Both the method and the conclusion were wrong**: Dynamic Workflows is
> enabled in web / remote / cloud-container sessions, so the tool was almost
> certainly present and the session skipped a tool it had. The lesson: detection
> cannot live in prose an agent reads once and forgets, and it must NEVER be a
> `ToolSearch`. It must be a **named first action with a recorded result** read off
> the visible tool list. That is this doctrine.

## I. The ONE test (authoritative)

**Is the literal token `Workflow` in your visible tool list?**

- **Yes** (the expected case — Dynamic Workflows is enabled across entrypoints,
  web / remote / cloud-container included) → use it (compile gate-free fan-out, §IV).
- **No** → only the narrow genuine-absence case (an explicit `disableWorkflows` /
  `CLAUDE_CODE_DISABLE_WORKFLOWS`, or a build below the v2.1.154 floor). Degrade to
  in-context `Agent(...)` fan-out (§V). This is **not** the web/remote default.

That is the whole test. The visible-tool-list check is the **only** authority —
never infer absence from a `ToolSearch` miss (§II), never from the fact that the
session is web/remote (it is enabled there), never from the Claude Code version
number, and never from the `/effort ultracode` instruction "use the Workflow tool"
(that instruction is *satisfied by* checking your tool list, not by searching for
a tool), and never from a prior session's memory of what was available.

## II. The forbidden test — NEVER `ToolSearch` for `Workflow`

`ToolSearch("workflow")` / `ToolSearch select:Workflow` / any keyword search
returns **nothing — by design**, because the native `Workflow` tool is a
**top-level** tool, not a deferred one. `ToolSearch` resolves *deferred* tools
only (specialist agents, MCP). A nothing-result from `ToolSearch` means **you
looked in the wrong place**; it is not evidence of absence and must never be
reported as "confirmed absent." Reaching for `ToolSearch` here is itself the
`WORKFLOW-SELFCHECK-TOOLSEARCH` anti-pattern — stop and apply §I instead.

The same holds for every native orchestration primitive — `TaskCreate` /
`TaskGet` / `TaskList` / `TaskUpdate`, `TeamCreate` / `TeamDelete`, `SendMessage`:
all top-level, all called directly, none a `ToolSearch` target. `ToolSearch
select:TaskCreate` *erroring* is expected and means "native, not deferred", not
"missing".

(Why the confusion persists: the model has no training prior for this tool —
research-preview, 2026-05 — so these doctrines are its only teacher. See
`references/glossary.md` and `doctrines/primitive-axis-binding.md`.)

## III. Record the result (the `agent_fillin` contract)

The SessionStart probe (`hooks/scripts/capability_discovery.sh`,
`doctrines/capability-discovery.md §V`) writes an **advisory env hint** only —
`present-expected` (Dynamic Workflows is enabled across entrypoints) — because a
hook is not the agent and cannot see the tool list. You close the loop:

- On your **first** `/shepherd:*` turn, perform §I and record
  `workflow_tool: present: true|false` in your orientation. This satisfies the
  roster's `agent_fillin.workflow_tool` contract.
- Surface it in the session-start status line so it is visible to the operator
  and to root:
  ```
  [SESSION-START] branch=… | mode=… | workflow_tool=present|absent | …
  ```
- In **TEAMMATE mode**, carry `workflow_tool` (and, per segment, whether you
  compiled or fell back) in every `WAVE-COMPLETE` payload so root can track
  engine health and catch a teammate that silently hand-rolled where the tool
  was present (§IV, the `PRIMITIVE-INVERSION` seam).

Record it **once** per session; it does not change mid-session.

## IV. When present — compile, because it is YOUR benefit

When `Workflow` is present, every gate-free agent-fanout segment in your walk
(WAVE-IMPL coders [+ worker], lane AUDIT, CLOSE-SWARM, DISCOVERY waves, HOTFIX
batches) is compiled and run out-of-context via the sequence in
`doctrines/workflow-compile-down.md` / `agents/conductor.md §Step 2`
(`shctx graph compile --segment=<entry> --verify` → run `<seg>.workflow.js` →
`shctx graph mark`).

Frame this correctly: compiling is not a tax the framework imposes on you — it is
**the conductor's own benefit**, and choosing the in-context fallback when the
tool is present is a *self-inflicted handicap*:

| You keep (compile, out-of-context) | You lose (hand-rolled in-context) |
|---|---|
| Your context window stays clean — intermediate agent results live in script variables, never in your conversation | Every coder/auditor return lands in your context; you blow your window and risk compaction mid-wave |
| Up to 16 agents run in parallel in the background while you stay responsive | You serialize or juggle batches by hand, holding all of it in working memory |
| The dispatch is `compile(G)` — mechanically faithful to the critic-gated graph | You re-author dispatch on the fly, re-opening every drift this framework closes |

So the rule is not merely "you MUST compile or it's `PRIMITIVE-INVERSION`" (it is,
per `doctrines/primitive-axis-binding.md §IV`) — it is "you *want* to compile,
because the alternative costs you more context and gives you less parallelism for
the same work." The mandate and the incentive point the same way.

The in-context fallback (§V) is reached **only** on a confirmed runtime failure
or genuine absence — never as a shortcut when the tool is sitting in your tool
list.

## V. When absent — degrade cleanly (correct, not a failure)

When `Workflow` is **not** in your visible tool list — the narrow genuine-absence
case: a Claude Code build below the Dynamic Workflows floor (v2.1.154), **or** an
explicit disable (`disableWorkflows` / `CLAUDE_CODE_DISABLE_WORKFLOWS`) — you
degrade to in-context `Agent(...)` fan-out. (Web / remote / cloud-container is NOT
this case — Dynamic Workflows is enabled there; #146 corrected.) This is the
documented degraded path (`doctrines/workflow-compile-down.md §XI`, glossary sense
1). It is fully correct: the same flock, the same briefs, the same graph — walked
in-context instead of compiled. Do not ToolSearch, do not retry, do not report the
feature "broken." Record `present: false` and proceed. Solo and teammate both
degrade identically; no team is required either way.

## VI. First-action placement (mode-agnostic)

The self-check is **Step 0 / first-action**, before any dispatch:

- **SOLO conductor** (`/shepherd:start`): perform §I at SEED-VERIFY, record per §III.
- **TEAMMATE conductor** (`/shepherd:spawn`): perform §I at lane start (the same
  first-action that reads the lane brief and opens the FOCUS-LOOP), record in the
  first `WAVE-COMPLETE` payload's `workflow_tool` field.
- **ROOT shepherd** (`/shepherd:spawn` main chat): perform §I before compiling any
  cross-lane / root-tier gate-free segment it owns.

One check, one recorded result, then the walk proceeds with the right execution
substrate already chosen.

## VII. Cross-doctrine references

- `references/glossary.md §1` — the native `Workflow` tool: what it is, the
  visible-tool-list test, never-ToolSearch, always-enabled presence (#146 corrected).
- `doctrines/capability-discovery.md §V` — the SessionStart probe, the advisory
  env hint, and the `agent_fillin.workflow_tool` hand-off this doctrine closes.
- `doctrines/workflow-compile-down.md` — the compile MODEL (§IV faithfulness, §V
  φ-map, §VI seam); this doctrine is its detection-and-benefit front-end.
- `doctrines/primitive-axis-binding.md §IV` — `PRIMITIVE-INVERSION`: hand-rolled
  fan-out where a compiled workflow was available.
- `doctrines/dispatch-cascade.md §IV-bis` — the primary-path / fallback cascade.
- `agents/conductor.md §Hard prohibitions #22` + `§Step 2 BODY` — the binding
  TEAMMATE-mode compile sequence this self-check gates entry to.
