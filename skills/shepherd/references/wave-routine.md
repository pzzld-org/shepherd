---
title: wave-routine
description: |
  The deterministic per-wave loop a single dispatcher runs to drive
  file-disjoint implementation steps to acceptance — every driver holding
  the Workflow grant (root, a teammate-conductor, a self-contained
  engineer) compiles the SAME Dynamic Workflow shape; in-context Agent()
  fan-out is the downgrade path, taken only on a confirmed absence (#263).
  Use when a root shepherd or a conductor drives a wave of coder+auditor
  steps outside a full agent-team fanout.
---

# Wave routine — one dispatcher, waves of dynamic workflows

The deterministic per-wave loop a single dispatcher runs to drive file-disjoint implementation steps to their acceptance outcomes — the wave's own coder/auditor steps are always SUBAGENTS, never nested Agent-Teams teammates. One routine, one vehicle, two scopes (§Per-wave compile, #263): root compiles the loop to a Dynamic Workflow over the sprint's lanes — standard, **and** the CONTINGENT fallback (in-context, root-tier) when Agent Teams itself is unavailable, root stays root either way; a `@conductor` runs it ABBREVIATED (§Abbreviated conductor) scoped to one lane, compiling the IDENTICAL Dynamic Workflow shape — `Workflow` ships in `@conductor`'s `tools:` frontmatter (#233) and that grant is LIVE (#263, CC 2.1.212, `skills/harness/SKILL.md §Workflow tool`), so this is the conductor's default mode, not a fallback. In-context `Agent()` dispatch is the DOWNGRADE path, taken only on a confirmed `WORKFLOW-VEHICLE-PROBE` absence and recorded with a `fanout_downgrade_reason`. This is the execution substrate for `/shepherd:start` (root) and the conductor's §Lane walk.

## Canonical scripts

This routine's determinism rests on three scripts. Every other file that cites them MUST use these exact signatures — do not paraphrase, do not re-derive:

| Script | Signature | Role in the wave | Issue |
|---|---|---|---|
| `scripts/df-guard.sh` | `[--min=<GiB>] [path]` | disk-pressure precheck, hard-rule preamble | #214 |
| `scripts/loc-count.py` | `<base_ref> [repo_path]` | net production Rust LOC assert, root gate #2 | #216 |
| `scripts/journal-status.sh` | `<journal.jsonl>` | wave-return TRUTH, root gate #1 | #213 |

## Per-wave compile

EVERY driver compiles ONE Dynamic Workflow script per wave — root and a teammate-conductor alike (#263): `Workflow` ships in `@conductor`'s `tools:` frontmatter (#233) and that grant is LIVE, so the conductor compiles the identical script root does, scoped to its own lane instead of the sprint. Same shape, same steps, same pairing, SAME runtime:

- `pipeline()` over FILE-DISJOINT steps, authored identically by whichever driver holds the grant — root over the sprint's lanes, a teammate-conductor over its own lane. Each step = one `shepherd:coder` (**both pins literal on the `agent()` call — `model:` + `agentType: "shepherd:coder"`, #255**; the Workflow runtime does NOT consult `shepherd.toml [models]` / `shctx models resolve coder` the way `Agent()` dispatch does, so that map is never read here; schema-forced structured report: `files_changed`, `loc_delta_rust`, `acceptance_outputs` with VERBATIM command output, `deviations`, `staged_gh_commands`, `notes`) PAIRED with one adversarial `shepherd:auditor` (same both-pins rule; independent hypothesis+falsification, re-executes EVERY acceptance predicate, returns PASS/REDO). Author every call through the `flockAgent()` wrapper (`skills/shepherd/SKILL.md §Dispatch law`); `workflow_model_guard.sh` refuses the script otherwise (`DISPATCH-MODEL-UNPINNED`, `DISPATCH-MISSING-SUBAGENT-TYPE`, `WORKFLOW-OFF-FLOCK`).
- REDO cap 3; `prescribed_fixes` threaded VERBATIM into the redo prompt — never a blanket re-run (`skills/shepherd/references/pipeline.md` §Wave review + REDO).
- Steps are FILE-DISJOINT: two steps never touch the same file (enforced by a root-gate check below).

Shape (schematic — the real JS API is `skills/harness/SKILL.md` §Workflow tool, not reproduced here; EVERY driver compiles this SAME script, root over the sprint's lanes and a teammate-conductor over its own lane; both #255 pins shown on every `agent()` call):

```
pipeline([
  parallel([
    pipeline([
      agent({ agentType: "shepherd:coder", model: "sonnet", prompt: step_1_brief }),
      agent({ agentType: "shepherd:auditor", model: "sonnet", prompt: step_1_review }),
    ]),
    pipeline([
      agent({ agentType: "shepherd:coder", model: "sonnet", prompt: step_2_brief }),
      agent({ agentType: "shepherd:auditor", model: "sonnet", prompt: step_2_review }),
    ]),
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

A `@conductor` driving this routine runs it ABBREVIATED: NO planning phase (root/engineer already authored the critic-gated plan; the lane brief IS the instruction) — execution only. It walks the lane's Stage-Graph ready-sets, dispatching each gate-free segment as a compiled Dynamic Workflow, same as root (#263; `Workflow` ships in `@conductor`'s `tools:` frontmatter, #233, and that grant is LIVE — the 6.3.9-era "unconditionally denied inside a teammate" reading, #220, is RETIRED as the standing instruction). The conductor's §Lane walk (`agents/conductor.md`) IS this routine scoped to one lane; the only differences from the root driver: (a) scope = one lane, not the sprint; (b) integration (rebase/merge/push) defers to root (`TEAMMATE-GIT-WRITE`). Dispatch mechanics are no longer a difference — both drivers compile the identical Workflow script (§Per-wave compile); a conductor hand-rolling in-context `Agent()` instead is the DOWNGRADE path, legitimate only after a `WORKFLOW-VEHICLE-PROBE` finds `Workflow` genuinely absent from the visible tool list and the conductor records a `fanout_downgrade_reason`. The pipeline SHAPE, hard-rule preamble, and root gate are IDENTICAL — which is WHY the routine is defined once, here.

## Fallback semantics

Agent Teams unavailable / teammate-conductors failing → root runs THIS routine directly over the sprint's lanes, absorbing every lane itself, with ZERO semantic drift from the spawned path. This is root's CONTINGENT fallback — it fires ONLY when Agent Teams itself is unavailable, and root's own per-wave dispatch still follows §Per-wave compile as written: root compiles each wave to a Dynamic Workflow exactly as it would with live teammate-conductors, because `Workflow` availability is independent of Agent Teams availability (`skills/harness/SKILL.md §Workflow tool`). This fallback is a DIFFERENT and still-valid concept from a teammate-conductor's own dispatch mode (§Abbreviated conductor) — but under the #263 inversion there is no longer a teammate restriction to contrast it against: a live teammate-conductor ALSO compiles a Dynamic Workflow as its default (same vehicle as root's), so the two sections differ only in WHEN each fires (Agent Teams absent vs a live teammate lane), never in what vehicle either one drives. Root's fallback is not a degraded mode; it is the same machine with a different driver (`/shepherd:start`, `commands/start.md`). Whichever driver is live, the three sections above bind identically in CONTENT — the same pipeline shape, the same hard rules verbatim, the same five root-gate checks, and now the same dispatch primitive (§Per-wave compile: a compiled Workflow at every tier, #263); only the scope (sprint vs one lane) and the git-integration authority (root-only vs deferred) differ.

---

`commands/start.md` (root driver) · `agents/conductor.md` §Lane walk (abbreviated per-lane driver) · `commands/spawn.md` (spawns conductors that run this abbreviated) · `skills/shepherd/references/pipeline.md` (gates, REDO) · `skills/harness/SKILL.md` §Workflow tool (the Dynamic Workflow primitive).
