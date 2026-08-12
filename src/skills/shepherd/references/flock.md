---
title: flock
description: "Per-role dispatch reference for the six-agent flock — briefs, write boundaries, per-role algorithms, teammate bridge. Use when dispatching a flock role or setting brief/worktree boundaries."
---

# The flock — dispatch reference

Six agents form the closed flock: @engineer, @critic, @coder, @auditor, @worker, @discovery. Each system prompt lives in `agents/<role>.md` (the registry loads it on dispatch). This file is the conductor's operational reference — when to dispatch, per-role algorithms, write boundaries — and NEVER duplicates an agent body.

## Dispatch

**Every flock dispatch (mandatory):**
1. Set `subagent_type: "shepherd:<role>"` — the registry auto-loads `agents/<role>.md`. NEVER omit it or use `general-purpose`/`Explore`/`Chat`.
2. Set `model` per the table.
3. Put the task brief in `prompt` — NEVER duplicate the agent body.
4. Leave `team_name` UNSET — reserved for root teammate-conductor spawns under `/shepherd:spawn`.

| Role | Model |
|---|---|
| @engineer | opus |
| @coder, @critic, @auditor, @worker, @discovery | sonnet |

Refuse these combinations on sight (canonical definitions: `skills/shepherd/SKILL.md §Dispatch law`):

| Combination | Code |
|---|---|
| `subagent_type` missing / `general-purpose` / `Explore` / `Chat` | `DISPATCH-MISSING-SUBAGENT-TYPE` |
| `team_name` set + `subagent_type ≠ shepherd:conductor` | `DISPATCH-TEAMMATE-TYPE-MISMATCH` |
| `subagent_type` outside the six + no specialist clearance | `DISPATCH-OFF-FLOCK` |
| Teammate-conductor sets `team_name` (any value) | `TEAMMATE-NESTING-ATTEMPT` |
| Teammate-conductor dispatches @engineer / @critic | `WRONG-TIER-DISPATCH` |

**Cascade — the plan IS the program.** The conductor walks the extracted `## Stage Graph` mechanically (`shctx graph next`/`mark`) — no fresh sequencing mid-sprint; `parallel_with` nodes fire in ONE Agent message. Gate-free agent-fanout segments compile to a Dynamic Workflow run out-of-context; the conductor NEVER hand-rolls in-context fan-out where a compiled workflow is required — re-affirmed, not missed, by the #263 fan-out-vehicle inversion (`skills/shepherd/references/pipeline.md §Dispatch patterns`, `skills/shepherd/references/wave-routine.md §Per-wave compile`).

**Generosity — only @engineer is count-capped** (once per sprint). @critic per gate, @coder per step, @auditor (intro + close swarm 3–5 + mid-body waves), @worker per bounded task, @discovery across all six patterns — all freely repeatable; the 3–5 close swarm and intro waves are FLOORS, NEVER ceilings. Extra dispatch is context-cheap (gate-free fan-out runs out-of-context); inlining a flock-shaped task to "save context" is a self-handicap. Reach for the lane, the swarm, the loop.

**Specialist — closed at six + narrow exceptions.** Route EVERY non-flock dispatch through the flock-first tree: **Q1** plan authorship / critic-gating / close-audit grading / in-Stage-Graph code → FLOCK-ONLY, no substitute (STOP); **Q2** bounded research/monitoring/triage → @worker, read-only orientation/synthesis → @discovery (DEFAULT to the flock lane); **Q3** dispatch a pre-authorized specialist (in `shepherd.toml [specialists].allowed`, else the default catalog) ONLY when ALL hold — its description was READ this session, it is read-only or clearly-bounded-write, and a flock dispatch would be measurably worse (surface on the operator log; tag the audit); **Q4** none clear → HALT `SPECIALIST-UNCLEAR`. NEVER improvise `general-purpose`/`Explore`.

A specialist is a subagent — from the visible available-agents list, dispatched via `Agent({subagent_type})`. NEVER `ToolSearch` for an agent/subagent/teammate type: it returns nothing by design and a miss is NEVER evidence of absence — the `SUBAGENT-DISCOVERY-TOOLSEARCH` anti-pattern (`ToolSearch` discovers deferred TOOLS, never agents). An expected-but-unregistered specialist → surface `/reload-plugins`, then degrade to @worker (annotated) or HALT `SPECIALIST-UNAVAILABLE`; NEVER degrade silently.

