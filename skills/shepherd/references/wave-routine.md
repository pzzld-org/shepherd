---
title: wave-routine
description: |
  The deterministic per-wave loop a single dispatcher runs to drive
  file-disjoint implementation steps to acceptance via Dynamic Workflows.
  Use when a root shepherd or a conductor drives a wave of coder+auditor
  steps outside a full agent-team fanout.
---

# Wave routine — one dispatcher, waves of dynamic workflows

The deterministic per-wave loop a single dispatcher runs to drive file-disjoint implementation steps to their acceptance outcomes via Dynamic Workflows, no agent-team fanout. Two drivers, one routine: root runs it directly (standard **and** the fallback when Agent Teams are unavailable — a degraded DRIVER, not a degraded routine); a `@conductor` runs it ABBREVIATED (§Abbreviated conductor) scoped to one lane. This is the execution substrate for `/shepherd:start` (root) and the conductor's §Lane walk.

## Canonical scripts

This routine's determinism rests on three scripts. Every other file that cites them MUST use these exact signatures — do not paraphrase, do not re-derive:

| Script | Signature | Role in the wave | Issue |
|---|---|---|---|
| `scripts/df-guard.sh` | `[--min=<GiB>] [path]` | disk-pressure precheck, hard-rule preamble | #214 |
| `scripts/loc-count.py` | `<base_ref> [repo_path]` | net production Rust LOC assert, root gate #2 | #216 |
| `scripts/journal-status.sh` | `<journal.jsonl>` | wave-return TRUTH, root gate #1 | #213 |

## Per-wave compile

The dispatcher compiles ONE Dynamic Workflow script per wave:

- `pipeline()` over FILE-DISJOINT steps. Each step = one `shepherd:coder` (model-pinned via `shctx models resolve coder`; schema-forced structured report: `files_changed`, `loc_delta_rust`, `acceptance_outputs` with VERBATIM command output, `deviations`, `staged_gh_commands`, `notes`) PAIRED with one adversarial `shepherd:auditor` (independent hypothesis+falsification, re-executes EVERY acceptance predicate, returns PASS/REDO).
- REDO cap 3; `prescribed_fixes` threaded VERBATIM into the redo prompt — never a blanket re-run (`skills/shepherd/references/pipeline.md` §Wave review + REDO).
- Steps are FILE-DISJOINT: two steps never touch the same file (enforced by a root-gate check below).

Shape (schematic — the real JS API is `skills/harness/SKILL.md` §Workflow tool, not reproduced here):

```
pipeline([
  parallel([
    pipeline([ agent(coder, step_1_brief), agent(auditor, step_1_review) ]),
    pipeline([ agent(coder, step_2_brief), agent(auditor, step_2_review) ]),
    // ... one inner pipeline() per file-disjoint step, one outer parallel()
  ]),
])
```

## Hard-rule preamble (every coder + auditor brief carries these verbatim — no paraphrase, no summary)

- No git commit/push, no `gh` writes — STAGE the text and PRINT the command (`staged_gh_commands`); commit custody is the dispatcher's.
- Secrets are NEVER echoed.
- GitHub Actions lifecycle is operator-owned.
- `scripts/df-guard.sh --min=12` MUST pass before ANY cargo invocation (#214).
- The lane's `CARGO_TARGET_DIR` is SHARED coder→auditor (warm cache, one tree) and DELETED on the wave's final PASS (#214).
- The LOC budget is stated per step; production LOC is measured by `scripts/loc-count.py` (#216), never counted in latent space.

## Root gate (serial, after the workflow returns; a failure blocks the wave commit)

Five checks, in order — the dispatcher runs them itself, never delegates them into the workflow:

1. `scripts/journal-status.sh <run-journal.jsonl>` — the wave-return TRUTH (#213; the harness task registry is best-effort, never trusted for return detection).
2. Deterministic LOC assert: `scripts/loc-count.py <base_ref>` vs the wave's stated budget (#216).
3. Cross-step file-disjointness check — no two steps touched the same path.
4. The canonical workspace test gate (`{gates}`; `skills/shepherd/references/pipeline.md` §Gates) — NEVER run concurrently with lane cargo builds (#214).
5. Append-only MSD (multi-step-dispatch) ledger entry in the plan: verdicts, LOC, deviations, run id + journal path (#213 — survives `/compact`). THEN the wave commit (`git commit -m "chore(dev.N/wave-K): ..."`); one commit per wave boundary is the one-wave loss horizon.

A failure at any of 1–4 blocks 5: no ledger entry, no wave commit, redo or halt instead.

## Abbreviated conductor

A `@conductor` driving this routine runs it ABBREVIATED: NO planning phase (root/engineer already authored the critic-gated plan; the lane brief IS the instruction) — execution only. It walks the lane's Stage-Graph ready-sets, compiling each gate-free segment to this per-wave routine. The conductor's §Lane walk (`agents/conductor.md`) IS this routine scoped to one lane; the only differences from the root driver: (a) scope = one lane, not the sprint; (b) integration (rebase/merge/push) defers to root (`TEAMMATE-GIT-WRITE`). Per-wave compile, hard-rule preamble, and root gate are IDENTICAL — which is WHY the routine is defined once, here.

## Fallback semantics

Agent Teams unavailable / teammate-conductors failing → root runs THIS routine directly over the sprint's lanes, in-context, with ZERO semantic drift from the spawned path. The fallback is not a degraded mode; it is the same machine with a different driver (`/shepherd:start`, `commands/start.md`). Whichever driver is live, the three sections above — Per-wave compile, Hard-rule preamble, Root gate — run byte-identical; only the scope (sprint vs one lane) and the git-integration authority (root-only vs deferred) change.

---

`commands/start.md` (root driver) · `agents/conductor.md` §Lane walk (abbreviated per-lane driver) · `commands/spawn.md` (spawns conductors that run this abbreviated) · `skills/shepherd/references/pipeline.md` (gates, REDO) · `skills/harness/SKILL.md` §Workflow tool (the Dynamic Workflow primitive).
