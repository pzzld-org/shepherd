---
title: Flock Teammate Efficacy Analysis — v5.1.4 Design Pivot
date: 2026-05-19
author: analytical-agent
sprint: v5.1.4
status: complete
gates: v5.1.4 plan authoring
sources:
  - agents/engineer.md
  - agents/critic.md
  - agents/coder.md
  - agents/auditor.md
  - agents/worker.md
  - agents/discovery.md
  - agents/conductor.md
  - agents/planter.md
  - .artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md
  - commands/spawn.md
  - skills/shepherd/flock.md
---

# Flock Teammate Efficacy Analysis — v5.1.4

Research question: which flock interactions benefit from teammate composition, and which would suffer?
Platform constraint ground truth is D-API report at `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md`.

---

## § Per-agent matrix

### Definitions used in this table

- **Pattern A fit**: "yes" = agent does focused single-context work with no need to dispatch sub-agents; a fresh teammate session is appropriate. "no" = agent has a structural reason a teammate won't work well.
- **Token-budget delta**: compared to the same agent run as a subagent (compressed within the conductor's context). "significant" = role benefits meaningfully from a full independent context window.
- **Coordination cost (round-trips)**: minimum SendMessage calls for a single typical dispatch (brief out + completion in = 2 baseline; halts add 2/each).
- **Pattern B fit**: whether this agent benefits from talking to other flock teammates directly rather than routing through the conductor.
- **Risk**: failure modes specific to running this role as a teammate.

---

### @engineer

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Strong yes** |
| Token-budget delta | **Significant** — Opus 1M with max extended thinking; Phase 0 mesh exhausts conductor context fast |
| Coordination cost | 4–6 RT (brief out, optional SEED-DRIFT escalation ×1, plan in, optional critic-YELLOW revision ×2) |
| Pattern B fit | No — critic gate must be conductor-mediated; @engineer submits to critic via conductor only |
| Risk | Opus model cost × session overhead; TeammateIdle hook must fire reliably at plan delivery or conductor waits indefinitely |

**Reasoning.** The engineer runs exactly once per sprint, at `model: opus[1m]` with `thinking: max` (`agents/engineer.md` lines 3–5). Its work is entirely self-contained: read seed, run Phase 0 mesh across 14+ surfaces, load brainstorming + writing-plans skills, emit one plan file. No sub-agent dispatch (`agents/engineer.md` line 35: "DO NOT dispatch other agents"). The Phase 0 mesh alone — GH issue ledger, Sentry, Supabase, git log, prior close — can easily consume 100k+ tokens. Offloading this to a fresh Opus teammate context preserves the conductor's context for the walk. The coordination cost is bounded: 1 brief out, 1 plan in, at most one revision loop (conductor mediates critic gate). The principal risk is the Opus-as-teammate cost multiplier and the reliability of `TeammateIdle` for signaling plan completion (D-API §11: idle detection is graceful only — crashes don't fire it).

---

### @critic

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Conditional yes** (for L/XL scope; no for XS/S) |
| Token-budget delta | Moderate — critic needs to read the full plan + cited files; fresh context is beneficial when plan > 50k tokens |
| Coordination cost | 2 RT base (brief + verdict); +2 per pass-2 cycle |
| Pattern B fit | No — critic outputs a verdict to the conductor; direct peer comms add no value |
| Risk | Verdict parsing: conductor currently reads critic output inline; as a teammate, verdict must be serialized to a file the conductor polls or arrives via SendMessage |

**Reasoning.** The critic is read-only (`agents/critic.md` line 31: tools are `Glob, Grep, Read, Skill` only) and stateless — it loads the plan, applies six duties, emits a structured verdict. The coordinator's concern is verdict relay: in the current subagent model, the verdict is the Agent tool's return value. As a teammate, the verdict text must land in a file (`.artifacts/escalations/` or the plan directory) and arrive via `SendMessage`. The conductor's Step 1 §INTRODUCTION protocol (`conductor.md` line 125) already handles PLAN-GATE as a structured gate node — wiring it to a teammate SendMessage verdict is mechanical. The token-budget benefit is real for L/XL plans (critic reading a 600-line plan plus 5+ cited files) but marginal for XS/S scope. A conditional dispatch policy is appropriate: spawn as teammate for M+ plans, run inline or as subagent for XS/S.

---