## Brief assembly

Every brief orders sections **stable framing first, variable content last** so the stable prefix stays byte-identical across a sprint (the runtime reuses the conversation prefix and framing behavior stays coherent).

- **Stable block** (this order): `[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`. Copied verbatim across every dispatch of a role in a sprint, NEVER customized; keep it thin — it points at `agents/<role>.md`, never restates it.
- **Variable block** (this order): `[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]` (last two: coder dispatches only).

Every stable section MUST precede every variable section — a variable section emitted first busts the prefix. The genuinely-cached prefix is the agent system prompt + tools (registry-injected); for `--scope >= patch` / long autoruns set `ENABLE_PROMPT_CACHING_1H=1`. The completeness auditor verifies ordering post-hoc (LOW per violation; MEDIUM if > 30%).

**Files-as-context-bus.** A lane brief carries the lane-plan PATH — `{run_dir}/lanes/{lane}/plan.md`, conductor-owned (`agents/conductor.md`) — never a pasted plan slice; the dispatched role reads the file. Symmetrically, a dispatched role writes its full output to a file under `{run_dir}/lanes/{lane}/reports/` and returns ≤15 lines to the dispatcher (verdict + pointer) — the file is the payload, the return is the receipt.

**@coder brief contract — seven exact bracketed headers** the coder's Startup Protocol parses (drift halts the coder with `BRIEF INVALID`): `[SKILLS]` `[CONTEXT-INVENTORY]` `[DO-NOT-DUPLICATE]` `[USER-STYLE]` `[FILE-SCOPE]` `[NON-GOALS]` `[ACCEPTANCE]`. Supporting lines every coder brief carries: `[WORKTREE]` (path / branch / cut-from / commit template), absolute repo path + sprint branch, `ONE cargo check after all code is written`, `No new build-manifest dependencies without conductor approval`, auto-injected `[CODE-STYLE]` + `[DB-CONTEXT]` (canonical types to reuse), and `[SIBLING-LANES]` (every other lane's `[FILE-SCOPE]` + produced symbols).

**Required-Skills matrix — the conductor MECHANICALLY computes `[SKILLS]`; NEVER trusts the engineer's list:** `[skills.mandatory]` (always `code-style`) + one language skill per `[FILE-SCOPE]` file (`.rs`→`rust`, `.py`→`python`, `.ts`/`.tsx`→`typescript`, `.go`→`go`) + every `[skills.detection]` match + `[skills.by_domain]`. A close-time mismatch is a `SKILL-DRIFT` finding. `code-style` is additive to language skills, NEVER a substitute.

**Brief-Validity checklist = the runtime body of the DEDUP-GATE node** (`skills/shepherd/references/pipeline.md §DEDUP-GATE`). The Agent batch does NOT fire until: all seven sections present + non-empty; `[WORKTREE]` cut from the sprint branch pre-dispatch; `[SKILLS]` equals the mechanical computation; `[CONTEXT-INVENTORY]` cites `{paths.ctx}/canonical-types.md` per concept + ≥1 existing symbol per new module (verified absolute path); `[FILE-SCOPE]` file-disjoint across the wave; `[ACCEPTANCE]` runnable, never prose; and the conductor has RUN every `[DO-NOT-DUPLICATE]` grep with each result equal to expected — a hit → DISPATCH BLOCKED, brief amended to "wire to existing". A coder-time hit → `DUPLICATION RISK: <pattern> hit N times` and halt; a stale entry → `CONTEXT-INVENTORY STALE` and the conductor re-meshes. When 2+ lanes write the same `.shepherd/ctx/*.md`, the brief carries a `[SHARED-FILE-RULE]` (section line-range, footer-append, or single-author) for clean cherry-picks.

## @engineer

Opus, once per sprint (§1 INTRODUCTION). Turns seed + context into one multi-phase plan whose `## Stage Graph` (`skills/shepherd/references/pipeline.md §Stage Graph`) is the binding dispatch contract. Loads `superpowers:brainstorming` + `superpowers:writing-plans` on dispatch, plus `[skills.mandatory]` + per-language + matched domain skills.

**Self-contained mode:** under `/shepherd:spawn`, root MAY spawn @engineer as its OWN named teammate (native teammate-spawn, NEVER an Agent/Task subagent) that runs its own read-only sub-flock + critic gate in-session and returns a hash-tied critic-proof; root accepts via a thin verify gate, not a re-critique. Full contract + halt codes (`ENGINEER-TOPOLOGY-MISMATCH`, `ENGINEER-SUBFLOCK-VIOLATION`, `WRONG-TIER-DISPATCH`): `skills/shepherd/references/pipeline.md §INTRO`.

