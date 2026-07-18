---
name: shepherd
slug: shepherd
version: 6.4.0
description: "Sprint-execution contract for the six-agent shepherd flock — dispatch law, root/sprint contracts, operator surface, principles. Use when running a /shepherd:spawn sprint."
metadata:
  triggers:
    - "/shepherd:plant"
    - "/shepherd:spawn"
    - "/shepherd:loop"
    - "/shepherd:focus"
    - "/shepherd:ctx"
    - "/shepherd:cleanup"
---

# /shepherd — sprint-execution contract

This file is the contract; detailed pipeline/flock mechanics live in `references/`.

Every `/shepherd:*` invocation MUST begin by reading `.claude/shepherd.toml` (or its `.local.toml` override) — it binds branch patterns, gate commands, artifact paths, MCP/CLI availability, and the resolved `{sprint_branch}`/`{patch_branch}`/`{paths.*}`/`{gates.*}`. Missing: warn and use `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` defaults. Broken: STOP and surface the error.

## Flock and tiers

The flock is closed at six.

| Role | Model | Job |
|---|---|---|
| `@engineer` | opus | Plan authorship from the seed. Once per sprint. Root-tier-exclusive under spawn. |
| `@critic` | sonnet | Adversarial gate on every plan above XS, every money-path/schema change, every merge to main. Root-tier-exclusive under spawn. |
| `@coder` | sonnet | Implementation. One per non-overlapping file scope, parallel waves. |
| `@auditor` | sonnet | Read-only review. Close swarm is ALWAYS 3–5 split by concern (code-quality, data-flow, dependency-topology, datastore-state, completeness); intro ≥3 in the engineer's sub-flock (codebase orientation). |
| `@worker` | sonnet | Bounded execution: monitoring, research, ops, MCP batches. |
| `@discovery` | sonnet | Read-only external research (documentation, web, release notes, MCP state) compiled into reports; codebase orientation belongs to intro-`@auditor`. NEVER mutates, grades, or dispatches. |

Two meta tiers plus the planter:

| Tier | Profile | Model | Adopted by |
|---|---|---|---|
| Root | `agents/shepherd.md` | inherit | Main chat under `/shepherd:spawn` (operator-explicit) |
| Conductor | `agents/conductor.md` | sonnet | Teammate lane session under `/shepherd:spawn` |
| Planter | `agents/planter.md` | opus[1m] | `/shepherd:plant`; also mid-spawn seed work |

## Dispatch law

Every flock dispatch MUST set `subagent_type: "shepherd:<role>"` (the registry auto-loads `agents/<role>.md`) and `model` per the role map, put the brief in `prompt` (NEVER inline-embed the agent body), and leave `team_name` unset. Teammate-conductor lanes are NOT flock dispatches: root stands them up via native teammate-spawn referencing `shepherd:conductor`, then drives them with `SendMessage`.

Tier reach: root dispatches `@engineer`, `@critic`, `@auditor`, `@worker`, `@discovery` and spawns teammate-conductors; root NEVER dispatches `@coder` — EXCEPT in **root-drives-workflows mode** (`/shepherd:start`, the Agent-Teams fallback with NO teammates active), where root drives the wave routine directly and dispatches `@coder`+`@auditor` steps ITSELF, running the same serial wave gate a conductor would (`references/wave-routine.md`). A teammate-conductor dispatches `@coder`, `@auditor`, `@worker`, `@discovery`; it NEVER dispatches `@engineer`/`@critic` (escalate `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` — `references/escalation.md §Halt-code index`) and NEVER spawns another teammate.

Forbidden dispatch constructions MUST be refused on sight:

| Halt code | Trigger | Refused by |
|---|---|---|
| `DISPATCH-MISSING-SUBAGENT-TYPE` | flock dispatch omits `subagent_type` or sets `general-purpose`/`Explore`/`Chat` | root + conductor |
| `DISPATCH-TEAMMATE-TYPE-MISMATCH` | a role other than `shepherd:conductor` stood up as a teammate | root |
| `DISPATCH-OFF-FLOCK` | `subagent_type` outside the closed six (or `shepherd:conductor`) | root + conductor |
| `TEAMMATE-NESTING-ATTEMPT` | a teammate-conductor sets `team_name`, runs `/shepherd:spawn`, or spawns its own tier | teammate-conductor |

These four are terminal — the dispatcher refuses to fire and surfaces (root) or escalates `SendMessage(to: lead, blocking: true)` (teammate). Teammate re-gating of a fixed plan is `WRONG-TIER-DISPATCH`; the self-contained `@engineer` carve-out and its `ENGINEER-TOPOLOGY-MISMATCH`/`ENGINEER-SUBFLOCK-VIOLATION` guards live in `references/flock.md §@engineer`. A specialist clears `DISPATCH-OFF-FLOCK` only via the decision tree in `references/flock.md §Dispatch`.

## Root contract

Work splits across the sprint's three sections, not by agent type:

