---
title: flock
description: Per-agent dispatch reference for the five-agent flock. Covers trigger conditions, parallel-safety, brief contract, and label/milestone discipline. Each agent's system prompt lives in agents/<role>.md — flock.md does NOT duplicate that content.
---

# The Flock — Dispatch Reference

Main chat is the **conductor** (orchestrator). It plans, seeds, dispatches, validates, and ties off. It NEVER writes code into source files, build manifests, shell scripts, or anything the flock owns. Only `.md` files: plans, reports, memory, `questions.md`. If a task needs 3+ non-thinking tool calls, offload to the flock.

---

## I. Agent files and dispatch procedure

The five agent definitions live at `${CLAUDE_PLUGIN_ROOT}/agents/`. Each file's YAML frontmatter defines the agent's `name`, `model`, `tools`, and `description`. The markdown body is the agent's **system prompt** — the identity + behavioral rules + NEVER clauses. **flock.md does NOT duplicate that content.** This file is the conductor's operational reference: when to dispatch, parallel-safety, brief shape.

```
${CLAUDE_PLUGIN_ROOT}/agents/coder.md      → @coder     model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/auditor.md    → @auditor   model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/critic.md     → @critic    model: sonnet
${CLAUDE_PLUGIN_ROOT}/agents/engineer.md   → @engineer  model: opus
${CLAUDE_PLUGIN_ROOT}/agents/worker.md     → @worker    model: sonnet
```

**Dispatch procedure (every flock agent, every time):**

1. **Read** the agent definition file.
2. **Extract** the markdown body below the YAML frontmatter `---`.
3. **Prepend** that body to the task brief as the agent's system prompt.
4. **Set `model`** per the table above.
5. **Do NOT set `subagent_type`** — omit it (defaults to general-purpose runtime).

```
Agent({
  description: "@coder: <short task summary>",
  model: "sonnet",
  prompt: "<full body of agents/coder.md>\n\n---\nTASK BRIEF:\n<brief>"
})
```

The flock agent's identity comes from the injected system prompt. **The flock is closed.** NEVER dispatch any agent outside these five — no `general-purpose`, `Explore`, `Plan`, `feature-dev:*`, `pr-review-toolkit:*`, `superpowers:*`. Engineer's plan-skills (`superpowers:brainstorming` + `superpowers:writing-plans`) load from inside the engineer's own dispatch — that is not the conductor calling them. If a task doesn't fit a flock role, the conductor handles it inline.

---

## II. Per-agent dispatch reference

### @auditor — code quality reviewer

**Model:** Sonnet · **System prompt:** `${CLAUDE_PLUGIN_ROOT}/agents/auditor.md`

**Dispatch mode:** SWARM — minimum 3, maximum 5. Always parallel. **Split by concern, never by file:**

| Concern | Focus |
|---|---|
| code-quality | language-idiom adherence, dead code, naming, deprecated markers, in-code discipline |
| data-flow | money path / business-critical path, gate logic, signal correctness, fail-closed verification |
| dependency-topology | feature gating, dependency flow, package boundary, wrapper-grep gate (`doctrines/wrapper-must-earn.md`) |
| datastore-state | schema migrations, RLS, row counts, query correctness, indexes |
| completeness | exit criteria pass/fail, carry-forwards, GH triage, real-work test, SUBTRACT verification, issue-ledger discipline |

**Trigger (mandatory):** end of every sprint (§3 close), before any merge to the patch branch, after any wave that touched money-path code, whenever the conductor suspects regression.

**Timing — Pattern B overlap:** auditors reviewing Wave N output are dispatched **concurrently with Wave N+1 coders** in the same message batch. Do NOT wait for all coder waves to complete (per `doctrines/pattern-b-overlap.md`).

**Brief must include:** non-overlapping concern scope, plan + close-report paths, GH repo slug, report path `{paths.reports}/<date>-audit-<concern>.md`, datastore project ID if schema validation needed.

**Each auditor produces:** report markdown + GH issues for every HIGH/CRITICAL finding + grade A–F (cutoffs in `references/agent-briefs.md`).

**Auditors are READ-ONLY.** Per `doctrines/auditor-readonly.md`, applying fixes is a process violation. The conductor dispatches hot-fix coders for findings.

---

### @coder — implementation specialist

**Model:** Sonnet · **System prompt:** `${CLAUDE_PLUGIN_ROOT}/agents/coder.md`

**Dispatch mode:** Parallel waves, one coder per non-overlapping file/package scope.