### @coder

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Yes, with one major constraint** |
| Token-budget delta | Marginal to moderate — coders work on focused file scopes; fresh context is more important for correctness discipline than raw token headroom |
| Coordination cost | 2 RT baseline (brief out, CODER REPORT in); +2 per halt code (BRIEF INVALID, BASE-DRIFT, etc.) |
| Pattern B fit | No — coders are explicitly forbidden from talking to other agents (`agents/coder.md` line 46: "NEVER dispatch other agents") |
| Risk | **Git custody**: coder teammates commit in their worktrees; conductor (planter-as-lead) must own rebasing. Under spawn mode, the teammate-conductor cannot call git rebase (`conductor.md` line 69: Hard Prohibition #12). This creates a dependency chain: coder teammate → SendMessage "wave complete" → planter triggers rebase. Adds one extra RT per wave and requires the planter to be responsive. |

**Reasoning.** Coders already operate in isolated worktrees — the isolation model maps naturally to the teammate model. However, `agents/coder.md` line 38 explicitly prohibits building/compiling, and worktree coordination currently relies on the conductor rebasing all worktrees after a wave. Under the spawn model where a teammate-conductor dispatches coders, the teammate cannot rebase (Hard Prohibition #12 in `conductor.md`). It must SendMessage the planter, who then rebases. This adds exactly 2 round-trips per wave (wave-complete notification out + planter rebase-confirm in). The worktree-commit discipline is unchanged; only the rebase trigger shifts from conductor-inline to planter-mediated. This is manageable and already planned per `spawn.md` §WAVE-BOUNDARY-COMMIT-PROTOCOL. The 4-coder parallel wave (see § Wave patterns, below) is the key test case.

---

### @auditor

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Yes** — concern-split auditors are structurally independent |
| Token-budget delta | Moderate — auditor reads sprint diff, plan, cited files, MCP state; fresh context per concern avoids cross-contamination of findings |
| Coordination cost | 2 RT per auditor (brief out, AUDITOR REPORT in); swarm of 3–5 = 6–10 RT total, all in parallel |
| Pattern B fit | Partial — see below |
| Risk | `WORKTREE-DRIFT` halt risk: auditor must operate from sprint root, not a worktree (`agents/auditor.md` lines 51–58). Under teammate mode, auditor's pwd is its own context, not inherited from conductor. Brief must explicitly set `[SPRINT-ROOT]` and `[SPRINT-BRANCH]` with absolute paths. |

**Reasoning.** The auditor swarm is the most parallelism-intensive pattern in the flock. Each auditor has a non-overlapping concern scope and produces an independent report — classic teammate territory. The concern-split (`code-quality`, `data-flow`, `dependency-topology`, `datastore-state`, `completeness`) means the 5 auditors can all run as concurrent teammates without coordination. The fresh-context benefit is real: each auditor loads `superpowers:systematic-debugging` plus concern-specific skills, reads the full diff, and reasons independently. Context cross-contamination in a shared session (e.g., data-flow auditor influenced by code-quality findings) is a real failure mode that the teammate model eliminates. The `WORKTREE-DRIFT` check (`agents/auditor.md` line 52: `pwd_sha == expected_sha`) is satisfied naturally if the brief carries the absolute sprint root path and the teammate verifies it on entry.

Pattern B partial fit: the `completeness` auditor's job includes the sprint-pattern journal write and cache-telemetry table. If the `completeness` auditor could query the `code-quality` auditor's grade before writing the pattern delta table, that would be useful. But in practice, the completeness report writes after all concerns close (the pattern delta table in `agents/auditor.md` lines 191–198 is populated from the audit report files on disk, not from live peer queries). So the inter-auditor dependency is file-mediated, not live — no Pattern B needed.

---

### @worker

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Strong yes** |
| Token-budget delta | Low to moderate — workers are IO-bound (log tails, MCP batches); compute is not the constraint |
| Coordination cost | 2 RT (brief out, WORKER REPORT in); no halt complexity expected for well-formed briefs |
| Pattern B fit | No — workers execute single bounded deliverables; peer communication would violate the "one report at completion" contract (`agents/worker.md` line 68) |
| Risk | Budget tracking: worker has explicit time + tool-call budget (`agents/worker.md` line 65). Teammate sessions don't expose per-session tool-call counts to the lead. BUDGET EXHAUSTED halt must be self-reported via SendMessage — no platform-level enforcement. |

**Reasoning.** Workers are the clearest Pattern A fit in the flock. Their contract is "execute one bounded task, return one report" — exactly what a teammate session does. They are IO-bound (sustained log observation, MCP fan-out), so their resource profile is compatible with running in a sibling context without consuming the conductor's thinking budget. The main risk is budget enforcement: the platform has no mechanism to kill a teammate after N tool calls. Workers must self-halt with `BUDGET EXHAUSTED` — the same discipline required today in the subagent model, but now without the Agent tool's implicit timeout mechanisms.

---

### @discovery

| Dimension | Assessment |
|---|---|
| Pattern A fit | **Strong yes** — strongest fit in the flock |
| Token-budget delta | **Significant** — discovery absorbs read-only exploration specifically to preserve conductor context; that benefit doubles when discovery runs in a completely separate session |
| Coordination cost | 2 RT (brief out, DISCOVERY REPORT in); `discovery_capture.sh` hook auto-indexes on report receipt |
| Pattern B fit | **Potentially yes — the one exception** (see below) |
| Risk | Output-path discipline: `agents/discovery.md` line 59 restricts Write to `[OUTPUT-PATH]` only, path-checked by hook. Under teammate mode, the hook runs in the teammate's context. If the hook is not wired identically in the teammate session, the guard fails silently. |

**Reasoning.** Discovery was added to the flock specifically to offload read-only exploration from the conductor's context (`agents/discovery.md` lines 53–54: "you exist to preserve the conductor's reasoning depth by absorbing read-only exploration into your context, not theirs"). Teammates achieve this at the session level — a separate context window with its own token budget, completely isolated from the conductor. The discovery role writes exactly one output file and returns a structured DISCOVERY REPORT; that maps to a clean `TeammateIdle` signal with a well-defined output artifact. Multiple concurrent discoveries (INTRO-COMBO-WAVE dispatches 2–3 in one batch) translate to multiple sibling teammates — the platform supports this within the one-team limit.

**Pattern B partial fit for discovery**: the INTRO-COMBO-WAVE dispatches `@discovery` and `@auditor` (intro-mode) in one batch (`conductor.md` line 118; `flock.md` §@discovery dispatch mode). In the current model, all reports land on disk and the conductor assembles `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` for the engineer's brief. Under teammate mode, if multiple discovery teammates could signal each other that their reports are ready — letting one aggregate for the engineer brief — that would reduce lead round-trips. However, the platform's no-nested-dispatch rule (D-API §12) means a discovery teammate cannot spawn the engineer; the aggregation must still go through the lead. The Pattern B value is limited and the coordination complexity is high; defer to v5.2.x.

---

## § Wave patterns under teammates

### 4-coder parallel wave

**Assessment: translates cleanly with one additional coordination step.**

Under the current subagent model, the conductor dispatches 4 coders in one `Agent` batch and gets 4 returns in one pass. Under Pattern A (teammate mode), the conductor-teammate dispatches 4 coder subagents (still via `Agent` tool — this is allowed; D-API §12 confirms teammates CAN dispatch regular subagents). Each coder returns a CODER REPORT to the conductor-teammate, which then sends `SendMessage` wave-complete to the planter. The planter rebases and gates.

Net cost: +1 SendMessage (wave-complete) + planter rebase trigger + planter rebase-confirm. The parallelism within the wave is preserved. The coder-teammate nesting question does not arise because the conductor-teammate dispatches coders as regular subagents, not as sub-teammates (no nested teams per D-API §12).

The 2-4 teammate limit for `--parallel <N>` (`spawn.md` lines 149–151) means the 4-coder wave runs INSIDE a single conductor-teammate, not as 4 coder-teammates. This is the correct architecture.

### Audit swarm (3–5 concern-split auditors)

**Assessment: strong fit — the audit swarm is the best use case for multi-teammate dispatch.**

The concern-split design already assumes fully independent parallel agents. Under Pattern A, the conductor-teammate dispatches 3–5 auditor subagents in one batch (same as today). Under a hypothetical "auditors as teammates" model, the conductor-teammate would spawn 3–5 auditor siblings — but this hits the one-team-per-lead limit (D-API §11). The conductor-teammate IS the team; it cannot create sub-teams.

Therefore: **auditors stay as subagents dispatched by the conductor-teammate**, not as additional teammates. The audit swarm pattern is unchanged in structure; it just runs inside the conductor-teammate's context. The concern-isolation benefit (each auditor's reasoning is context-isolated) is preserved because subagent dispatches use separate Agent tool calls with separate compressed contexts.

### INTRO-COMBO-WAVE (3 @discovery + 2 @auditor intro-mode)

**Assessment: translates cleanly, with hook-wiring discipline required.**

The INTRO-COMBO-WAVE fires 5 agents in one batch before `@engineer`. Under Pattern A, these 5 fire as subagents inside the conductor-teammate. The discovery and intro-auditor reports land on disk via their `Write` tools. The conductor-teammate then assembles `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` and dispatches the engineer.

The engineer itself CAN be a sub-teammate of the conductor-teammate — but as noted in D-API §12, this would require nested team creation, which is forbidden. The engineer runs as a regular subagent with Opus model override (D-API §5: "Custom agent `model` frontmatter is now honored at spawn time").

The hook `discovery_capture.sh` (`agents/discovery.md` line 195) auto-indexes discovery reports. This hook must be wired in the conductor-teammate's session environment, not just the planter's. Verify hook registration is inherited by teammates (platform behavior under investigation per D-API Unknown §4).

---

## § The one-team-per-lead chokepoint

**Platform constraint (D-API §11):** "a lead can only manage one team. Must clean up before creating another."

Under Pattern A, the one-team IS the conductor-teammate. That team can contain multiple sibling conductor-teammates only under `--parallel <N>` mode (`spawn.md` §Check 5). For a single sprint:

```
Lead (planter)
  └── Team: shepherd-conductor-{sprint_slug}   ← ONE conductor
        ├── subagent: @engineer (via Agent tool)
        ├── subagent: @critic   (via Agent tool)
        ├── subagents: @coder × N (via Agent tool, one batch)
        ├── subagents: @auditor × 3–5 (via Agent tool, one batch)
        └── subagents: @worker, @discovery (via Agent tool)
```

The conductor-teammate has full `Agent` tool access to dispatch flock subagents. Flock members are subagents inside the conductor-teammate, not additional teammates. The lead's one-team slot is occupied by the single conductor-teammate.

**Maximum parallelism under `--parallel <N>`:**

```
Lead (planter)
  └── Team:
        ├── teammate: shepherd-conductor-{sprint_A}  ← coder wave A running
        ├── teammate: shepherd-conductor-{sprint_B}  ← coder wave B running
        ├── teammate: shepherd-conductor-{sprint_C}  ← coder wave C running
        └── teammate: shepherd-conductor-{sprint_D}  ← (max N=4 per spawn.md:149)
```

Each conductor-teammate independently dispatches its flock as subagents. The N=4 cap in `spawn.md` line 150 is specifically cited as preventing `TeammateIdle` handler saturation — a sound rationale. At N=4, the planter is triaging 4 simultaneous escalation channels, each of which may have its own coder waves, audit swarms, and HOTFIX subgraphs.

**Breakage point**: if a user attempts to dispatch auditors as additional teammates (6 auditors + 1 conductor = 7 teammates in one team), the platform does not document a per-team member cap explicitly. D-API §9 notes "There are no per-teammate config files" and the team config holds `members[]` with arbitrary count. However, the `TeammateIdle` handler saturation concern and the planter's ability to triage compound rapidly beyond 4–6 active members. The practical limit for shepherd is 4 conductor-teammates (`--parallel 4`), each internally running a full audit swarm as subagents.

---

## § Recommended Pattern A coverage — ranked

**Rank 1: @discovery**
Strongest theoretical fit. Discovery exists to absorb read-only context from the conductor; running as a teammate session achieves exactly that at the session level. Clean brief contract, well-defined output file, compatible with `TeammateIdle` signaling. The INTRO-COMBO-WAVE (3 discoveries) already runs 3 in parallel — translating to 3 concurrent subagents inside a conductor-teammate preserves this. If companion hooks are properly wired, `discovery_capture.sh` auto-indexes reports without extra coordination. Consider discovery as the first production validation target for Pattern A.

**Rank 2: @worker**
Workers are IO-bound, isolated, and single-deliverable. They map directly to the teammate lifecycle (start, work, idle, report). No subagent dispatch, no git coordination, no grading. The budget-enforcement gap (no platform kill mechanism) is a minor concern that already exists in the subagent model. Workers deployed as teammates inside a conductor-teammate run in parallel with Wave 1 coders exactly as designed.

**Rank 3: @engineer**
High value but high cost. Running the engineer as a subagent inside a conductor-teammate (or even as a top-level teammate) gives the Opus 1M context window full isolation from the conductor's walk state. Phase 0 mesh across 14 surfaces benefits most from fresh context. The coordination cost (4–6 round-trips for brief + potential revision cycle) is bounded and well-defined. The primary risk is Opus cost × teammate overhead; justify only for M+ sprints. This is also the role where "context window size matters most to quality" — the `agents/engineer.md` framing is explicit: "You are model opus because plan-quality determines whether 4–5 parallel coders produce coherent or contradictory work" (line 27).

**Rank 4 (tied): @auditor, @critic**
Both benefit from fresh context but are currently well-served as subagents. The auditor swarm's concern-isolation is already achieved via separate Agent calls. The critic's read-only stateless nature makes it cheap to run as a subagent. Promote to teammate if token pressure from large plans or large sprint diffs becomes measurable.

**Rank 5: @coder**
Coders map structurally to teammates but the git-custody chain adds round-trips. Under the spawn model, the conductor-teammate cannot rebase; coders already commit in their worktrees. The net effect: coder work as subagents is the cleanest path — the git discipline is already designed for subagent mode. Promote coder-as-teammate only if the conductor-teammate's context budget for brief assembly + rebase tracking becomes a measurable bottleneck.

---

## § Recommended Pattern B usage

**Verdict: None in v5.1.4. All flock comms flow through the lead (planter) or conductor.**

Justification: Pattern B (peer-to-peer flock messaging) offers benefits only where (a) the lead is a bottleneck on a latency-critical path and (b) the inter-agent protocol is simple and well-defined. Neither condition holds in shepherd v5.1.4:

1. **Conductor already batches parallel dispatches in one message** — the bottleneck is not message latency but context-assembly time before dispatch. Pattern B does not help with that.
2. **No role-level identity enforcement at the platform level** (D-API §9: "There are no per-teammate config files"). Any teammate can claim any role name in a `SendMessage`. Without platform-enforced role attestation, a discovery teammate receiving a `SendMessage` purportedly from an auditor teammate has no way to verify the sender's actual identity. This creates a TOCTOU identity gap.
3. **Race conditions on shared artifacts**: if two auditors tried to coordinate directly on a shared finding file, file-locking would be needed. The platform's task file locking (D-API §7) is designed for task-claim races, not arbitrary file write coordination. Shctx's SQLite lock primitives are the right tool, but wiring them into a peer protocol adds complexity with no sprint-v5.1.4 ROI.
4. **Completeness auditor's cross-concern dependency** (the one plausible Pattern B use case) is already file-mediated — concern auditors write reports to disk, completeness auditor reads them. No live IPC required.

Pattern B is worth revisiting in v5.2.x only if shepherd adds a long-running "standing flock" model where agents persist across sprints and need to share observations asynchronously. That is outside the v5.1.4 scope.

---

## § Recommended /shepherd:spawn re-design

The current `spawn.md` correctly frames the planter-as-lead / conductor-as-teammate split and the wave-boundary commit protocol. For v5.1.4, the spawn command should be extended in two ways: first, add an explicit **flock dispatch model selector** — a `--flock-mode [subagent|teammate]` flag (or a `shepherd.toml [spawn].flock_mode` key) that controls whether the conductor-teammate dispatches flock members as subagents (current default, lower round-trip cost) or as additional teammates (opt-in, higher isolation, reserved for engineer and discovery on M+ sprints). Default to `subagent`; expose `teammate` as experimental with a clear warning that it consumes the team's member slots and degrades `TeammateIdle` handler throughput. Second, add the **recovery sentinel** described in the D-API report: on `/shepherd:spawn` entry, scan `~/.claude/teams/` for a prior shepherd team config whose session IDs no longer exist in `~/.claude/sessions/`, surface them as orphaned with a one-line remediation prompt, and write `status=orphaned` to `parallel_assignments` — this prevents silent hang on resume after an interrupted spawn session. Neither change requires new platform APIs; both work within the current experimental feature surface confirmed in D-API §§5, 11, 12.
