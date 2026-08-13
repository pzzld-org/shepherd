---
name: shepherd
slug: shepherd
version: 6.4.4
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

Every `/shepherd:*` invocation MUST begin by reading `.shepherd/shepherd.toml` (the canonical project binding, or its `.local.toml` override; the legacy `.claude/shepherd.toml` pre-v6.4.2 path is still honored forever as a fallback tier — `docs/configuration.md#config-resolution`) — it binds branch patterns, gate commands, artifact paths, MCP/CLI availability, and the resolved `{sprint_branch}`/`{patch_branch}`/`{paths.*}`/`{gates.*}`. Missing: warn and use `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` defaults. Broken: STOP and surface the error.

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

**Two tools, one law (#255).** `Agent(subagent_type: "shepherd:<role>")` and `Workflow`'s `agent({agentType: "shepherd:<role>"})` are the SAME dispatch law under two spellings — a Dynamic Workflow's `agent()` call is a flock dispatch exactly like an in-context `Agent()` call, and omitting the option is the SAME violation under either spelling: `DISPATCH-MISSING-SUBAGENT-TYPE`. A workflow script that fires `agent()` without `agentType` produces a generic workflow subagent — no `shepherd:<role>` body, no code-style/language skills, no CODER REPORT shape, no model pin — and nothing in that call's shape objects; the doctrine catches it only if this law is read as covering both spellings. `Workflow agent()` ALSO does NOT consult `shepherd.toml [models]` — the `shctx models resolve <role>` map that `Agent()` dispatches inherit is NOT read by the Workflow runtime, so `model` MUST be pinned literally on EVERY `agent()` call in the script; an unpinned call silently inherits whatever model the workflow's host session runs under (observed: opus instead of the mandated sonnet) — `DISPATCH-MODEL-UNPINNED`.

Author every Dynamic Workflow `agent()` call through a guarded wrapper, never a bare call — this is the sanctioned pattern, not a suggestion:

```js
function flockAgent(prompt, opts = {}) {
  if (!opts.agentType?.startsWith("shepherd:"))
    throw new Error("DISPATCH-MISSING-SUBAGENT-TYPE: agentType must be shepherd:")
  if (!opts.model)
    throw new Error("DISPATCH-MODEL-UNPINNED: Workflow agent() bypasses [models]")
  return agent(prompt, opts)
}
```

Forbidden dispatch constructions MUST be refused on sight:

| Halt code | Trigger | Refused by |
|---|---|---|
| `DISPATCH-MISSING-SUBAGENT-TYPE` | flock dispatch omits `subagent_type` (`Agent()`) or `agentType` (`Workflow agent()`), or sets either to `general-purpose`/`Explore`/`Chat` | root + conductor + engineer (#263 — every tier that may now author an `agent()` call) |
| `DISPATCH-TEAMMATE-TYPE-MISMATCH` | a role other than `shepherd:conductor` stood up as a teammate | root |
| `DISPATCH-OFF-FLOCK` | `subagent_type` outside the closed six (or `shepherd:conductor`) | root + conductor |
| `WORKFLOW-OFF-FLOCK` | a Dynamic Workflow `agent()` call sets `agentType` outside the closed six (or `shepherd:conductor`), or fires bare `agent()` without the `flockAgent` guard | root + conductor + engineer (#263 — every tier that may now author an `agent()` call) |
| `TEAMMATE-NESTING-ATTEMPT` | a teammate-conductor sets `team_name`, runs `/shepherd:spawn`, or spawns its own tier | teammate-conductor |

These five are terminal — the dispatcher refuses to fire and surfaces (root) or escalates `SendMessage(to: lead, blocking: true)` (teammate-conductor or self-contained `@engineer` — both teammate tiers, per the widened reach above). Teammate re-gating of a fixed plan is `WRONG-TIER-DISPATCH`; the self-contained `@engineer` carve-out and its `ENGINEER-TOPOLOGY-MISMATCH`/`ENGINEER-SUBFLOCK-VIOLATION` guards live in `references/flock.md §@engineer`. A specialist clears `DISPATCH-OFF-FLOCK`/`WORKFLOW-OFF-FLOCK` only via the decision tree in `references/flock.md §Dispatch`.

**Fan-out vehicle: the Dynamic Workflow, at every tier holding the grant (#263).** A team lead — root, a teammate-`@conductor`, or a self-contained `@engineer` — drives its OWN fan-out, and the vehicle is a compiled Dynamic Workflow, never a hand-rolled batch of individual `Agent()` calls. `Workflow` ships in the `tools:` frontmatter of `@conductor` and `@engineer` (#233) and that grant is LIVE: the 6.3.9-era "hard-denied inside a subagent" reading is RETIRED as the standing instruction. Who drives: the lead. What it drives: a Workflow.

**Probe once per session, before the FIRST fan-out (`WORKFLOW-VEHICLE-PROBE`).** Read your own visible tool list for the literal token `Workflow`. This confirms WHICH SUBSTRATE you are on, not whether a dormant grant went live. **Present** → you are on a live Agent-Teams teammate substrate: compile and dispatch a Dynamic Workflow. **Absent** → you are an Agent-tool subagent (the substrate was not live at spawn, so a "teammate" is silently just a subagent): `Workflow` is genuinely denied there, and in-context `Agent()` — the whole `parallel_with` clique in ONE message — is CORRECT and the only option available to you, not a downgrade to apologize for. Record the substrate either way. `FANOUT-VEHICLE-DOWNGRADE` fires only when a role CONFIRMED on a live teammate substrate hand-rolls in-context anyway; it never fires on a subagent substrate. NEVER `ToolSearch` for `Workflow` to answer this (`WORKFLOW-SELFCHECK-TOOLSEARCH`): `ToolSearch` resolves DEFERRED tools only and `Workflow` is a native top-level primitive, so a null there is a FALSE NEGATIVE BY CONSTRUCTION — it establishes nothing, neither presence nor absence, and is not evidence of "discovery-invisibility" (`skills/harness/SKILL.md §Tool presence`). The visible tool list is the only valid oracle.

**Any probe reported as a capability ABSENCE must state its positive control, or it is not a finding (`PROBE-FALSIFIABILITY`).** A negative result is evidence only if the instrument has been shown able to return the positive — state the positive control: concrete evidence the instrument CAN report "present" under the right conditions. No stated positive control → the result is not a finding and MUST NOT be filed as one; route it to an open question instead. This generalizes, one layer up, the discipline shepherd already imposes on `@auditor` findings — the Hypothesis + Falsification + Confidence triple (`agents/auditor.md §Per-finding contract`), backed by the mandatory `superpowers:systematic-debugging` falsify-don't-confirm skill — from a post-hoc audit finding to a lead's own capability probe of the substrate. Incident: `DF-68` (`.shepherd/runs/v645/dogfood.md`) — a day spent asserting a capability absence on two instruments neither of which could ever have returned the positive result even if the capability were present.

## Root contract

Work splits across the sprint's three sections, not by agent type:

- **INTRO**: root spawns the self-contained `@engineer` as a named teammate (DEFAULT) — the engineer team-lead runs his own discovery wave (MINIMUM 5: 2 `@discovery` + 3 intro-`@auditor`, scaled upward at his discretion) and his own `@critic` loop until GREEN, then returns ONE finalized plan and alerts root. Root dispatches NO discovery/orientation wave of its own — that is `ROOT-INTRO-USURPED` (`references/pipeline.md §INTRO`). Root materializes the plan and runs the operator-approval gate. Classic fallback (teammate-spawn unavailable): root fires the INTRO-COMBO-WAVE + a distinct `@critic` itself. The engineer is the ONLY INTRO teammate — conductor teammates spawn in BODY only.
- **BODY** (teammate-conductors): root projects the approved plan into lanes (vertical slices across waves), one teammate-conductor per lane via Agent Teams — never a workflow (the LANE is the Agent-Teams teammate; what that teammate then compiles for its OWN gate-free fan-out inside the lane IS a Dynamic Workflow — two different axes, and conflating them is `PRIMITIVE-INVERSION`, #263); lane count = teammate count, constant across waves. At each wave boundary a lane `SendMessage`s `WAVE-COMPLETE` and goes idle; root gates, commits, then refreshes the lane with a fresh teammate. Count LANES, never teammate-instances or "lanes per wave."
- **CLOSE** (root-direct subagents): root aggregates teammate payloads, dispatches the CLOSE-SWARM (3–5 `@auditor`) on the AGGREGATED output, then runs CLOSE-FINALIZE.

In coordinate mode root MUST actively drive (wake → act → probe → yield-to-events every wake), NEVER passive-wait after a dispatch, reserving operator pauses for the enumerated decision points (Stop-hook backstop: `skills/harness/SKILL.md §Capability enforcement`). This active-drive FOCUS-LOOP plus the close-time `shctx adapt roll` harvest is root's STANDING operating mode from team-liveness to CLOSE-FINALIZE — focus, motivation, and improvement are the default, the Stop hook only a backstop.

Root MUST NOT write source code, dispatch `@coder` directly (except in root-drives-workflows mode — `references/wave-routine.md`), nest a `/shepherd:spawn`, or silently absorb a teammate finding without materializing it. Git custody is root-exclusive: a teammate that runs `git rebase`/`merge`/`push`/`worktree` halts `TEAMMATE-GIT-WRITE` (`references/pipeline.md §CLOSE-FINALIZE`). Escalation payload: `references/escalation.md §Escalation payload`; Stage-Graph walk: `references/pipeline.md §Stage Graph`.

## Fan-out counterweight (#256)

Everything above pushes ONE direction: fan out by default, lane count = teammate count, gate-free segments compile to a Dynamic Workflow. Nothing in it pushes back, and a dispatcher following it to the letter can take down the machine — measured on FL03/axiom, 16 GB box: a verify phase of 12 agents each independently invoking `cargo` for the same expensive build drove free physical memory to 16 MB and swap to 8.6/9.2 GB; the kernel SIGKILLed a *teammate's* `cargo nextest list` mid-enumeration — the OS picked the victim, and it picked the lane doing useful work, not the excess fan-out. Cargo target dirs separately reached ~147 GiB. The six *fix* agents in that wave were correct — genuinely disjoint file scopes are exactly what the fan-out doctrine authorizes. The twelve *verify* agents were the error. This counterweight binds HARDER now, not softer: #263 widens WHICH tiers compile a Dynamic Workflow — root, teammate-conductor, and self-contained `@engineer` alike — so more of the machine can trigger this incident's shape, not just root. These five rules are the missing counterweight:

1. **Shared-resource clause.** File-disjointness authorizes concurrent WRITES; it does NOT authorize concurrent BUILDS. A wave fanning out N agents that each invoke the project's build command needs an EXPLICIT concurrency cap — disjoint `[FILE-SCOPE]` is the write test, not the build test.
2. **Verify-phase asymmetry.** *Fan out fixes. Verify once, centrally.* One workspace-wide gate run is both cheaper AND more rigorous than N agents spot-checking their own scopes — it is the only run that catches a cross-scope interaction no single agent's slice can see. Fanning out the verify phase instead of centralizing it requires a stated reason in the wave brief, not the default.
3. **Resource preflight.** The project declares its build's approximate peak memory and disk (`shepherd.toml` or the language skill's default); the dispatcher divides available headroom by that figure to get a concurrency cap BEFORE firing the wave. Rust-specific trap: `codegen-units` means the job count UNDERSTATES real `rustc` concurrency — a naive `-j$(nproc)` is already wrong before N agents multiply it.
4. **Watch swap-free, not disk-free.** Disk is the lagging indicator — minutes of warning. Swap is the leading one — seconds. Every disk warning in the incident above was downstream of an unnoticed memory problem; a dispatcher monitoring disk alone sees the crisis after it's unrecoverable.
5. **Kill your own, not the OS's choice.** If a build must be killed to recover headroom, the dispatcher kills ITS OWN largest allocator (the process it dispatched) rather than letting the OS choose — the OS will choose the gate, or a teammate doing useful work, exactly as it did in the incident.

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

**Availability means bounded latency, not presence (#257).** "AVAILABLE" above is binary on discovery — plugin loaded, `[mcp].<svc>` on — and that predicate is incomplete: a tool can be loaded, enumerated, resolved by `ToolSearch`, and still not answer. Measured 2026-08-03: `add_issue_comment` through a Docker-gateway MCP timed out at 1824s and then 1804s (~30 min each, two attempts) before the `gh issue comment` fallback posted instantly — an hour of wall-clock lost to a tool that was "available" the whole time by the discovery-only reading. An MCP write that has not returned within a stated budget is UNAVAILABLE for contract purposes, and the sanctioned CLI fallback applies WITHOUT counting as a violation:

- **Budget: 120s** for issue/PR writes — generous against a normal 1–3s call, tight against a genuine hang.
- The existing `[WARN] MCP <tool> unavailable — using <cli>` line covers the timeout case too, and MUST record the elapsed time (`[WARN] MCP <tool> unavailable — using <cli> (timed out after Ns)`) so the pattern is visible across sprints, not silently indistinguishable from a clean discovery-absence.
- **One retry, then commit to the fallback for the remainder of the dispatch** — no re-probing per call. Two independent 30-minute hangs (the measured incident) is the actual failure mode a single retry-then-commit rule prevents.
- **Bulk ledger writes are CLI-first outright** — a sprint close writing many comments never probes the MCP first: aggregate hang risk (N writes × a possible 120s budget each) is a real availability problem for the close itself, and `gh`'s output (a URL) is not meaningfully worse than the MCP's for a write of this shape.

Distinguish this from the axiom dev.8 W0 incident cited above (a whole-plugin ABSENCE left `gh` the only mechanism, and the resulting CLI use was misread at close as non-compliance): that was *chose the CLI correctly, graded wrongly*; a timeout under the old binary reading produces evidence of NEITHER "chose the CLI wrongly" nor "the MCP did not answer" — the elapsed-time `[WARN]` line above is what makes a close report able to tell the two failures apart.

**Provider-agnostic discovery (#110; enforced v6.4.3).** NEVER hard-assume an MCP namespace. Shepherd DISCOVERS a service's tools at runtime via `ToolSearch("github issues" | "sentry" | "supabase")`, which resolves whatever provider is connected — native `mcp__github__*`, Composio, or a Docker-gateway `mcp__MCP_DOCKER__*` — by capability, not by a fixed token.

**No agent frontmatter names a provider token at all (v6.4.3).** Until v6.4.3 the doctrine above said the `mcp__plugin_*` entries in a `tools:` line were "the default-provider OFFER, not a hard dependency" — while 129 such tokens shipped across eight agents and `commands/start.md`, so the doctrine and the manifest disagreed and the manifest is what the platform reads. Every one of those tokens named ONE server's ONE naming scheme, and shepherd can guarantee none of them: the same GitHub capability is `mcp__github__*` natively and `mcp__MCP_DOCKER__*` behind a Docker MCP gateway, which is how the operator's own access is routed. A token naming an unconnected server is dead weight at best; read as a dependency it binds the plugin to a toolset the installing user may simply not have. The frontmatter now carries ZERO provider tokens; every role that touches a service grants `ToolSearch` instead, and `hooks/tests/lint_agent_capabilities.sh` fails on any re-added `mcp__*` token or on a service-touching role missing `ToolSearch`. Name the CAPABILITY you need in prose, never the token — the same hint-don't-bind discipline `@engineer`'s optional `superpowers:*` skills already use.

A `ToolSearch` that returns nothing for a service is a DISCONNECTED-or-absent provider (#110): degrade to the sanctioned CLI fallback (`gh` / `psql`) and emit `[WARN] MCP <svc> unavailable — using <fallback>`, never a silent tool failure.

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