**Trigger:** any implementation task in the sprint plan; §2 body of the sprint. Never dispatch for planning, architecture, or research.

**Parallel-safe:** YES — but ONLY when scopes are disjoint. Before dispatching N coders concurrently, verify:
- Zero file overlap between coder scopes
- Zero shared build-manifest edits (single-writer rule)
- No rename cascades touching public re-exports across coder scopes

**Parallel dispatch rule (binding):** zero-overlapping coders MUST be dispatched in the **same message** (single Agent batch). Sequential dispatch of parallel-safe coders is a process violation.

**Minimum lane count by sprint T-shirt:** M → 3 parallel coders, L → 4, XL → 4 per wave (multiple waves). Plan with fewer lanes than the minimum → reject back to @engineer.

**Meaningful-progress bar:** each coder modifies/creates ≥ 50–100 LOC of production code (not boilerplate). < 30 LOC = merge with adjacent work. > 8 files = split into sub-coders.

**Sequential required when:** schema migrations (single writer), architectural refactors touching many files, rename cascades across public re-exports, critic flagged sequencing dependency.

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
- **`[WORKTREE]`** — `path: <absolute worktree path>  branch: <worktree branch>  cut-from: <sprint branch>  commit: fix(dev.N/<track>): <subject>`. The coder commits in this worktree; conductor rebases and deletes.
- **Absolute repo path + sprint branch** — one line (separate from `[WORKTREE]`)
- **`ONE cargo check after all code is written — not before, not repeatedly.`**
- **`No new build-manifest dependencies without conductor approval.`**
- **`Prefer more focused lanes over fewer broad ones — splitting scope is correct.`**
- **`[DB-CONTEXT]` (optional in v5.0.0-c, required in v5.0.0-d).** When the engineer populates this block via `shctx inject coder`, the coder reads it as authoritative for `[CONTEXT-INVENTORY]` overlap. Block format:
  ```
  [DB-CONTEXT]
  ## Existing canonical types — REUSE; do not duplicate
  | package | kind | name | signature |
  | … |
  [/DB-CONTEXT]
  ```
  Coder MUST cite at least one `[DB-CONTEXT]` row in `[CONTEXT-INVENTORY]` if the lane introduces a type that overlaps with an existing canonical concept.
- **Auto-attach `[CODE-STYLE]` block (v5.0.0+).** For every language detected in `[FILE-SCOPE]`, the conductor reads `.artifacts/styles/<lang>.md` and prepends its content as a `[CODE-STYLE]` block in the brief. If the file is missing for a detected language, the conductor runs `shctx style init <lang>` first. The operator-installed `code-style` skill (separate plugin or user skill) remains the universal ledger; `[CODE-STYLE]` is the project-specific override layer. Coders read both; project rules win on conflict.

#### Required-Skills Matrix (conductor MECHANICALLY populates `[SKILLS]` — never trusts engineer's list)

Per `doctrines/zero-duplicate-tolerance.md`, the conductor **mechanically computes** `[SKILLS]` for every coder dispatch. The engineer's plan MAY suggest skills; the conductor's computation is authoritative. Algorithm:

```
[SKILLS] := [skills.mandatory]                                 # always (e.g., code-style)

for path in [FILE-SCOPE].MAY_MODIFY:
    primary_language := infer_language_from_extension(path)    # .rs → rust, .py → python, ...
    [SKILLS] += [primary_language]
    for (pattern, skill_list) in [skills.detection]:
        if path matches pattern:
            [SKILLS] += skill_list
            break

for domain in detect_domains([FILE-SCOPE]):                    # finance, polymarket, supabase, ...
    [SKILLS] += [skills.by_domain][domain]

[SKILLS] := dedupe([SKILLS])
```

The matrix below is the FRAMEWORK default; per-project overrides come from `shepherd.toml [skills.by_domain]` and `[skills.detection]`.

| Target file / domain | Required Skill slugs |
|---|---|
| Any source file in the project's primary language | `<primary-language>`, `code-style` |
| Mixed-language source | every matching language skill, `code-style` |
| Test-writing (TDD discipline) | base-language skills + `superpowers:test-driven-development` |
| Schema migrations | `<datastore-domain skill>`, `code-style` |
| Build-manifest edits | per-language skill, `code-style` (and conductor-approval — see hard prohibitions) |

`code-style` is **additive** to language-mastery, not a substitute. Coders need both.

