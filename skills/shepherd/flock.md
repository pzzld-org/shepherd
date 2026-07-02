---
title: flock
description: Per-agent dispatch reference for the six-agent flock. Covers trigger conditions, parallel-safety, brief contract, and label/milestone discipline. Each agent's system prompt lives in agents/<role>.md — flock.md does NOT duplicate that content.
---

# The Flock — Dispatch Reference

Main chat is the **conductor** (orchestrator). It plans, seeds, dispatches, validates, and ties off. It NEVER writes code into source files, build manifests, shell scripts, or anything the flock owns. Only `.md` files: plans, reports, memory, `questions.md`. If a task needs 3+ non-thinking tool calls, offload to the flock.

---

## I. Agent files and dispatch procedure

The six agent definitions live at `${CLAUDE_PLUGIN_ROOT}/agents/`. Each file's YAML frontmatter defines `name`, `model`, `tools`, `description`; the markdown body is the agent's **system prompt** (identity + behavioral rules + NEVER clauses). **flock.md does NOT duplicate that content** — this file is the conductor's operational reference: when to dispatch, parallel-safety, brief shape.

```
${CLAUDE_PLUGIN_ROOT}/agents/coder.md      → @coder      model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/auditor.md    → @auditor    model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/critic.md     → @critic     model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/engineer.md   → @engineer   model: opus
${CLAUDE_PLUGIN_ROOT}/agents/worker.md     → @worker     model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/discovery.md  → @discovery  model: sonnet  (v5.1.1+)
```

**Dispatch procedure (every flock agent, every time) — MANDATORY (v6.0.0):**

1. **Set `subagent_type` to `"shepherd:<role>"`** — the plugin agent registry auto-loads the agent body from `agents/<role>.md`. **Mandatory for every flock dispatch.** Omitting it, defaulting to `general-purpose`, or substituting `Explore`/`Chat` is `DISPATCH-MISSING-SUBAGENT-TYPE` (`doctrines/dispatch-tier-separation.md §IV-bis.1`) — refuse to fire.
2. **Set `model`** per the table above.
3. **Put the task brief in `prompt`** — do NOT duplicate the agent body.
4. **Leave `team_name` UNSET** — reserved for root-level teammate-CONDUCTOR spawns under `/shepherd:spawn` only. A flock dispatch with `team_name` set produces a coder/auditor/worker AS a teammate with no conductor coordination: `DISPATCH-TEAMMATE-TYPE-MISMATCH` (§IV-bis.2). Refuse.

```
Agent({
  description: "@coder: <short task summary>",
  subagent_type: "shepherd:coder",      // MANDATORY — never omit
  model: "sonnet",
  prompt: "TASK BRIEF:\n<brief>"
  // team_name: NEVER set on a flock dispatch
})
```