**Phase-0 mesh** is a coverage spec, not a personal re-query mandate: by default the intro discovery wave runs first and injects `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]`; the engineer consumes those as authoritative, verifies gaps only, and acts on findings. It self-runs the rows ONLY when the wave did not fire. Row 1 (open-issue ledger via `shctx issues classify`) is CRITICAL — enumerate the FULL open-issue space, not just the current milestone, and surface non-current-milestone CRITICAL/HIGH as drift risks; NEVER silently absorb them. Row 10 (`shctx adapt priors --metrics --lessons`) drives measured wave/lane sizing + `prior:<mem_id>` citations. If the mesh shows the seed premise changed, prepend `[SEED DRIFT]`; the plan is NOT written until the conductor amends the seed (mechanical vs substantive classification: `skills/shepherd/references/pipeline.md §Phase-0 amendment`). Full mesh-row catalog + plan-document templates: `agents/engineer.md`.

A bug spotted during mesh is NEVER fixed inline (an @engineer-signed commit is a discipline violation) — list it as a Wave 0 coder step. **Plan-quality bar (all MUST hold before delivery):** every coder step's seven sections fully populated; `[CONTEXT-INVENTORY]` cites verified absolute paths; `[DO-NOT-DUPLICATE]` names every new identifier; sibling `[FILE-SCOPE]` disjoint; `[ACCEPTANCE]` runnable; Stage Graph present, complete, matching wave/step counts, encoding Pattern B (`parallel_with`) + WORKER-IO at Wave 1 START; each coder step owns ≤ 3 MAY-MODIFY files (a single-file step > 300 LOC may stay one). **Revision protocol:** GREEN → READY; YELLOW → revise ONCE then critic pass-2 (pass-2 GREEN → READY, else ESCALATED); RED (seed-level) → ESCALATED, seed amended. The engineer revises at most ONCE without root intervention.

## @critic

Sonnet, single, sequential — BEFORE any non-XS coder dispatch, money-path / schema / architectural changes, or any merge to `main`. Output shape: `agents/critic.md`. Four verdicts, NOT interchangeable:
- **PROCEED** — sound; dispatch, no revision.
- **PROCEED WITH CHANGES** — conductor folds a note/emphasis into briefs inline; no engineer revision.
- **RECONSIDER** (YELLOW) — the engineer MUST re-write a bracketed section or re-decompose a wave; revise ONCE, re-critique. Boundary test: does an engineer need to re-write any bracketed section in any coder brief? → yes = RECONSIDER.
- **REJECT** (RED) — seed-level; conductor escalates to operator and amends the seed before re-dispatch.

Pass-2 flag classification (pass-1 flags always return to the engineer): `dispatcher-patch` (conductor applies inline, informal pass-3 for verdict) vs `substantive` (ESCALATE, never block-and-proceed). A prose-only acceptance is a seed defect → reject at PLAN-GATE with `PLAN-MISSING-OUTCOME-VERIFICATION` (owned by `skills/shepherd/references/pipeline.md §Gates`). New abstractions need ≥ 3 concrete use cases; new wrapper types must pass the §@auditor justification test. The sprint-pattern duty is OPTIONAL — engaged only when the brief carries `shctx adapt` data; NEVER demand data not provided.

**Necessity audit — Cargo feature reachability — resolve the FULL feature graph before declaring a dependency or feature "missing".** Direct-declaration absence is NOT the same as feature unreachability. A required feature counts as *reachable* if any one of these holds:
- (a) it is named in a crate's `default` feature set;
- (b) it is enabled by any other reachable feature in `[features]` — including `foo = ["bar"]` chains and umbrella/SDK `full = [...]` rollups;
- (c) it is pulled in through an optional dependency, via `dep:x` or the `x?/feat` weak-dep syntax;
- (d) it is requested by a workspace member, by `--features` / `--all-features` on the close-gate command, or by a `cfg(feature = "…")` guard that the gate exercises.