- **INTRO**: root spawns the self-contained `@engineer` as a named teammate (DEFAULT) — the engineer team-lead runs his own discovery wave (MINIMUM 5: 2 `@discovery` + 3 intro-`@auditor`, scaled upward at his discretion) and his own `@critic` loop until GREEN, then returns ONE finalized plan and alerts root. Root dispatches NO discovery/orientation wave of its own — that is `ROOT-INTRO-USURPED` (`references/pipeline.md §INTRO`). Root materializes the plan and runs the operator-approval gate. Classic fallback (teammate-spawn unavailable): root fires the INTRO-COMBO-WAVE + a distinct `@critic` itself. The engineer is the ONLY INTRO teammate — conductor teammates spawn in BODY only.
- **BODY** (teammate-conductors): root projects the approved plan into lanes (vertical slices across waves), one teammate-conductor per lane via Agent Teams — never a workflow; lane count = teammate count, constant across waves. At each wave boundary a lane `SendMessage`s `WAVE-COMPLETE` and goes idle; root gates, commits, then refreshes the lane with a fresh teammate. Count LANES, never teammate-instances or "lanes per wave."
- **CLOSE** (root-direct subagents): root aggregates teammate payloads, dispatches the CLOSE-SWARM (3–5 `@auditor`) on the AGGREGATED output, then runs CLOSE-FINALIZE.

In coordinate mode root MUST actively drive (wake → act → probe → yield-to-events every wake), NEVER passive-wait after a dispatch, reserving operator pauses for the enumerated decision points (Stop-hook backstop: `skills/harness/SKILL.md §Capability enforcement`).

Root MUST NOT write source code, dispatch `@coder` directly (except in root-drives-workflows mode — `references/wave-routine.md`), nest a `/shepherd:spawn`, or silently absorb a teammate finding without materializing it. Git custody is root-exclusive: a teammate that runs `git rebase`/`merge`/`push`/`worktree` halts `TEAMMATE-GIT-WRITE` (`references/pipeline.md §CLOSE-FINALIZE`). Escalation payload: `references/escalation.md §Escalation payload`; Stage-Graph walk: `references/pipeline.md §Stage Graph`.

## Sprint contract

Every `dev.N` sprint is operator-equivalent to a full patch. A "small incremental sprint" is a category error — work is patch-grade, else a `@worker` dispatch or hotfix subgraph.

- Branch shape `v{X}.{Y}.{Z}-dev.{N}`, `N ∈ {0..sprints_per_patch-1}` (default `sprints_per_patch` = 10).
- **dev.0** — patch-grade setup + carryover + cleanup + ≥1 operator-visible feature or unblock.
- **dev.1 … dev.{last-1}** — patch-grade theme delivery: multi-wave, multi-step, SUBTRACT delta, release-notes-eligible.
- **dev.{last}** — wiring, polish, release-notes draft, closeout audit; release pipeline runs per `[release].driver` (`conductor` | `github-workflow` | `operator`).

At close a dev branch rebase-merges into the patch branch and is DELETED (origin + local); after dev.{last} the patch branch squash-merges into main and rollover cascade fires. NEVER direct-commit to `{branching.main_branch}`; NEVER merge to main without an explicit operator release signal or a sprint-through grant. Each sprint MUST ship real operator-visible value (real-work test).

Carry-forward discipline: `CRITICAL`/`HIGH` findings are NEVER deferred; a once-deferred item cannot be deferred again without an operator override; labels in `[ledger.non_issue_labels]` (`wontfix`/`tracking-future`/`design-question`/`rfc`) are NOT carry-forwards. Full carry-forward + issue-ledger lifecycle: `references/pipeline.md §CLOSE`. Rollover: `references/branching-model.md`. Gates: `references/pipeline.md §Gates`. Grades: `references/grading-rubric.md`.

## Operator surface

The planter (`/shepherd:plant`) is the framework's SOLE `AskUserQuestion` holder; it MUST surface every question through the `AskUserQuestion` tool, NEVER as chat/terminal prose (`INLINE-QUESTION-MISUSE`).

Execution sessions (root under `/shepherd:spawn`) carry NO `AskUserQuestion`; posture: proceed. They reach the operator ONLY through enumerated turn-ending pauses: pre-spawn approval gate, `--scope` gates, sprint-close PAUSE, dispute adjudication, `HARD-STOP`, explicit operator interrupt. They NEVER ask for confirmation or reassurance, stop on a decision with an obvious default (pick it, note it in the report), or invent a new stop point. Teammate-conductors NEVER contact the operator — they escalate to root via `SendMessage`; root surfaces it as a turn-ending report.

Mid-flight operator amendments are classified and traced, never silently absorbed. **Clarification** → dispatcher-patch: amend the lane brief inline, no `@engineer` re-dispatch. **Feature addition** → file a GH issue; current wave if file-disjoint, else a WAVE-IMPL node. **Production regression** → file one GH issue per symptom; dispatch a diagnostic `@worker` immediately (`[BUDGET]` 15 min, 40 tool calls), then HF `@coder`s. **Architectural decision** → `@critic` (current sprint) or a GH issue + spec stub (future). NEVER defer without a target (sprint slot + milestone + justification). HARD-STOP when an amendment implies secret/credential rotation, a changed sprint north-star, or a security rollback.

