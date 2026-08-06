---
name: start
description: Root drives waves of Dynamic Workflows to execute an already-planned sprint or a direct task — execution-only, and the fallback when Agent Teams / teammate-conductors are unavailable.
argument-hint: "[ sprint_slug | task ] [ --from=<base_ref> ]"
allowed-tools: Agent, Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, Workflow, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:start — root-drives-workflows execution

Main chat adopts `agents/shepherd.md` (full file) as a system-prompt addendum, then drives
`skills/shepherd/references/wave-routine.md` DIRECTLY over an already-planned sprint's lanes
(or a small, self-contained task) — no teammate-conductor spawn, no `@engineer`/`@critic`
planning phase. The plan MUST already exist; a missing plan is NOT planted inline here — route
to `/shepherd:plant` then `/shepherd:spawn`. `/shepherd:start` is the thin, execution-only
entry point: one root dispatcher compiling wave after wave of Dynamic Workflows until the
target is done.

## When to use vs /shepherd:spawn

`/shepherd:spawn` is the optimized path for substantive, large-scale work: it runs the
INTRO-COMBO-WAVE + `@engineer` plan authorship + `@critic` gate, then fans out one
teammate-conductor per lane under Agent Teams. `/shepherd:start` is the abbreviated,
single-dispatcher counterpart — no fanout, no planning, just execution of a plan that already
cleared `@critic` — and it is the documented FALLBACK when Agent Teams / teammate-conductors
are unavailable or failing. Both drivers run the exact SAME per-wave routine
(`skills/shepherd/references/wave-routine.md`) via the exact SAME dispatch vehicle — a
compiled Dynamic Workflow, at both tiers (#263); only the driver (one root vs. one
teammate-conductor per lane) and the scope (sprint vs. one lane) differ.

## Preflight

Run every check before the first wave compiles. Refuse with a clear error on any HARD gate;
Check 0 runs FIRST.

| Check | Gate | Rule |
|---|---|---|
| 0 | Operator-only invocation | HARD. Refuse if invoked from a teammate session — same secondary signals as `commands/spawn.md §Check 0` (cwd under `.worktrees/`, `INVOCATION-CONTEXT.dispatcher: teammate-conductor`). |
| 1 | Plan exists for the target | HARD. `sprint_slug` target: `{run_dir}/plan.md` (`{run_dir}` = `{paths.runs}/{run}`, default `.shepherd/runs/{run}`; `{run}` = the sprint slug) MUST exist and be critic-gated, else HALT — route to `/shepherd:plant` + `/shepherd:spawn`. `task` target: the argument text itself is the instruction (no seed/plan lookup) — it must already be concrete and file-scoped enough to compile as one wave. |
| 2 | shepherd.toml | Scaffold-then-proceed: `shctx config init` if missing, emit `[CONFIG] scaffolded`, PROCEED. Non-blocking. |
| 3 | Disk pressure | HARD. `${CLAUDE_PLUGIN_ROOT}/scripts/df-guard.sh --min=12` before any cargo invocation; exit 1 INSUFFICIENT halts here. |
| 4 | Clean worktree / correct branch | HARD. `git status --porcelain` empty on the sprint's dev branch (or the operator-confirmed task branch) before wave 1 compiles. |

## Execution

Root loops the wave routine, one wave per Stage-Graph ready-set (or one wave total for a
single-shot `task`):

- **Compile** (`wave-routine.md §Per-wave compile`): one Dynamic Workflow per wave —
  `pipeline()` over FILE-DISJOINT steps, each step a `shepherd:coder` + adversarial
  `shepherd:auditor` pair, batched in a `parallel()`.
- **Brief** every coder+auditor pair with the hard-rule preamble VERBATIM
  (`wave-routine.md §Hard-rule preamble`): no git commit/push, no `gh` writes (stage +
  print only), `${CLAUDE_PLUGIN_ROOT}/scripts/df-guard.sh --min=12` before cargo, shared `CARGO_TARGET_DIR`
  deleted on final PASS, LOC budget measured by `${CLAUDE_PLUGIN_ROOT}/scripts/loc-count.py`, never eyeballed.
- **Gate, serially, after EVERY wave** (`wave-routine.md §Root gate`) — never delegated
  into the workflow: (1) `${CLAUDE_PLUGIN_ROOT}/scripts/journal-status.sh <run-journal.jsonl>` for the wave-return
  TRUTH; (2) `${CLAUDE_PLUGIN_ROOT}/scripts/loc-count.py <base_ref>` (`--from` if passed, else the sprint branch
  HEAD) against the wave's stated budget; (3) cross-step file-disjointness check; (4) the
  canonical workspace test gate, never concurrent with lane cargo builds; (5) the #242
  boundary-merge ledger drained — `shepherd run wave pending {run}` exits 0; exit 6
  (accepted-but-unmerged lanes remain) is a mechanical stop; (6) append-only MSD
  ledger entry, THEN the wave commit. A failure at 1–5 blocks 6: redo or halt, no commit.

## Fallback role

When Agent Teams is unavailable or a teammate-conductor stalls/fails, root falls back to
running the wave routine directly over every lane, in-context, with ZERO semantic drift from
the spawned path (`wave-routine.md §Fallback semantics`) — the same machine, a different
driver. A `@conductor`'s abbreviated §Lane walk is this identical routine scoped to one lane
(`wave-routine.md §Abbreviated conductor`); `/shepherd:start` is that same routine scoped to
the whole sprint, run by root instead of one conductor per lane.

## Hard stops

`/shepherd:start` MUST refuse when:

1. No approved plan exists for a `sprint_slug` target — route to `/shepherd:plant` +
   `/shepherd:spawn`.
2. Invoked from a teammate session (Check 0).
3. `${CLAUDE_PLUGIN_ROOT}/scripts/df-guard.sh --min=12` fails (INSUFFICIENT) — do not compile the wave.