Worked example (a downstream false positive this checklist exists to prevent): `bin/node` declares `app-core = { features = ["full"] }`; `app-core` declares `full = ["app-runtime?/full"]`; `app-runtime` declares `full = ["native-runtime"]`. So `native-runtime` is already reachable in `bin/node` by transitive feature unification — adding a direct `app-runtime = { features = ["native-runtime"] }` edge duplicates a dependency and may violate the umbrella-crate convention. Do NOT flag it. Only a feature with **no path from any root** (default, CLI, workspace, or another reachable feature) may be raised — and even then as a **non-CRITICAL observation** carrying a "verify with `cargo tree -e features` / `cargo hack`" instruction, never a hard CRITICAL, unless it gates compiled code that the close-gate `cargo test --workspace --features full` would provably never exercise. When the suspected-missing crate is a dependency of the project's umbrella/SDK crate, check that crate's `full` rollup for the sub-feature before flagging anything at all.

## @coder

Sonnet, one per step (a single non-overlapping `[FILE-SCOPE]`). Zero-overlap coders MUST be dispatched in the SAME message; sequential dispatch of parallel-safe coders is a process violation. Sequential is REQUIRED for schema migrations (single writer), rename cascades across public re-exports, or a critic-flagged dependency. Progress bar: ≥ 50 LOC per coder; < 30 LOC merge with adjacent; > 8 files split. Coders run ZERO build/compile/lint AND ZERO git (write files, list them in the report, never commit — read-only `git status`/`diff`/`log`/`show`/`rev-parse` only; `coder_git_guard.sh` enforces it, `CODER-GIT-WRITE`). The conductor runs the gate sequence once per wave after all rebases, and stages+commits each coder's reported files only after the wave-review returns PASS — a REDO re-runs the named coder over the SAME uncommitted files, nothing to unwind (`skills/shepherd/references/pipeline.md §Gates` + §Wave review + REDO).

**Cross-lane dependencies** — pause-for-dependency is retired: a needed symbol that is missing, outside `[FILE-SCOPE]`, and not owned by a wave-sibling is a graph edge the engineer composes (the compiled segment await-orders it); the coder does NOT pause. In-sprint-but-unsequenced → leave the WIP files in the worktree, note them in the report, file a `BRIEF-AMENDMENT REQUEST` (never a self-commit). Out-of-scope → finish assigned scope, file a finding at close. NEVER expand scope silently or add a TODO; scope overlap → `SCOPE OVERFLOW`.

**Work bound to tracking** — NEVER write `TODO`/`FIXME`/`XXX`/`HACK` (the `code-quality` auditor grade-caps the sprint on any hit). Every intentional gap uses a language primitive citing the GH issue `#N`:

| Language | Unimplemented path | Unsupported arm | Migration window |
|---|---|---|---|
| **Rust** | `todo!("see #{N}")` or `unimplemented!("{description}; see #{N}")` | `unimplemented!("{reason}; see #{N}")` | `#[deprecated(since = "{version}", note = "{instructions}; see #{N}")]` |
| **TypeScript/JS** | `throw new Error("TODO see #{N}")` | `throw new Error("{reason}; see #{N}")` | `/** @deprecated {instructions}; see #{N} */` |
| **Python** | `raise NotImplementedError("see #{N}")` | `raise NotImplementedError("{reason}; see #{N}")` | `warnings.warn("{instructions}; see #{N}", DeprecationWarning, stacklevel=2)` |
| **Go** | `panic("TODO see #{N}")` | `panic("{reason}; see #{N}")` | `// Deprecated: use Y instead; see #{N}` |
| **SQL/Migrations** | `-- NOT YET: see #{N}` (comment in migration file) | n/a | `-- DEPRECATED: see #{N}` |

**INSIGHTS** — a coder MAY append an optional `## INSIGHTS` block (kinds `relocation`/`extension`/`duplication`/`consolidation`/`gap`/`nit`) for the next engineer; taxonomy + template + capture hook are canonical in `skills/adaptation/SKILL.md §INSIGHTS`. NEVER use it for scope changes (file a `BRIEF-AMENDMENT REQUEST`) or style venting. A project's `.claude/doctrines/*.md`, injected into the brief preamble, WIN over framework guidance on conflict. A dedup-grep hit is REUSE-if-it-fits, else JUSTIFY-NEW naming the missing invariant. Body: `agents/coder.md`.

## @auditor