**Skill-attachment audit at sprint close:** the `code-quality` auditor verifies that every coder dispatch in the sprint loaded the skills the conductor's mechanical computation would have produced. A mismatch is a `SKILL-DRIFT` finding (and a documented duplicate-risk source — coders without the language skill produce non-idiomatic code that's hard to dedupe later).

#### `[CONTEXT-INVENTORY]` contents (conductor populates)

One bullet per existing symbol the coder should reuse:

```
- `{Symbol}` in `{absolute-or-package-path}::{module}` — {one-line description}
```

Minimum items per brief:
- Every package / module / umbrella re-export the scope imports from
- Every type the brief's acceptance mentions
- Every trait/interface the coder will implement, extend, or call
- Every constant / default the coder must honor

If the coder reads a cited entry and finds it stale, it replies `CONTEXT-INVENTORY STALE: ...` and the conductor re-meshes before re-dispatching.

#### `[DO-NOT-DUPLICATE]` contents (conductor populates)

Explicit greps the coder runs **before writing any new type / function / constant**:

```
- rg -n "<language-specific pattern for new identifier>" → expected 0 hits
```

Pattern syntax is language-specific (consult the language skill). If a must-be-zero pattern returns N > 0, the coder replies `DUPLICATION RISK: <pattern> hit N times` and halts.

#### Brief-Validity Checklist (conductor runs BEFORE dispatch — DEDUP-GATE node)

This checklist IS the runtime behavior of the `DEDUP-GATE` node (per `pipeline.md` §II + `doctrines/zero-duplicate-tolerance.md`). Failure on any line BLOCKS dispatch — the Agent batch does NOT fire until every checkbox is green.

- [ ] All seven bracketed sections present and non-empty?
- [ ] `[WORKTREE]` line present with path + branch + cut-from + commit template?
- [ ] Worktree already cut from sprint branch (`git worktree add <path> -b <branch>`) before dispatch?
- [ ] **`[SKILLS]` matches the conductor's mechanical computation** (engineer's suggestions are a SUBSET, never a SUPERSET-with-omissions)? Computation is per-`[FILE-SCOPE]` from `[skills.mandatory]` + `[skills.detection]` + `[skills.by_domain]` (see Required-Skills Matrix above).
- [ ] **Every primary-language file in `[FILE-SCOPE]` has its language skill in `[SKILLS]`** (.rs → `rust`, .py → `python`, .ts/.tsx → `typescript`, .go → `go`, ...)?
- [ ] `[USER-STYLE]` contains `code-style` at minimum?
- [ ] **`[CONTEXT-INVENTORY]` cites from `{paths.ctx}/canonical-types.md`** for every concept the lane touches (per `doctrines/zero-duplicate-tolerance.md` §canonical-types index)?
- [ ] `[CONTEXT-INVENTORY]` cites at least one existing symbol per new package/module touched, with absolute path?
- [ ] **`[DO-NOT-DUPLICATE]` names every new identifier the coder is about to introduce** AND **the conductor has run every grep itself; every result equals the expected count**?
- [ ] `[FILE-SCOPE]` is file-disjoint from every OTHER coder in the same wave?
- [ ] `[ACCEPTANCE]` is runnable (greps, LOC, structural assertions) — not prose?

**A brief that fails ANY checkbox is a DEDUP-GATE block.** The conductor does NOT dispatch. Per `doctrines/zero-duplicate-tolerance.md` §Layer 2, the conductor amends the brief (convert lane to "wire to existing", or escalate to operator) and re-runs the checklist. Coder-side `BRIEF INVALID` halt is a fallback — this checklist is the contract.

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

# Four-step gate — sequential, on the sprint branch, after ALL rebases
cargo check --workspace --features full          # bail early on compile errors
cargo fmt --all                                   # normalize formatting first
cargo fix --workspace --allow-dirty              # apply rustc machine-applicable fixes
cargo clippy --fix --workspace --allow-dirty     # apply clippy machine-applicable fixes

git add -A && git commit -m "fix(dev.N/wave-K): rebase + fmt + fix + clippy"