Every amendment gets one append-only ledger entry at `{paths.ctx}/dispatcher-patches/{sprint_slug}-pc-{N}.md` (fields: `type`, `timestamp`, `gh-issue`, verbatim `operator-quote`, `disposition`). The close report folds every entry into an "Operator amendments folded" table the `completeness` auditor checks for dispositions.

## Principles

**DURABLE ARTIFACT** — every top-tier dispatch MUST terminate in exactly one durable artifact (plan, seed, skill, report, registry row); reasoning that lives only in a transcript is spend without impact. Root manifests objectives into the codebase without authoring the work; the engineer produces exactly one finalized plan.

**SUBTRACT** — every sprint MUST end strictly net-negative on (tables, columns, deps, abstractions, LOC), scoped to `[gates.subtract_paths]` (production source only; reports, plans, handoffs are outside scope by construction). SUBTRACT is a CONSTRAINT, not a job description — deletion that misses the seed's deliverables also caps C+; both must pass. At close the `completeness` auditor measures it; net-positive without pre-authorization files `SUBTRACT-VIOLATION` (grade-cap C+):

```bash
git diff {patch_branch}..HEAD --shortstat -- $(read_subtract_paths_from_config)
```

If `[gates.subtract_paths]` is unset, the auditor falls back to the language skill's default globs (Rust: `crates/**/*.rs bin/**/*.rs **/*.toml **/*.sql`). Net-positive is pre-authorized ONLY by a seed `sprint_metadata` block declaring `expected_loc_delta` and `subtract_floor`. Ship net-negative while delivering features: (1) replace, don't append — every new line retires ≥1 old line; (2) inline single-callers; (3) collapse hollow wrappers (`references/flock.md §@auditor`); (4) delete deprecated migration shims same-sprint; (5) audit the dependency tree every dev.0, dropping ≥1 dep/patch; (6) remove dead feature flags on rollout completion; (7) inline single-impl traits no test mocks. Dependency-delta and abstraction-delta detection delegate to the project-language skill's §subtract-detection patterns (`rust`, `typescript`, `python`).

**MCP-over-CLI** — when an MCP is AVAILABLE (plugin loaded + `[mcp].<svc>` on), every WRITE goes through it and CLIs are read-only bulk enumeration only; when the MCP is UNAVAILABLE (not loaded or `[mcp].<svc> = false`), the CLI (`gh`, `psql`) is the SANCTIONED write fallback — flag it in the report, never a contract violation (the axiom dev.8 W0 incident: a whole-plugin absence left `gh` the only GH-write mechanism, then read as non-compliant):

| Service | MCP for | CLI OK for |
|---|---|---|
| GitHub | issue/PR create·update·comment, label apply, milestone, releases | `gh issue list`, `gh pr list`, `gh repo view` |
| Sentry | read-only via MCP | n/a |
| Supabase / Postgres | schema queries, advisor checks, migration apply, table inspection | read-only `psql` if MCP unavailable |
| Fly | Use `fly` CLI (no MCP) | All Fly ops |
| Datadog / Grafana | queries if MCP available | streaming logs |

When a service is `false` in both `[mcp]` and `[cli]` config, downgrade that Phase-0 mesh row to N/A and continue.

**Token + cache discipline** — every sprint open binds cache-first brief assembly (`references/flock.md §Brief assembly`), the conserve-tokens excellence bar (`skills/adaptation/SKILL.md §Excellence bar`), and the per-role cache-hit-rate targets in `skills/context/SKILL.md §Cache telemetry` for every brief, report, and commit; the telemetry hook records per-dispatch hit-rate and a sprint-aggregate rate <40% files a MEDIUM finding at close.

**How-to-work constitution** (latent-vs-deterministic split, skillify-success, context-window diagnostic, `DONE`/`DONE_WITH_CONCERNS`/`BLOCKED`/`NEEDS_CONTEXT` vocabulary): `references/operating-philosophy.md`.

## Invocation map

`/shepherd:spawn` is the primary command for substantive sprint work; sprint inferred from the current branch when no `sprint_slug` is given.

| Command | Profile / action |
|---|---|
| `/shepherd:plant [scope]` | `agents/planter.md §Plant mode` (opus[1m]) — authors patch-grade sprint seeds |
| `/shepherd:spawn [sprint_slug] [flags]` | `agents/shepherd.md` (root) — spawns teammate-conductors; operator-explicit only, refuses from teammate sessions. Flags `references/spawn-flags.md §--scope`; preflight `commands/spawn.md §Preflight` |
| `/shepherd:loop [task] [--max N] [--agent worker\|discovery]` | Pattern 6 Loop-Until-Done — each loop declares `--max`, each iteration emits `new_findings: true\|false`. `skills/motivation/SKILL.md §Loop discipline` |
| `/shepherd:focus` | Focus record + FOCUS-HEARTBEAT drift guard. `skills/motivation/SKILL.md §Focus record` |
| `/shepherd:ctx` | Context registry; backs the DEDUP-GATE fast path. `skills/context/SKILL.md` |
| `/shepherd:cleanup` | Prune stale/crashed teammate entries; operator-confirmed, NEVER auto-prunes live entries |