Sonnet. SWARM, min 3 max 5, always parallel, split by concern NEVER by file: `code-quality`, `data-flow`, `dependency-topology`, `datastore-state`, `completeness`. Trigger: every close; before any patch-branch merge; after any money-path wave; on suspected regression. Every wave also gets ≥ 1 @auditor in `mode: wave-review` returning `review_verdict: PASS|REDO` against the four-item checklist — the conductor emits `WAVE-COMPLETE` only on PASS, dispatched Pattern B, concurrent with Wave N+1 coders (`skills/shepherd/references/pipeline.md §Wave review + REDO`). Write path (EXACT): `{run_dir}/audits/audit-<concern>.md` (intro mode `{run_dir}/audits/intro-audit-<concern>.md`) — RUN-scoped, so an audit never lands under `{paths.docs}`; the `audits/` directory plus the `audit-` prefix keeps it inside the @auditor write-allow path (`AUDITOR-WRITE-PATH`, `lock_guard.sh`). Produces a report + a GH issue per HIGH/CRITICAL + a grade A–F (`skills/shepherd/references/grading-rubric.md`). Body: `agents/auditor.md`.

**Read-only** — auditors REPORT, NEVER Edit/Write source or config, apply a fix "even if obviously correct", run migrations, or edit another auditor's report. The sole write is the report; the sole mutating MCP is `issue_write`. Enforced by three layers — `tools:` allowlist, `lock_guard.sh` path-scope hook, `lint_agent_capabilities.sh` regression guard (`skills/harness/SKILL.md §Capability enforcement`). Gates run AT SPRINT ROOT (where `shepherd.toml` lives), NEVER inside a coder worktree — a stale worktree yields false-CRITICAL findings: `WORKTREE-DRIFT`.

**Method — hypothesis-driven.** Every finding carries a **Hypothesis** + a **Falsification attempt** (the exact command / grep / query that would DISPROVE it, plus its result) + a **Confidence** (HIGH / MEDIUM / LOW). A finding without the triple, or one at LOW confidence, is not a finding → `## Open questions`; a hypothesis the falsification disproved → `## Verifications`. Weight effort by class: read `shctx adapt priors --lessons`; classes ≥ 70% verified falsify with a lower bar, classes < 30% demand strong falsification. Empty registry → framework priors:

- WORKTREE-DRIFT: 90%
- BASE-DRIFT: 90%
- STAGE-GRAPH-VIOLATION: 80%
- DUPLICATION RISK: 75%
- wrapper-must-earn: 60%
- SUBTRACT violation: 70%
- chronic carry-forward: 70%

**Wrapper-grep gate** (`dependency-topology` concern): new lane-introduced hollow-wrapper hits ARE a sprint-fail; pre-existing hits log to `{paths.ctx}/wrapper-debt-ledger.md`. Rust detection: `rg -n 'pub struct \w+ \{[\s\n]*pub params: \w+,?\s*\}' --type rust` (per-language greps live in each language skill). A wrapper earns existence ONLY via a type-system-enforced invariant, a borrowed scope over live state, a shared-allocation pattern, or ≥ 3 substantive trait/interface methods; otherwise it is hollow — delete it. Carry-forward + GH discipline (CRITICAL/HIGH never deferred; milestone = version; NEVER create `dev.N` labels): `skills/shepherd/references/pipeline.md §CLOSE`.

## @worker

Sonnet, single or parallel, always bounded (defined deliverable + budget). Dispatch @worker (NEVER inline) when ANY holds: IO-bound > 5 min; > 10 sequential MCP calls; a structured non-code deliverable that need not enter conductor context; runnable in parallel without contention; inlining would burn > ~1000 tokens. Inline ONLY a one-line answer needed immediately for the next dispatch decision. Workers dispatch at Wave 1 START (IO-bound, non-competing); the conductor NEVER sits on a Monitor stream.

Brief sections: `[DELIVERABLE]` / `[SOURCES]` / `[BUDGET]` (time + max tool calls) / `[FORMAT]` / `[OUT-OF-SCOPE]` (`Do NOT modify code/data/config unless the deliverable IS .md; do NOT dispatch other agents; do NOT exceed the budget`). `HALT CONDITIONS` are set by the conductor, never chosen by the worker. Workers are leaf dispatches — they NEVER compose flock work, NEVER browse beyond `[SOURCES]`. Patterns: issue-ledger triage, deploy monitor, branch cleanup (recommend, never execute), research summary, file organization. Cross-lane deps + `## INSIGHTS`: same as @coder. Body + pattern catalog: `agents/worker.md`.