# Clean up
git worktree remove .worktrees/<lane>
git branch -d claude-agent-<lane>-<short-hash>
```

**Coders run zero cargo invocations.** Worktrees share the workspace `target/` lock — parallel `cargo` calls WILL deadlock. The conductor runs the four-step gate above after ALL worktrees in a wave are rebased — 4 invocations, sequential, all by main chat. `--allow-dirty` is required because the working tree is dirty post-rebase before the gate commit fires.

**In-code rules** (auditor + critic enforce, coder system prompt encodes): per-language deprecation marker for migrations; explicit-panic stub for unfinished work; no in-code TODO/FIXME — use GH issue creation; per-language collection-type preference per `code-style:<language>.md`; tracing levels per project CLAUDE.md.

---

### @critic — adversarial gate

**Model:** Sonnet · **System prompt:** `${CLAUDE_PLUGIN_ROOT}/agents/critic.md`

**Dispatch mode:** Single agent, sequential — always BEFORE non-trivial coder dispatch.

**Trigger (mandatory):** any plan above XS scope, money-path / business-critical changes, schema migrations, architectural shifts (new package / trait / table / dependency-flow change), any proposed merge to `main`.

**Output (verbatim shape):** see `${CLAUDE_PLUGIN_ROOT}/agents/critic.md` §Output.

**Pass-2 flag classification (after @engineer revised once):**
- `dispatcher-patch` — trivial line-level fix → main chat applies inline, informal pass-3 for verdict
- `substantive` — design gap → ESCALATE to operator; never block-and-proceed

---

### @engineer — sprint plan author

**Model:** Opus (one dispatch per sprint) · **System prompt:** `${CLAUDE_PLUGIN_ROOT}/agents/engineer.md`

**Dispatch mode:** Single agent, once per sprint in §1 INTRODUCTION.

**Trigger:** start of every sprint (main chat seeds, @engineer plans); when a seed is revised mid-cycle and the plan needs regeneration; when Phase 0 mesh is stale.

**Mandatory skills to load on dispatch:**
1. `superpowers:brainstorming` — design the §2 BODY decomposition
2. `superpowers:writing-plans` — primary plan-structure framework
3. Every skill in `shepherd.toml [skills.mandatory]` (default: `["code-style"]`)
4. Per-language skill per `shepherd.toml [project].language`
5. Domain skills per `[skills.by_domain]` whose `[skills.detection]` patterns match the sprint's file scope

**No framework-mandatory skill list beyond brainstorming + writing-plans.** The `workflow` skill, the `code-style` skill, any other cross-cutting skills are loaded only when the project explicitly opts in via `[skills.mandatory]` or matches via `[skills.detection]`. The flock framework itself is unopinionated about which skills exist.

**Sandwich-plan discipline:** §1 + §3 are predictable single-phase bookends with structured steps cited verbatim from `SKILL.md` §III. §2 is the engineer's territory — N phases, plan-defined wave decomposition, parallel-safety analysis, real-work justification per phase. **N scales with shepherd model** — opus enables deeper bodies; sonnet runs leaner.

**Process:**
1. **Phase 0 mesh** — run at plan-time, embed at TOP of plan (open GH issues — full ledger per `doctrines/issue-ledger-awareness.md`, recent PRs, `git log` since prior close, deploy/error/datastore state per `[mcp]` and `[cli]` flags, prior carry-forwards, every artefact the seed references)
2. **Author plan** — `{paths.plans}/{sprint_branch}.plan.md` with frontmatter, Phase 0 findings, north-star, phases, wave composition, exit criteria, open questions
3. **Proof-of-dispatch footer** — main chat populates critic/revision/status fields after critic passes

**Brief must include:** seed file path, prior close-report path, branch + version context, `[mcp]` and `[cli]` availability flags, "DO NOT write source code. DO NOT commit. DO NOT dispatch other agents."

**Revision protocol:**
- GREEN → READY; main chat commits plan, proceeds to coder dispatch
- YELLOW → revise ONCE; @critic pass 2; pass-2 GREEN → READY; pass-2 YELLOW/RED → ESCALATED
- RED → ESCALATED immediately; main chat amends seed before re-dispatch

---

### @worker — bounded task executor

**Model:** Sonnet · **System prompt:** `${CLAUDE_PLUGIN_ROOT}/agents/worker.md`

**Dispatch mode:** Single or parallel — always bounded (defined deliverable, defined budget).

**Trigger:** monitoring tasks > 10 min (log tails, error triage, deploy inspection); MCP batches (datastore, GH bulk ops); research and summary docs; branch cleanup; data analysis; file organization; any self-contained task.

**Timing:** workers MUST be dispatched at the **start of Wave 1**, not after. They are IO-bound and non-competing. Never defer a worker that could run parallel with Wave 1.

**Main chat NEVER sits on a Monitor stream** — anything requiring sustained observation goes to @worker.

**Brief must include:** "You are a @worker. Report back a summary; do not stream updates." + the specific deliverable + sources to consult + budget (time + max tool-call count) + report format + "Do NOT modify any code, data, or config." (unless deliverable IS `.md`).

**Dispatch patterns and brief catalog**: see `doctrines/worker-patterns.md` for when to dispatch worker (vs inline), brief templates for issue triage / deploy monitoring / branch cleanup / research / file organization, and anti-patterns the conductor must avoid.

---

## III. Dispatch discipline summary

| Rule | Detail |
|------|--------|
| **Flock agents ONLY — injected via prompt** | Read `agents/<role>.md`, inject body. Never set `subagent_type`. No outside agents. |
| Parallel coders require zero file overlap | Verify before dispatch; single build-manifest writer at a time |
| Parallel dispatch rule | Zero-overlap coders MUST be in the same message — sequential dispatch is a process violation |
| Minimum lanes: M=3, L=4, XL=4/wave | Plan with fewer lanes → reject back to @engineer |
| @critic before every non-XS dispatch | No exceptions for money-path, schema, or arch changes |
| @auditor always a swarm by concern | 3–5 agents minimum; split by concern, never by file |
| @auditor overlaps with Wave 2 coders | Pattern B — same message batch (`doctrines/pattern-b-overlap.md`) |
| @worker at Wave 1 START | IO-bound; never defer |
| @engineer once per sprint | Opus; gated by @critic |
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
- **Labels treated as `tracking-future` per `[ledger.non_issue_labels]`** are NOT carry-forwards — they're explicitly tracked but not actioned.

---

## V. Anti-patterns (the conductor actively watches for these)

1. Sequential dispatch when parallel is safe → must batch in one message
2. Over-scoped single coder (>8 files) → split into sub-coders
3. Under-scoped parallel coders (<30 LOC each) → merge thin scopes
4. Auditors waiting for all coder waves → dispatch on Wave 1 in parallel with Wave 2 (Pattern B; encoded as `parallel_with` in the Stage Graph)
5. Missing language skills in coder briefs → conductor MECHANICALLY computes `[SKILLS]`; never trust engineer's list. Every coder needs `code-style` + the matching language skill (`rust`/`python`/`typescript`/`go`/...).
6. @engineer dispatched for coder-scope tasks → @engineer is plans only
7. @critic skipped for M+ scope → no exceptions for "obvious" plans
8. Workers dispatched after Wave 1 → IO-bound, batch with Wave 1 START (graph encodes `parallel_with: [wave-1-impl]`)
9. Silent plan rejection → if plan has too few lanes, explicitly reject to engineer
10. Missing `code-style` on coder briefs → mandatory always
11. Soft `[CONTEXT-INVENTORY]` → engineer must fully populate inline; conductor cross-checks against `{paths.ctx}/canonical-types.md`
12. **Skipping the anti-duplication grep** → THE ZERO-TOLERANCE ANTI-PATTERN. Conductor runs every `[DO-NOT-DUPLICATE]` grep BEFORE dispatch (DEDUP-GATE node). Coder-side self-halt is a fallback, not the primary defense.
13. Brief drift from canonical section names → coder rejects with `BRIEF INVALID`
14. **Tunnel vision on current milestone** → Phase 0 must enumerate ALL open issues per `doctrines/issue-ledger-awareness.md`, not just the milestone the seed targets
15. **Off-graph dispatch** → every Agent batch corresponds to a node in the plan's Stage Graph (per `doctrines/stage-graph.md`); mid-walk improvisation is a process violation
16. **Stale `{paths.ctx}/canonical-types.md`** → every dev.0 fires the `CANONICAL-TYPES-REFRESH` worker; subsequent sprints' Phase 0 reads it FIRST

---

## VI. See also

- `pipeline.md` — Stage Graph node taxonomy + edge labels + walk algorithm
- `doctrines/stage-graph.md` — graph-as-dispatch-contract principle
- `doctrines/zero-duplicate-tolerance.md` — DEDUP-GATE pre-dispatch contract + skill auto-attachment
- `references/agent-briefs.md` — copy-paste brief templates + grade cutoffs
- `references/seed-template.md` — canonical seed shape (engineer reads + parses; now includes graph-hint §7-bis)
- `references/branching-model.md` — branch lifecycle + rollover algorithm + hygiene checks
- `doctrines/*.md` — framework-intrinsic rules
- `${CLAUDE_PLUGIN_ROOT}/agents/<role>.md` — agent system prompts (the source of truth for each agent's identity)