Saves ~150–650 lines of inline body per dispatch (GH #20) — ~3000 tokens/wave for a 9-coder wave.

**Forbidden combinations — refuse on sight** (full table: `doctrines/dispatch-tier-separation.md §IV-bis`):

| Combination | Halt code |
|---|---|
| `subagent_type` missing OR `general-purpose`/`Explore`/`Chat` | `DISPATCH-MISSING-SUBAGENT-TYPE` |
| `team_name` set + `subagent_type ≠ shepherd:conductor` | `DISPATCH-TEAMMATE-TYPE-MISMATCH` |
| `subagent_type` outside closed-flock-six (no specialist clearance) | `DISPATCH-OFF-FLOCK` |
| Teammate-conductor constructs `team_name` (any value) | `TEAMMATE-NESTING-ATTEMPT` |
| Teammate-conductor dispatches `@engineer`/`@critic` | `WRONG-TIER-DISPATCH` (engineer/critic halts on receipt) |

**The flock is closed at six + specialist exceptions** (`doctrines/specialist-dispatch.md`, v5.1.1+). Never dispatch any agent outside these six unless it's a pre-authorized specialist (e.g. `code-review:code-review`, `sentry:seer`) whose contract strictly fits the task — specialists are exception, not default. Plan authorship / critic gating / close-time audit grading / code implementation are never substitutable. Engineer's plan-skills (`superpowers:brainstorming` + `superpowers:writing-plans`) and auditor's skill (`superpowers:systematic-debugging`) load from inside the agent's own dispatch, not from the conductor calling them. If a task fits no flock role and no specialist, the conductor handles it inline.

---

## II. Per-agent dispatch reference

### @auditor — code quality reviewer

**Model:** Sonnet · `${CLAUDE_PLUGIN_ROOT}/agents/auditor.md`

**Dispatch mode:** SWARM, min 3 max 5, always parallel. **Split by concern, never by file:**

| Concern | Focus |
|---|---|
| code-quality | language-idiom adherence, dead code, naming, deprecated markers, in-code discipline |
| data-flow | money path / business-critical path, gate logic, signal correctness, fail-closed verification |
| dependency-topology | feature gating, dependency flow, package boundary, wrapper-grep gate (`doctrines/wrapper-must-earn.md`) |
| datastore-state | schema migrations, RLS, row counts, query correctness, indexes |
| completeness | exit criteria pass/fail, carry-forwards, GH triage, real-work test, SUBTRACT verification, issue-ledger discipline |

**Trigger (mandatory):** end of every sprint (§3 close); before any merge to the patch branch; after any wave touching money-path code; whenever regression is suspected. **Plus (v6.2.4, #167):** every wave gets ≥1 `@auditor` in `mode: wave-review` returning `review_verdict: PASS|REDO` against the four-item checklist (intent / no fragile global / no reinvention / no passes-local-breaks-CI); the conductor emits `WAVE-COMPLETE` only on `PASS` and forces the named author to redo on `REDO` (`doctrines/flock-output-review.md`).

**Timing — Pattern B overlap:** auditors reviewing Wave N output (close-mode and wave-review) dispatch **concurrently with Wave N+1 coders**, same message batch — never wait for all coder waves (`doctrines/pattern-b-overlap.md`).

**Brief must include:** non-overlapping concern scope, plan + close-report paths, GH repo slug, report path `{paths.reports}/<date>-audit-<concern>.md`, datastore project ID if schema validation needed.

**Produces:** report markdown + GH issue per HIGH/CRITICAL finding + grade A–F (cutoffs in `references/agent-briefs.md`).

**Auditors are READ-ONLY** (`doctrines/auditor-readonly.md`) — applying fixes is a process violation; the conductor dispatches hot-fix coders for findings.

---

### @coder — implementation specialist

**Model:** Sonnet · `${CLAUDE_PLUGIN_ROOT}/agents/coder.md`

**Dispatch mode:** one `@coder` per **step** (one coder's non-overlapping file scope — `doctrines/primitive-axis-binding.md §II`). A wave's gate-free coder steps fan out concurrently.

**Trigger:** any implementation task in the sprint plan (§2 body). Never for planning, architecture, or research.

**Parallel-safe:** YES, only when scopes are disjoint. Before dispatching N coders concurrently, verify zero file overlap, zero shared build-manifest edits (single-writer rule), and no rename cascade touching public re-exports across scopes.

**Parallel dispatch rule (binding):** zero-overlapping coders MUST be dispatched in the **same message**. Sequential dispatch of parallel-safe coders is a process violation.

**Decomposition discipline:** decompose each wave into many narrow, file-disjoint `@coder` steps, to the substantive LOC floor by T-shirt in `agents/engineer.md §Step decomposition discipline`. Too-few/too-broad steps → reject back to @engineer. (Spawn-mode parallelism is the **lane** projection — total lanes, never per-wave — per `agents/engineer.md §Lane projection`; lanes are a post-plan concept, `doctrines/primitive-axis-binding.md`.)

**Meaningful-progress bar:** ≥ 50–100 LOC production code per coder. < 30 LOC = merge with adjacent work. > 8 files = split into sub-coders.

**Sequential required when:** schema migrations (single writer), architectural refactors touching many files, rename cascades across public re-exports, critic-flagged sequencing dependency.

#### Brief contract (mandatory — seven exact bracketed headers)

The coder's Startup Protocol parses these exact headers — drift causes the agent to STOP and reject the brief.

```
[SKILLS]             # Skill slugs to invoke via the Skill tool — see matrix below
[CONTEXT-INVENTORY]  # Existing types/traits/functions/constants to reuse (absolute paths + one-line description each)
[DO-NOT-DUPLICATE]   # Grep patterns the coder MUST run before writing new code (must-be-zero patterns)
[USER-STYLE]         # Required: `code-style` (always)
[FILE-SCOPE]         # Files the coder MAY create/modify + files it MUST NOT touch
[NON-GOALS]          # Things the plan explicitly reserves for other sprints / other coders
[ACCEPTANCE]         # Runnable greps + structural assertions that prove the scope landed
```

Five supporting lines every brief carries:
- **`[WORKTREE]`** — `path: <absolute worktree path>  branch: <worktree branch>  cut-from: <sprint branch>  commit: fix(dev.N/<track>): <subject>`. Coder commits here; conductor rebases and deletes.
- Absolute repo path + sprint branch — one line (separate from `[WORKTREE]`)
- **`ONE cargo check after all code is written — not before, not repeatedly.`**
- **`No new build-manifest dependencies without conductor approval.`**
- **`Prefer more focused lanes over fewer broad ones — splitting scope is correct.`**
- **`[DB-CONTEXT]`** (optional v5.0.0-c, required v5.0.0-d): when the engineer populates it via `shctx inject coder`, it's authoritative for `[CONTEXT-INVENTORY]` overlap:
  ```
  [DB-CONTEXT]
  ## Existing canonical types — REUSE; do not duplicate
  | package | kind | name | signature |
  | … |
  [/DB-CONTEXT]
  ```
  Coder MUST cite ≥1 `[DB-CONTEXT]` row in `[CONTEXT-INVENTORY]` if the lane introduces an overlapping type.
- **Auto-attach `[CODE-STYLE]` block (v5.0.0+):** for every language detected in `[FILE-SCOPE]`, the conductor reads `.artifacts/styles/<lang>.md` and prepends it as `[CODE-STYLE]` (running `shctx style init <lang>` first if missing). The operator-installed `code-style` skill remains the universal ledger; `[CODE-STYLE]` is the project-specific override layer — coders read both, project rules win on conflict.

#### Required-Skills Matrix (conductor MECHANICALLY populates `[SKILLS]` — never trusts engineer's list)

Per `doctrines/zero-duplicate-tolerance.md`, the conductor mechanically computes `[SKILLS]`; the engineer's plan MAY suggest skills but the conductor's computation is authoritative:

```
[SKILLS] := [skills.mandatory]                                 # always (e.g., code-style)

for path in [FILE-SCOPE].MAY_MODIFY:
    primary_language := infer_language_from_extension(path)    # .rs → rust, .py → python, ...
    [SKILLS] += [primary_language]
    for (pattern, skill_list) in [skills.detection]:
        if path matches pattern:
            [SKILLS] += skill_list
            break

for domain in detect_domains([FILE-SCOPE]):                    # finance, payments, supabase, ...
    [SKILLS] += [skills.by_domain][domain]

[SKILLS] := dedupe([SKILLS])
```

The matrix below is the FRAMEWORK default; per-project overrides come from `shepherd.toml [skills.by_domain]` / `[skills.detection]`.

| Target file / domain | Required Skill slugs |
|---|---|
| Any source file in the project's primary language | `<primary-language>`, `code-style` |
| Mixed-language source | every matching language skill, `code-style` |
| Test-writing (TDD discipline) | base-language skills + `superpowers:test-driven-development` |
| Schema migrations | `<datastore-domain skill>`, `code-style` |
| Build-manifest edits | per-language skill, `code-style` (and conductor-approval — hard prohibitions) |

`code-style` is additive to language-mastery, not a substitute — coders need both.

**Skill-attachment audit at close:** the `code-quality` auditor verifies every coder dispatch loaded the skills the conductor's mechanical computation would have produced. A mismatch is a `SKILL-DRIFT` finding (and a documented duplicate-risk source — coders without the language skill produce non-idiomatic code, harder to dedupe later).

#### `[CONTEXT-INVENTORY]` contents (conductor populates)

One bullet per existing symbol the coder should reuse:

```
- `{Symbol}` in `{absolute-or-package-path}::{module}` — {one-line description}
```

Minimum items: every package/module/umbrella re-export the scope imports from; every type the acceptance mentions; every trait/interface the coder implements/extends/calls; every constant/default it must honor.

If a cited entry is stale, the coder replies `CONTEXT-INVENTORY STALE: ...` and the conductor re-meshes before re-dispatching.

#### `[DO-NOT-DUPLICATE]` contents (conductor populates)

Explicit greps the coder runs **before writing any new type/function/constant**:

```
- rg -n "<language-specific pattern for new identifier>" → expected 0 hits
```

Pattern syntax is language-specific (consult the language skill). A hit > 0 → coder replies `DUPLICATION RISK: <pattern> hit N times` and halts.

#### Brief-Validity Checklist (conductor runs BEFORE dispatch — DEDUP-GATE node)

This checklist IS the runtime behavior of the `DEDUP-GATE` node (`pipeline.md §II` + `doctrines/zero-duplicate-tolerance.md`). Failure on any line BLOCKS dispatch.

- [ ] All seven bracketed sections present and non-empty?
- [ ] `[WORKTREE]` line present with path + branch + cut-from + commit template?
- [ ] Worktree already cut from sprint branch (`git worktree add <path> -b <branch>`) before dispatch?
- [ ] `[SKILLS]` matches the conductor's mechanical computation (engineer's suggestions are a SUBSET, never a SUPERSET-with-omissions)? Per-`[FILE-SCOPE]` from `[skills.mandatory]` + `[skills.detection]` + `[skills.by_domain]`.
- [ ] Every primary-language file in `[FILE-SCOPE]` has its language skill in `[SKILLS]` (.rs→`rust`, .py→`python`, .ts/.tsx→`typescript`, .go→`go`, ...)?
- [ ] `[USER-STYLE]` contains `code-style` at minimum?
- [ ] `[CONTEXT-INVENTORY]` cites from `{paths.ctx}/canonical-types.md` for every concept touched (`doctrines/zero-duplicate-tolerance.md` §canonical-types index)?
- [ ] `[CONTEXT-INVENTORY]` cites ≥1 existing symbol per new package/module touched, with absolute path?
- [ ] `[DO-NOT-DUPLICATE]` names every new identifier the coder is about to introduce, AND the conductor has run every grep itself with every result equal to the expected count?
- [ ] `[FILE-SCOPE]` is file-disjoint from every OTHER coder in the same wave?
- [ ] `[ACCEPTANCE]` is runnable (greps, LOC, structural assertions), not prose?

Per `doctrines/zero-duplicate-tolerance.md` §Layer 2, a brief failing ANY checkbox is a DEDUP-GATE block — the conductor amends the brief (convert lane to "wire to existing", or escalate) and re-runs the checklist. Coder-side `BRIEF INVALID` halt is a fallback, not the primary defense.

#### Worktree lifecycle (conductor owns)

Before dispatch:
```bash
git worktree add .worktrees/<lane> -b claude-agent-<lane>-<short-hash>
# branch is cut from sprint branch (HEAD)
```

After coder reports back (all coders in wave before rebase):
```bash
# Rebase each worktree branch into sprint branch
git rebase claude-agent-<lane>-<short-hash>
# Repeat per coder; resolve any conflicts inline

# Gate sequence — sequential, on the sprint branch, after ALL rebases
# Commands come from shepherd.toml [gates]; examples below are Rust defaults.
{gates.format}   # normalize formatting (e.g. cargo fmt --all, prettier --write, black .)
{gates.check}    # bail early on compile/type errors (e.g. cargo check, tsc --noEmit)
{gates.lint}     # static analysis (e.g. cargo clippy -D warnings, eslint, ruff check)
# Language-specific auto-fix (optional, per language skill):
#   Rust:   cargo fix --allow-dirty && cargo clippy --fix --allow-dirty
#   TS/JS:  eslint --fix
#   Python: ruff check --fix

git add -A && git commit -m "fix(dev.N/wave-K): rebase + gate"

# Clean up
git worktree remove .worktrees/<lane>
git branch -d claude-agent-<lane>-<short-hash>
```

**Coders run zero build/compile/lint invocations** — worktrees share the workspace build cache and parallel tool invocations can deadlock or produce false errors. The conductor runs the gate sequence above sequentially, by main chat, after ALL worktrees in a wave are rebased. Exact commands come from `shepherd.toml [gates]`; the framework does not hardcode language-specific tool names.

**In-code rules** (auditor + critic enforce, coder system prompt encodes): per-language deprecation marker for migrations; explicit-panic stub for unfinished work; no in-code TODO/FIXME (use GH issue creation); per-language collection-type preference per `code-style:<language>.md`; tracing levels per project CLAUDE.md.

---

### @critic — adversarial gate

**Model:** Sonnet · `${CLAUDE_PLUGIN_ROOT}/agents/critic.md`

**Dispatch mode:** Single agent, sequential — always BEFORE non-trivial coder dispatch.

**Trigger (mandatory):** any plan above XS scope, money-path/business-critical changes, schema migrations, architectural shifts (new package/trait/table/dependency-flow change), any proposed merge to `main`.

**Output (verbatim shape):** `agents/critic.md §Output`.

**Pass-2 flag classification (after @engineer revised once):**
- `dispatcher-patch` — trivial line-level fix → main chat applies inline, informal pass-3 for verdict
- `substantive` — design gap → ESCALATE to operator, never block-and-proceed

---

### @engineer — sprint plan author

**Model:** Opus, one dispatch per sprint · `${CLAUDE_PLUGIN_ROOT}/agents/engineer.md`

**Dispatch mode:** Single agent, once per sprint in §1 INTRODUCTION.

**Self-contained mode (v6.2.5, clarified v6.2.6):** under `/shepherd:spawn`, root MAY instead spawn `@engineer` as its OWN named teammate (native teammate-spawn, never an Agent/Task subagent). It runs, in its own window, a read-only sub-flock — INTRO-COMBO-WAVE (`@discovery` + intro-`@auditor`) plus its own `@critic` gate + ≥1 revision — returning the plan plus a hash-tied **critic-proof**. Root then skips its own discovery wave and `@critic` and accepts via a thin `shctx plan verify` gate, not a re-critique; no code is touched. A teammate-**conductor** may NOT dispatch `@engineer`/`@critic` (`WRONG-TIER-DISPATCH`); teammate → `@engineer` is refused unconditionally; a self-contained engineer dispatched as a subagent is refused (`ENGINEER-TOPOLOGY-MISMATCH`). Only root spawns the engineer teammate, and it dispatches ONLY its read-only sub-flock (tagged `dispatcher: engineer-self-contained`). See `doctrines/engineer-self-contained-plan.md`.

**Trigger:** start of every sprint (main chat seeds, @engineer plans); seed revised mid-cycle needing plan regeneration; Phase 0 mesh stale.

**Mandatory skills to load on dispatch:**
1. `superpowers:brainstorming` — design the §2 BODY decomposition
2. `superpowers:writing-plans` — primary plan-structure framework
3. Every skill in `shepherd.toml [skills.mandatory]` (default: `["code-style"]`)
4. Per-language skill per `shepherd.toml [project].language`
5. Domain skills per `[skills.by_domain]` whose `[skills.detection]` patterns match the sprint's file scope

No framework-mandatory skill list beyond brainstorming + writing-plans — `workflow`, `code-style`, and other cross-cutting skills load only when the project opts in via `[skills.mandatory]` or `[skills.detection]` match. The flock framework is unopinionated about which skills exist.

**Sandwich-plan discipline:** §1 + §3 are predictable single-phase bookends with structured steps cited verbatim from `SKILL.md` §III. §2 is the engineer's territory — N phases, plan-defined wave decomposition, parallel-safety analysis, real-work justification per phase. N scales with shepherd model: opus enables deeper bodies, sonnet runs leaner.

**Process:** (1) **Phase 0 mesh** at plan-time, embedded at TOP of plan (open GH issues — full ledger per `doctrines/issue-ledger-awareness.md`, recent PRs, `git log` since prior close, deploy/error/datastore state per `[mcp]`/`[cli]` flags, prior carry-forwards, every seed-referenced artefact); (2) **author plan** at `{paths.plans}/{sprint_slug}.plan.md` with frontmatter, Phase 0 findings, north-star, phases, wave composition, exit criteria, open questions; (3) **proof-of-dispatch footer** — main chat populates critic/revision/status fields after critic passes.

**Brief must include:** seed file path, prior close-report path, branch + version context, `[mcp]`/`[cli]` availability flags, "DO NOT write source code. DO NOT commit. DO NOT dispatch other agents."

**Revision protocol:** GREEN → READY, main chat commits plan, proceeds to coder dispatch. YELLOW → revise ONCE, @critic pass 2; pass-2 GREEN → READY; pass-2 YELLOW/RED → ESCALATED. RED → ESCALATED immediately; main chat amends seed before re-dispatch.

---

### @discovery — read-only orientation / research (v5.1.1+)

**Model:** Sonnet · `${CLAUDE_PLUGIN_ROOT}/agents/discovery.md`

**Dispatch mode:** Single OR parallel — multiple discoveries fire in one Agent batch when questions are file-disjoint (typically all are). Cap: 5 concurrent.

**Trigger:** when the conductor (or engineer's plan) needs read-only exploration absorbed into a parallel agent. Canonical patterns:
- **PRE-MESH-DISCOVERY** (in INTRO-COMBO-WAVE): prior-close-audit ingestion, canonical-types freshness, GH state inventory
- **PRE-HOTFIX-DISCOVERY**: error-cluster analysis from `.shepherd/runs/wN-gate.json`
- **ARCHITECTURE-DISCOVERY**: mid-session orientation when conductor joins late
- **DOCTRINE-RECONCILIATION-DISCOVERY**: "does the codebase actually follow doctrine X?"
- **MCP-STATE-DISCOVERY**: read-only fan-out across GH + Sentry + Supabase + ...
- **RESEARCH-SUMMARY-DISCOVERY**: external web research with citations

**Hard rules:** read-only, NEVER mutates state (no Edit, no MCP write, no dispatch). Output is a structured DISCOVERY REPORT at `{paths.reports}/<date>-discovery-<id>.md`. Never grades (auditor's lane) — surfaces facts and questions, not recommendations. Never substitutes for worker (acts) or auditor (grades).

**Brief contract (mandatory bracketed sections):**

```
[ROLE]               @discovery — read-only orientation
[QUESTION]           <one-sentence question>
[SOURCES]            <files, dirs, MCP queries, web URLs>
[OUTPUT-PATH]        {paths.reports}/<date>-discovery-<id>.md
[BUDGET]
  - Time: <max minutes>
  - Max tool calls: <N>
[FORMAT]             <Findings + Open questions + Confidence minimum>
[NON-GOALS]          (default four + brief-specific additions)
```

Copy-paste templates per pattern: `references/agent-briefs.md § @discovery`. Full contract + use-case catalog + cross-sprint reuse rules: `doctrines/discovery-readonly.md`.

---

### @worker — bounded task executor

**Model:** Sonnet · `${CLAUDE_PLUGIN_ROOT}/agents/worker.md`

**Dispatch mode:** Single or parallel — always bounded (defined deliverable, defined budget).

**Trigger:** monitoring tasks > 10 min (log tails, error triage, deploy inspection); MCP batches (datastore, GH bulk ops); research and summary docs; branch cleanup; data analysis; file organization; any self-contained task.

**Timing:** workers MUST be dispatched at the **start of Wave 1**, not after — they're IO-bound and non-competing. Never defer a worker that could run parallel with Wave 1.

**Main chat NEVER sits on a Monitor stream** — anything requiring sustained observation goes to @worker.

**Brief must include:** "You are a @worker. Report back a summary; do not stream updates." + the specific deliverable + sources to consult + budget (time + max tool-call count) + report format + "Do NOT modify any code, data, or config." (unless deliverable IS `.md`).

**Dispatch patterns and brief catalog:** `doctrines/worker-patterns.md` — when to dispatch worker (vs inline), brief templates for issue triage / deploy monitoring / branch cleanup / research / file organization, and anti-patterns to avoid.

---

## III. Dispatch discipline summary

| Rule | Detail |
|------|--------|
| **Flock agents ONLY — `subagent_type` MANDATORY (v6.0.0)** | Set `subagent_type: "shepherd:<role>"`. Missing → `DISPATCH-MISSING-SUBAGENT-TYPE` halt; never silently defaults to general-purpose. `doctrines/dispatch-tier-separation.md §IV-bis`. |
| Parallel coders require zero file overlap | Verify before dispatch; single build-manifest writer at a time |
| Parallel dispatch rule | Zero-overlap coders MUST be in the same message — sequential dispatch is a process violation |
| Decompose each wave into many narrow steps (LOC floor per `engineer.md`); spawn-mode lane-count guidance (few fat lanes) per `engineer.md §Lane projection` | Under-decomposed wave / mis-sized lane projection → reject back to @engineer |
| @critic before every non-XS dispatch | No exceptions for money-path, schema, or arch changes |
| @auditor always a swarm by concern | 3–5 agents minimum; split by concern, never by file |
| @auditor overlaps with Wave 2 coders | Pattern B — same message batch (`doctrines/pattern-b-overlap.md`) |
| @worker at Wave 1 START | IO-bound; never defer |
| @engineer once per sprint | Opus; gated by @critic |
| **Only `@engineer` is count-capped** — `@auditor`/`@worker`/`@discovery`/`@coder`/`@critic` are freely repeatable | The close swarm (3–5) and intro waves are FLOORS, not ceilings — audit mid-body, re-discover before risky waves, worker-first for bounded ops, loop when completion = "no new findings" (`doctrines/dispatch-generosity.md`) |
| Main chat owns git | Coders describe diffs; main chat commits |
| No gates in coders | Main chat runs the single validation pass between waves |
| Every coder brief: language skills + `code-style` | Mandatory always (per `[skills.mandatory]`) |

---

## IV. Carry-forward + GH label/milestone discipline

### IV.A Carry-forward rules

- **CRITICAL/HIGH** items cannot be deferred. Dispatch another wave.
- **Once-deferred** items cannot be deferred again (operator override required).
- Every deferral opens a GH issue with `deferred` label, target milestone, target sprint slot in body.
- Auditor fails the sprint on any CRITICAL/HIGH carry-forward without justification.
- At each sprint close, the `completeness` auditor runs the carry-forward refresh per `doctrines/carry-forward-refresh.md` — chronic items (≥ `[ledger.chronic_threshold_patches]` patch crossings) get the `chronic` label.

### IV.B GH labels + milestones

- **Milestone = version**: `--milestone v{X}.{Y}.{Z}`. Authoritative version-grouping.
- **Sprint slot = issue body line**: `Target: {sprint_branch}`. NEVER create `dev.N` labels.
- **NEVER create new labels without operator approval.** Reuse existing; canonical status set: `critical`, `medium`, `low`, `deferred`, `chronic`.
- **Use the GH MCP for writes** per `doctrines/use-mcp-not-cli.md`. The `gh` CLI is fine for read-only enumeration.
- **Labels treated as `tracking-future` per `[ledger.non_issue_labels]`** are NOT carry-forwards — explicitly tracked but not actioned.

---

## V. Anti-patterns (the conductor actively watches for these)

1. Sequential dispatch when parallel is safe → must batch in one message
2. Over-scoped single coder (>8 files) → split into sub-coders
3. Under-scoped parallel coders (<30 LOC each) → merge thin scopes
4. Auditors waiting for all coder waves → dispatch on Wave 1 in parallel with Wave 2 (Pattern B; encoded as `parallel_with` in the Stage Graph)
5. Missing language skills in coder briefs → conductor MECHANICALLY computes `[SKILLS]`; never trust engineer's list. Every coder needs `code-style` + the matching language skill (`rust`/`python`/`typescript`/`go`/...)
6. @engineer dispatched for coder-scope tasks → @engineer is plans only
7. @critic skipped for M+ scope → no exceptions for "obvious" plans
8. Workers dispatched after Wave 1 → IO-bound, batch with Wave 1 START (graph encodes `parallel_with: [wave-1-impl]`)
9. Silent plan rejection → if a wave is under-decomposed or a spawn lane projection is mis-sized, explicitly reject to engineer
10. Missing `code-style` on coder briefs → mandatory always
11. Soft `[CONTEXT-INVENTORY]` → engineer must fully populate inline; conductor cross-checks against `{paths.ctx}/canonical-types.md`
12. **Skipping the anti-duplication grep** → THE ZERO-TOLERANCE ANTI-PATTERN. Conductor runs every `[DO-NOT-DUPLICATE]` grep BEFORE dispatch (DEDUP-GATE node). Coder-side self-halt is a fallback, not the primary defense.
13. Brief drift from canonical section names → coder rejects with `BRIEF INVALID`
14. **Tunnel vision on current milestone** → Phase 0 must enumerate ALL open issues per `doctrines/issue-ledger-awareness.md`, not just the milestone the seed targets
15. **Off-graph dispatch** → every Agent batch corresponds to a node in the plan's Stage Graph (`doctrines/stage-graph.md`); mid-walk improvisation is a process violation
16. **Stale `{paths.ctx}/canonical-types.md`** → every dev.0 fires the `CANONICAL-TYPES-REFRESH` worker; subsequent sprints' Phase 0 reads it FIRST
17. **Missing sprint-pattern registry read at mesh time** → the engineer MUST run `shctx adapt priors --metrics --lessons` as the sprint-patterns mesh row (`doctrines/adaptation-loop.md §III`); skipping it means systemic risks accumulate silently

---

## VI. Three-tier meta (shepherd + conductor + planter) — v5.1.6+

The six flock agents above are the closed domain flock. Above them sit three meta-orchestrators on TWO tiers, living in `agents/` by file convention but NOT opening the closed-flock contract and NOT dispatched via the Agent tool as lane agents.

| Tier | Profile | File | Adopted by | Role |
|---|---------|------|---|------|
| **3 (root)** | **@shepherd** | `${CLAUDE_PLUGIN_ROOT}/agents/shepherd.md` | Main chat under `/shepherd:spawn` (operator-explicit only) | **v5.1.6 — root-tier orchestrator.** Owns `@engineer` dispatch (subagent, or self-contained teammate) + `@critic` dispatch **in classic mode** (a self-contained engineer runs its own discovery + `@critic` in its window, #172), artifact materialization from teammate payloads, dispute resolution, close-swarm coordination. Writes `.md` only — never source code. |
| **2 (meta)** | **@conductor** | `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` | Main chat under `/shepherd:start` (SOLO) OR teammate session under `/shepherd:spawn` (TEAMMATE) | Sprint-runner / wave-executor. **Dual-mode** (v5.1.6+): solo mode preserves full dispatch + writes; teammate mode is restricted (no engineer/critic dispatch, no artifact writes). **Model: sonnet** (downgraded v5.1.6 from `inherit`). |
| **PARALLEL** | **@planter** | `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` | Main chat under `/shepherd:plant`; also loaded by shepherd profile mid-spawn for delegated seed work | Seed author + cleanup steward. Holds git custody during cleanup phases. Escalation responder when shepherd not loaded. Model: opus[1m]. |

**Key distinction from the six lanes:** flock agents are dispatched via `Agent({ prompt: "<agents/role.md body>...", ... })` — ephemeral subagents. Shepherd, conductor, and planter are adopted as the **ambient session identity** of whoever invokes the command (main chat or teammate) — not ephemeral. The §I dispatch procedure applies to the six flock agents only; the three meta profiles are self-applied.

**Dispatch tier separation under `/shepherd:spawn`:** per `doctrines/dispatch-tier-separation.md`, teammate-conductors (tier 2 teammate mode) CANNOT dispatch `@engineer` or `@critic` — root-tier-exclusive. Teammates surface `PLAN-AUTHORSHIP-REQUEST` or `PLAN-GATE-REQUEST` escalations to root via `SendMessage`. Solo-mode conductors (`/shepherd:start`) retain full dispatch surface — tier separation does NOT apply (solo conductor IS root).

The divergence table comparing conductor and planter is canonical in `agents/conductor.md §How the conductor differs from the planter`. The three-tier dispatch matrix is canonical in `doctrines/dispatch-tier-separation.md §II`. Do not maintain copies here.

<!-- DUPLICATED in agents/conductor.md §How the conductor differs from the planter — canonical there -->
<!-- DUPLICATED in doctrines/dispatch-tier-separation.md §II — canonical there -->

---

## VII. See also

- `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` — canonical conductor profile (sprint-runner; dispatch procedure; pipeline steps; halt codes; side-effect boundary; divergence table vs. planter)
- `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` — canonical planter profile (seed authorship; babysitter mode; git custody; escalation response)
- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — spawn command (preflight, teammate prompt construction, `--parallel` and `--auto` flag behavior)
- `pipeline.md` — Stage Graph node taxonomy + edge labels + walk algorithm
- `doctrines/stage-graph.md` — graph-as-dispatch-contract principle
- `doctrines/zero-duplicate-tolerance.md` — DEDUP-GATE pre-dispatch contract + skill auto-attachment
- `doctrines/spawn-escalation.md` — escalation channel contract (file paths, payload schema, resume shape, heartbeat, wave-boundary commits) (v5.1.4)
- `references/agent-briefs.md` — copy-paste brief templates + grade cutoffs
- `references/seed-template.md` — canonical seed shape (engineer reads + parses; engineer authors the Stage Graph from Phase-0)
- `references/branching-model.md` — branch lifecycle + rollover algorithm + hygiene checks
- `doctrines/*.md` — framework-intrinsic rules
- `${CLAUDE_PLUGIN_ROOT}/agents/<role>.md` — agent system prompts (source of truth for each agent's identity) — six domain lanes + conductor + planter meta-orchestrators