## @discovery

Sonnet, read-only sixth lane; single or parallel — many fire in one Agent batch, cap 5 concurrent, else batch into one broader question. NEVER mutates, dispatches, grades, or proposes code (FACTS + QUESTIONS only). Write is path-restricted to `[OUTPUT-PATH]` = `{run_dir}/reports/discovery-<id>.md` (`DISCOVERY-WRITE-PATH`, `lock_guard.sh`) — RUN-scoped, never `{paths.docs}`; any other target is denied. State-modifying Bash or a write-MCP call is `DISCOVERY-MUTATE`. Brief (parse strictly; halt `BRIEF INVALID` on any missing/empty section, or if `[OUTPUT-PATH]` escapes `{run_dir}/reports/`): `[ROLE]` / `[QUESTION]` / `[SOURCES]` / `[OUTPUT-PATH]` / `[BUDGET]` / `[FORMAT]` / `[NON-GOALS]`. Return the canonical DISCOVERY REPORT + one `shctx discovery insert --run=<RUN_ID>` row per finding (halt `MISSING-RUN-ID` if the brief lacks it) — report template + field labels owned by `agents/discovery.md`.

Specialization: `@discovery` is the flock's EXTERNAL-information lane — documentation, web research, release notes, MCP state — compiled into intelligence reports; codebase orientation inside a combo wave belongs to intro-`@auditor` lanes (`skills/shepherd/references/pipeline.md §INTRO`). Six dispatch patterns: **A PRE-MESH-DISCOVERY** (intro wave: prior-close, canonical-types freshness, GH state); **B PRE-HOTFIX-DISCOVERY** (on WAVE-N-GATE fail: cluster `{run_dir}/gates/wN-gate.json` errors — the gate's structured `--keep-going` output, written at gate time); **C ARCHITECTURE-DISCOVERY** (mid-session re-orientation); **D DOCTRINE-RECONCILIATION-DISCOVERY** (per-rule adherence); **E MCP-STATE-DISCOVERY** (read-only GH/Sentry/Supabase fan-out); **F RESEARCH-SUMMARY-DISCOVERY** (external cited web research).

Confidence: HIGH (authoritative, full coverage, no conflicts) / MEDIUM (gaps or resolved conflicts) / LOW (thin / conflicting — surface for a second discovery). Citations MANDATORY in `## Findings`; an uncited claim → `## Open questions`.

## @conductor

A conductor is a spawned teammate, one per lane: it plans, dispatches, validates, ties off, and writes ONLY `.md` — NEVER source, manifests, shell scripts, or anything the flock owns. Its cwd / HEAD / active-worktree triple is pinned to the sprint root at session open and MUST NEVER drift.

### §Ban 1 — never `cd`/`pushd` into a worktree
Use `git -C <path>` + absolute `Read`/`Write`. A stray commit in a drifted cwd is invisible until cherry-pick, then silently replayed or dropped. Ban 3 companion: NEVER `git worktree add` from inside a worktree — run from sprint root or use `shctx worktree create-batch`.

### §Ban 2 — never `git switch`/`checkout` to an agent lane branch
Allowed checkouts: ONLY `{patch_branch}` / `{sprint_branch}` / `{main_branch}`, and `git checkout -b {next_sprint_branch}` at close. Agent lane branches (`agent-*`, `lane-*`) are permanently off-limits to conductor HEAD — a conductor-signed commit on a lane branch fails the `code-quality` close audit.

### §Mandatory verification (session open + before every worktree op)
1. `pwd` matches row 1 of `git worktree list`.
2. `git rev-parse --abbrev-ref HEAD` == `{sprint_branch}` (or patch/main during release plumbing).
3. `[[ "$(git rev-parse --git-dir)" == "$(git rev-parse --git-common-dir)" ]]` — else `DRIFT: inside a sub-worktree`, exit 1.

Any failure → HALT; recover to the primary worktree and re-verify all three. This binds the conductor session ONLY — dispatched coders / auditors / workers own their own triple. In no-isolation mode HEAD legitimately advances as the CONDUCTOR commits coder output to the sprint branch (coders never commit — §@coder) — verify HEAD-at-branch-name, not against `[BASE-COMMIT-EXPECTED]`.

**Three meta profiles** sit above the six lanes, adopted as session identity (NEVER Agent-dispatched): root **@shepherd** (`agents/shepherd.md`), teammate/solo **@conductor** (`agents/conductor.md`), and **@planter** (`agents/planter.md`). A teammate-conductor's dispatch surface is restricted (no artifact writes) and NEVER reaches @engineer/@critic — it surfaces `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` to root (`skills/shepherd/references/escalation.md §Halt-code index`). Canonical tier matrix: `skills/shepherd/SKILL.md §Dispatch law`.

## Write boundaries

Every coder `Write`/`Edit` target (source, manifests, migrations, docs, AND shared-context artifacts under `.shepherd/`) MUST resolve under the brief's `[WORKTREE].Path` — a write to the sprint root is invisible to the conductor's cherry-pick and dirties the tree: `CODER-WORKTREE-CONFINEMENT` (`lock_guard.sh`). The coder never runs `git add`/`commit` — the conductor stages the coder's reported files (`coder_git_guard.sh §@coder`). If the brief omits `[WORKTREE].Path`, halt `BRIEF INVALID — missing [WORKTREE].Path`.

Sprint coder worktrees MUST be branched from sprint HEAD via `shctx worktree create-batch <lanes> --from "$SPRINT_BRANCH"`, NEVER via `Agent({isolation:"worktree"})` (its base non-deterministically defaults to `main`). The batch emits `[BASE-COMMIT-EXPECTED]` (40-char SHA) on its last line; paste it verbatim into every coder brief. The coder verifies at Step 0.5 BEFORE touching code; on SHA mismatch it halts with the exact message (this guards worktrees branched from the wrong base):

```
BASE-DRIFT — worktree HEAD <actual_sha> does not match [BASE-COMMIT-EXPECTED] <expected_sha>.
The worktree was branched from the wrong base — likely `main` or a stale patch branch.
Halting before Step 1. Conductor must re-create the worktree from {sprint_branch} HEAD.
```

A brief that omits `[BASE-COMMIT-EXPECTED]` entirely → halt `BRIEF INVALID — missing [BASE-COMMIT-EXPECTED]`. If `isolation:"worktree"` consistently routes to `main`, the conductor switches to no-isolation dispatch (file-disjoint `[FILE-SCOPE]`, direct commits to the sprint branch), documented in the close report. Discovery/auditor write paths are enforced identically (`DISCOVERY-WRITE-PATH` / `AUDITOR-WRITE-PATH`). Teardown removes ONLY `.worktrees/<sprint_slug>-<lane_id>`; tearing down a live sibling is `WORKTREE-TEARDOWN-LIVE`.

## Teammate bridge

Under `/shepherd:spawn`, root spawns one teammate-conductor per lane via native teammate-spawn referencing `shepherd:conductor`; `Agent`/`Task` spawn ephemeral subagents, NEVER teammates. Platform Agent Teams and shepherd's stack coexist; ownership splits by axis:

- **Identity + liveness — shepherd owns it.** Each teammate MUST run `shctx ... register` at boot; its name is predictable (`shepherd-{lane|parallel|auto}-{sprint_slug}[-{lane_id}]`) and the `teammates` table is the only authoritative liveness index. An unregistered teammate is invisible to shepherd coordination even while running.
- **Messaging — SPLIT BY SESSION SCOPE (v6.3.7 #206).** Intra-session teammate↔lead messages use the harness-native `SendMessage` — that IS the canonical inbox; a teammate reports status, root drains and routes by `halt_code`, all inline. The durable audit trail of teammate/escalation STATE is the registry (`teammates`/`escalations` rows), not a message log. Cross-session handoff between two INDEPENDENT sessions (no shared team graph — e.g. `--staged` plant→spawn) uses the dedicated `shctx signal` channel (`session_signals`). Never conflate the two: `signal` is not a teammate inbox, and `SendMessage` cannot bridge independent sessions.
- **Cleanup — both, non-overlapping.** Shepherd owns git worktrees, `agent-*` branches, the lock, and stale-row prune (`shctx cleanup`); the platform owns `~/.claude/teams/`. Run both at close.

Platform capability facts (Agent Teams limits, `TeammateIdle`/`Task*` hooks, tool-presence truth): `skills/harness/SKILL.md §Agent Teams`. Anti-patterns — each a split-brain process violation: spawning teammates by natural language inside a solo session (no root identity layer); reading `~/.claude/teams/*/config.json` as the liveness source of truth (query the `teammates` table); using `SendMessage` for a cross-session message; skipping `register` at boot.
