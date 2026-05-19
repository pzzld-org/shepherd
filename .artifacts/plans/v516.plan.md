---
sprint_slug: v516
patch_slug: v516
patch_branch: v5.1.6
sprint_branch: v5.1.6
tshirt: L
authors:
  - main-chat (opus)
generated_at: 2026-05-19
---

# v5.1.6 — Root-Shepherd Restructure & --scope Flag

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a `shepherd` root-tier profile above `conductor`/`planter`, downgrade `conductor` to sonnet, restrict `@engineer`/`@critic` dispatch to the root tier under spawn, add `/shepherd:spawn --scope <sprint|patch|minor|version>` flag, and lift engineer plan defaults toward ultra-parallel wave composition.

**Architecture:** Three meta tiers. Main chat = `shepherd` (root) when `/shepherd:spawn` is active; remains `conductor` when `/shepherd:start` runs solo (backward-compat). Teammate-conductors execute waves; cannot dispatch engineer/critic; cannot write artifacts (return structured payloads only). The root shepherd owns plan authorship, plan gating, close-audit dispatch, artifact materialization, and inter-teammate dispute resolution.

**Tech Stack:** Markdown agent profiles, YAML frontmatter, bash hooks (`shctx`), `.claude/shepherd.toml` config.

---

## Phase 0 mesh (already complete)

| # | Source | Findings |
|---|---|---|
| 1 | git status / branch | clean; on `v5.1.6`; ahead of `main` by 4 commits (147a1c9 + parents) |
| 2 | PR #42 | OPEN draft, baseRefName main, headRef v5.1.6, 5/5 additions/deletions, milestone v5.1.6, mergeable=MERGEABLE, no checks |
| 3 | Existing agent files | 8 agent files; conductor `inherit`, planter `opus[1m]`, engineer `opus[1m]`, others sonnet |
| 4 | Existing commands | plant, start, spawn, ctx (+ retired autorun/parallel deltas) |
| 5 | Doctrines | 40+ doctrines; no `root-shepherd-*`, `dispatch-tier-*`, or `scope-scale-*` doctrines yet |
| 6 | CHANGELOG | v5.1.5 entry present; v5.1.6 entry missing (this sprint authors it) |
| 7 | GH issues | 27 open; 4 are platform-restriction failure modes (#39, #43, #44, #20-#26 range) |
| 8 | Memory | brief-cache-discipline, dispatch-cascade, specialist-dispatch all already in place; new doctrines layer cleanly on top |

---

## File structure

**Create (NEW):**

- `agents/shepherd.md` — root-tier profile (adopted by main chat under `/shepherd:spawn`)
- `skills/shepherd/doctrines/root-shepherd-orchestration.md` — root-tier behavioral contract
- `skills/shepherd/doctrines/dispatch-tier-separation.md` — who can dispatch whom (3-tier diagram)
- `skills/shepherd/doctrines/scope-scale-workload.md` — `--scope` flag semantics + scale rules
- `.artifacts/plans/v516.plan.md` — THIS FILE

**Modify:**

- `agents/conductor.md` — model `inherit` → `sonnet`; dual-mode behavior (solo vs teammate); teammate-mode write prohibitions
- `agents/engineer.md` — root-exclusive dispatch hard prohibition; ultra-parallel minimum lane counts in body
- `agents/critic.md` — root-exclusive dispatch hard prohibition
- `commands/spawn.md` — `--scope` flag, operator-only invocation check, main-chat adopts `shepherd` (not `planter`) under spawn; planter remains plant-only
- `commands/start.md` — note conductor-solo mode preserved
- `commands/plant.md` — planter scope (no spawn coupling change)
- `skills/shepherd/SKILL.md` — three-tier meta in §I; new doctrines in §XI; `--scope` flag note in §X
- `skills/shepherd/flock.md` — §VI three-tier meta table
- `skills/shepherd/agents/engineer.reference.md` — ultra-parallel minimums (M=6, L=8, XL=10/wave)
- `README.md` — flow diagram + new --scope flag mention
- `CHANGELOG.md` — v5.1.6 entry (top of file)
- `CLAUDE.md` (root of repo) — file contracts updated for shepherd.md addition

**Bumped already (in current branch — no changes):**

- `.claude-plugin/plugin.json` 5.1.6 ✓
- `.claude-plugin/marketplace.json` 5.1.6 ✓
- `skills/shepherd/SKILL.md` frontmatter version 5.1.6 ✓
- `skills/context/SKILL.md` frontmatter version 5.1.6 ✓

---

## Three-tier dispatch model (target)

```
            ┌─────────────────────────────────────────────────────┐
            │   TIER 3 (root)         agents/shepherd.md           │
            │   Main chat under       OWNS: @engineer, @critic     │
            │   /shepherd:spawn       OWNS: artifact writes        │
            │                         OWNS: dispute resolution     │
            └─────────────────────────────────────────────────────┘
                                ▲
                                │ spawns N teammates
                                ▼
            ┌─────────────────────────────────────────────────────┐
            │   TIER 2 (meta)         agents/conductor.md          │
            │   Teammate session OR   solo: dispatches all six     │
            │   main chat solo        teammate: dispatches 4 only  │
            │                         model: sonnet (downgrade)    │
            └─────────────────────────────────────────────────────┘
                                ▲
                                │ dispatches
                                ▼
            ┌─────────────────────────────────────────────────────┐
            │   TIER 1 (flock)        agents/{coder,auditor,       │
            │   Ephemeral subagents          worker,discovery}.md  │
            │                         (engineer/critic = root-tier │
            │                          exclusive under spawn)      │
            └─────────────────────────────────────────────────────┘

            ┌─────────────────────────────────────────────────────┐
            │   META-PLANT (parallel) agents/planter.md            │
            │   Main chat under       OWNS: seed authorship        │
            │   /shepherd:plant       OWNS: babysit during spawn   │
            │                         model: opus[1m]              │
            └─────────────────────────────────────────────────────┘
```

**Solo mode (`/shepherd:start` in main chat, no spawn):** Tier 2 conductor remains the runner. Backward-compatible. Full dispatch surface preserved.

**Spawn mode (`/shepherd:spawn` in main chat):** Tier 3 shepherd is the runner. Main chat owns engineer/critic + artifact writes. Teammate-conductors are wave-executors with restricted dispatch.

---

## --scope flag semantics

| Scope | Sprint count | Behavior |
|---|---|---|
| `sprint` (default) | 1 | Single `dev.N` sprint. Current `/shepherd:spawn` behavior. |
| `patch` | ~10 | Full patch (dev.0..dev.LAST). Replaces explicit `--auto` (which becomes alias). |
| `minor` | ~100 | Multiple patches under a minor version. Experimental — operator confirms. |
| `version` | ~1000 | Multiple minors under a major version. Experimental — operator confirms with hard pause. |

Composes with `--parallel <N>` orthogonally: `--scope patch --parallel 4` fans 4 disjoint sprints from the patch concurrently. Single-axis flags also valid: `--scope patch` ≡ sequential autopilot over the patch.

The 4-tier roadmap (dev=1, patch=10, minor=100, major=1000) in `doctrines/version-scale-roadmap.md` is the scale source-of-truth.

---

## Tasks

### Task 1: Create root-shepherd doctrines (build the contract first)

**Files:**
- Create: `skills/shepherd/doctrines/root-shepherd-orchestration.md`
- Create: `skills/shepherd/doctrines/dispatch-tier-separation.md`
- Create: `skills/shepherd/doctrines/scope-scale-workload.md`

**Why doctrines first:** Every agent profile + command cites these. Authoring doctrines first lets the agent updates reference stable paths.

- [ ] **Step 1.1: Write `root-shepherd-orchestration.md`**
  Contents: root-tier identity, when main chat adopts it, three-mode behavior (idle/dispatch/coordinate), responsibilities (engineer dispatch, critic dispatch, artifact materialization, dispute resolution, close audit dispatch), prohibitions (no code, no coder dispatch when teammates are active — delegate to them, no nested spawn), close-mode flow, escalation triage from teammates.

- [ ] **Step 1.2: Write `dispatch-tier-separation.md`**
  Contents: three-tier diagram, dispatch matrix (who-can-dispatch-whom), restriction enforcement (teammate conductor cannot dispatch engineer/critic — surfaces PLAN-AUTHORSHIP-REQUEST / PLAN-GATE-REQUEST instead), solo-mode exemption (conductor when adopted directly via /shepherd:start retains full dispatch).

- [ ] **Step 1.3: Write `scope-scale-workload.md`**
  Contents: `--scope` flag semantics, 4-tier mapping, composition with `--parallel`, preflight gating (`minor`/`version` require operator double-confirm), sprint-count enumeration algorithm, scope drift surfacing.

- [ ] **Step 1.4: Verify paths resolve**
  ```bash
  ls skills/shepherd/doctrines/{root-shepherd-orchestration,dispatch-tier-separation,scope-scale-workload}.md
  ```
  Expected: three files present.

---

### Task 2: Author `agents/shepherd.md` (root profile)

**Files:**
- Create: `agents/shepherd.md`

- [ ] **Step 2.1: Write the file**
  Frontmatter: `name: shepherd`, `color: gold`, `model: inherit`, `thinking: high`, `description:` (two worked examples), full `tools:` list including Agent, Edit, Write, SendMessage, TaskCreate/Get/List/Update, full MCP read+write set for orchestration.

  Body sections:
  - Role: root-tier orchestrator, adopted by main chat when `/shepherd:spawn` fires
  - Hard prohibitions (no nested spawn, no source code, no direct coder dispatch when teammates own that work)
  - Three modes: idle / dispatch / coordinate
  - Mandatory protocol: load config → adopt profile → dispatch INTRO-COMBO-WAVE → @engineer → @critic gate → spawn teammates → coordinate waves → close-swarm → finalize
  - Halt codes: HARD-STOP, PARALLEL-COLLISION, TEAMMATE-STALL, etc.
  - Escalation triage (from teammates)
  - Operator communication norms
  - Side-effect boundary (writes ALL artifacts that teammate-conductors return as payloads)
  - "What I am NOT" + final reminder

- [ ] **Step 2.2: Sanity-check frontmatter**
  ```bash
  head -60 agents/shepherd.md
  ```
  Expected: clean YAML, no malformed tools list.

---

### Task 3: Restructure `agents/conductor.md`

**Files:**
- Modify: `agents/conductor.md`

- [ ] **Step 3.1: Change model**
  `model: inherit` → `model: sonnet`

- [ ] **Step 3.2: Add dual-mode behavior section**
  New section after "Hard prohibitions" — "Conductor modes":
  - **Solo mode** (`/shepherd:start` in main chat): full dispatch surface (engineer + critic + four-lane flock); writes plans, reports, handoffs; backward-compatible.
  - **Teammate mode** (spawned via `/shepherd:spawn`): restricted dispatch — `@engineer` and `@critic` are root-tier exclusive; surfaces `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` escalations. No file writes — returns structured payloads (close report, wave-complete) via `SendMessage`. Root shepherd materializes artifacts.

- [ ] **Step 3.3: Add hard prohibitions #13–#15 for teammate mode**
  - #13: In teammate mode, NEVER dispatch `@engineer` — surface `PLAN-AUTHORSHIP-REQUEST` escalation.
  - #14: In teammate mode, NEVER dispatch `@critic` — surface `PLAN-GATE-REQUEST` escalation.
  - #15: In teammate mode, NEVER write artifact files (plans, reports, handoffs, close docs) — return structured payloads via SendMessage; root shepherd materializes.

- [ ] **Step 3.4: Update side-effect boundary**
  Add the teammate-mode write restrictions to the table at the bottom of the file. Solo-mode rows preserved unchanged.

- [ ] **Step 3.5: Verify file shape**
  ```bash
  head -10 agents/conductor.md && wc -l agents/conductor.md
  ```
  Expected: `model: sonnet` in frontmatter; total length grew by 40-80 lines.

---

### Task 4: Engineer/critic root-exclusive contracts

**Files:**
- Modify: `agents/engineer.md`
- Modify: `agents/critic.md`

- [ ] **Step 4.1: Add hard prohibition in `engineer.md`**
  Append to "Hard prohibitions" section: "**DO NOT accept dispatch from a teammate-conductor.** You are root-tier-exclusive under `/shepherd:spawn`. If your brief originates from a spawned teammate (detect via `[INVOCATION-CONTEXT]` block listing `dispatcher: teammate-conductor`), HALT immediately with `WRONG-TIER-DISPATCH` — the teammate must surface a `PLAN-AUTHORSHIP-REQUEST` to root instead. Solo-mode `/shepherd:start` dispatch is permitted (the main-chat conductor is root in solo mode)."

- [ ] **Step 4.2: Add hard prohibition in `critic.md`**
  Same pattern, with `PLAN-GATE-REQUEST` as the surface escalation.

- [ ] **Step 4.3: Add `[INVOCATION-CONTEXT]` to engineer/critic brief contracts**
  In each file's brief contract section, add a new bracketed header:
  ```
  [INVOCATION-CONTEXT]
  dispatcher: <root-shepherd | conductor-solo | teammate-conductor>
  spawn_session: <id or "n/a">
  ```
  This is the field engineer/critic check to decide accept/halt.

- [ ] **Step 4.4: Verify**
  ```bash
  grep -n "WRONG-TIER-DISPATCH" agents/engineer.md agents/critic.md
  ```
  Expected: both files contain the new halt code.

---

### Task 5: Ultra-parallel engineer plan template

**Files:**
- Modify: `agents/engineer.md` (body section "What 'ground truth' means" + plan-quality bar references)
- Modify: `skills/shepherd/agents/engineer.reference.md` (the actual reference table)
- Modify: `agents/conductor.md` (body-depth heuristic table)
- Modify: `skills/shepherd/SKILL.md` (body-depth heuristic table)

- [ ] **Step 5.1: Find current minimum lane counts**
  ```bash
  grep -n "M.*4.*~80\|L.*6.*~100\|XL.*6+ per wave" agents/conductor.md skills/shepherd/SKILL.md skills/shepherd/agents/engineer.reference.md
  ```

- [ ] **Step 5.2: Update body-depth heuristic in conductor.md**
  Find existing table (M=4, L=6, XL=6+/wave) and update to:
  | T-shirt | Min coder lanes | Per-lane production | Body LOC floor |
  |---|---|---|---|
  | M | 6 (was 4) | ~80 LOC | ~400 LOC |
  | L | 8 (was 6) | ~100 LOC | ~700 LOC |
  | XL | 10/wave (was 6/wave) | multiple waves | 1500+ LOC |
  Note: numbers raised by 50% to encourage ultra-parallel composition.

- [ ] **Step 5.3: Same update in SKILL.md §III §BODY**

- [ ] **Step 5.4: Update engineer.reference.md "Minimum coder lanes by sprint T-shirt"**
  Same numbers.

- [ ] **Step 5.5: Update "Anti-pattern #11" wording**
  Change "Too-few coder lanes" → "Too-few coder lanes (M<6, L<8, XL<10/wave) → reject back to engineer; split mercilessly — if a lane touches >5 files, decompose."

- [ ] **Step 5.6: Update flock.md §II @coder "Minimum lane count" section to match**

---

### Task 6: /shepherd:spawn refinements

**Files:**
- Modify: `commands/spawn.md`

- [ ] **Step 6.1: Add operator-only invocation check (Check 0)**
  At top of preflight, add Check 0:
  ```
  ### Check 0 — Operator-only invocation
  Refuse if invoked from a non-main-chat session. Detection:
    - $CLAUDE_AGENT_TEAMMATE_NAME is set (subagent or teammate session)
    - $CLAUDE_PROJECT_SESSION_TYPE == "teammate"
  Refuse with: "/shepherd:spawn — REFUSED: Nested spawn forbidden. Subagents and teammate-conductors cannot spawn further teammates. Surface the request to the root shepherd session."
  ```

- [ ] **Step 6.2: Add --scope flag section**
  After § Preflight, new section § --scope flag:
  ```
  ### --scope <sprint|patch|minor|version>

  Scales the workload before any teammate spawns. Default: sprint.

  | Scope | Sprint count | Composes with |
  |---|---|---|
  | sprint  | 1                | --parallel <N> N=1 (no fanout) |
  | patch   | sprints_per_patch | --parallel <N>, --auto (alias) |
  | minor   | patches_per_minor × sprints_per_patch | experimental — confirm |
  | version | minors_per_major × patches_per_minor × sprints_per_patch | experimental — hard pause |

  Implementation:
  - sprint: existing single-sprint behavior
  - patch: existing --auto behavior (loop sequentially; or --parallel <N> for fanout)
  - minor: enumerate patches under current minor; loop or fanout per --parallel
  - version: hard pause + operator double-confirm before any spawn

  Per `doctrines/scope-scale-workload.md`.
  ```

- [ ] **Step 6.3: Update profile-adoption section**
  Currently: "Main chat adopts the planter profile (§Adopt the planter profile)."
  Change to: "Main chat adopts the **shepherd** root profile (`agents/shepherd.md`). The planter profile is loaded only under `/shepherd:plant` or when seed authorship is delegated mid-spawn. See `doctrines/root-shepherd-orchestration.md` §Two-meta-loading."

- [ ] **Step 6.4: Update teammate prompt boot block**
  In the boot prompt template under § Build the teammate prompt:
  - Add: `ROOT-SESSION-NAME: shepherd-root @ {main_chat_session_id}`
  - Add: `INVOCATION-CONTEXT.dispatcher: teammate-conductor` (passed into every engineer/critic brief the teammate might attempt — they'll halt with WRONG-TIER-DISPATCH per Task 4)
  - Update HARD PROHIBITIONS to add: "NO dispatching @engineer or @critic — surface PLAN-AUTHORSHIP-REQUEST / PLAN-GATE-REQUEST escalations. NO artifact writes — return structured payloads via SendMessage."

- [ ] **Step 6.5: Update preflight Check 1 for --scope=minor/version**
  Add hard-pause prompts requiring operator typing the literal string `confirm minor` or `confirm version` before any spawn fires.

- [ ] **Step 6.6: Update argument-hint frontmatter**
  ```yaml
  argument-hint: "[ sprint_slug ] [ --scope sprint|patch|minor|version ] [ --parallel <N> | --auto ]"
  ```

- [ ] **Step 6.7: Verify**
  ```bash
  grep -n "Check 0\|--scope" commands/spawn.md | head -20
  ```

---

### Task 7: Cross-cutting updates (SKILL.md, flock.md, start.md, plant.md, README.md, CLAUDE.md)

**Files:**
- Modify: `skills/shepherd/SKILL.md` (§I three-tier flock map)
- Modify: `skills/shepherd/flock.md` (§VI meta tier)
- Modify: `commands/start.md` (note solo-mode preserved)
- Modify: `commands/plant.md` (no functional change; cross-ref updates)
- Modify: `README.md` (flow diagram, --scope mention)
- Modify: `CLAUDE.md` (file contracts updated for shepherd.md)

- [ ] **Step 7.1: Update SKILL.md §I "The flock (closed at six)" table**
  Add note about three-tier meta below the flock table:
  > **Three-tier meta** (above the flock): `agents/shepherd.md` (root, adopted by main chat under `/shepherd:spawn`), `agents/conductor.md` (sprint-runner, model: sonnet, dual-mode), `agents/planter.md` (seed-author + babysitter, model: opus[1m]). See `doctrines/dispatch-tier-separation.md`.

- [ ] **Step 7.2: Update SKILL.md §X "Invocation" table**
  Add --scope row entry under `/shepherd:spawn`.

- [ ] **Step 7.3: Update SKILL.md §XI "See also" file map**
  Add three new doctrine rows:
  - `doctrines/root-shepherd-orchestration.md`
  - `doctrines/dispatch-tier-separation.md`
  - `doctrines/scope-scale-workload.md`

- [ ] **Step 7.4: Update flock.md §VI "Meta tier"**
  Expand the two-row table to three rows (shepherd, conductor, planter). Update narrative to reflect the three-tier dispatch model. Cite `dispatch-tier-separation.md`.

- [ ] **Step 7.5: Update commands/start.md**
  Add Step 1 note: "When invoked in main chat (solo mode), the conductor profile retains its full dispatch surface (engineer + critic + four-lane flock). The dispatch-tier-separation only restricts conductors running as teammates under /shepherd:spawn."

- [ ] **Step 7.6: Update README.md**
  - Bump version mention from v5.1.5 to v5.1.6
  - Add `--scope` flag note in the command table
  - Add brief sentence on three-tier meta

- [ ] **Step 7.7: Update CLAUDE.md**
  Add `agents/shepherd.md` to the "Shepherd file contracts" section bullet list. Update flock description to mention root tier.

---

### Task 8: CHANGELOG v5.1.6 entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 8.1: Insert v5.1.6 section above v5.1.5**

  ```markdown
  ## v5.1.6 — 2026-05-19

  ### Root-shepherd tier + dispatch separation + --scope flag

  Introduces a `shepherd` root-tier profile that main chat adopts under
  `/shepherd:spawn`, downgrades the `conductor` to Sonnet with dual-mode
  behavior (solo retains full surface, teammate is wave-executor only),
  restricts `@engineer` and `@critic` dispatch to the root tier, adds
  `/shepherd:spawn --scope <sprint|patch|minor|version>`, and lifts the
  engineer plan minimum lane counts toward ultra-parallel composition
  (M=6, L=8, XL=10/wave).

  #### New

  - **`agents/shepherd.md`** — root-tier profile (model: inherit). Owns
    `@engineer` + `@critic` dispatch, artifact materialization from
    teammate payloads, dispute resolution, and close-swarm coordination
    when spawn is active.
  - **`doctrines/root-shepherd-orchestration.md`** — root-tier behavioral
    contract: three modes (idle/dispatch/coordinate), responsibilities,
    prohibitions, escalation triage protocol.
  - **`doctrines/dispatch-tier-separation.md`** — three-tier dispatch
    matrix (root/conductor/flock); restriction enforcement; solo-mode
    exemption for conductor.
  - **`doctrines/scope-scale-workload.md`** — `/shepherd:spawn --scope`
    flag semantics, 4-tier mapping, composition with `--parallel`,
    preflight gating for `minor`/`version` scopes.

  #### Changed

  - **`agents/conductor.md`** — `model: inherit` → `model: sonnet`. New
    dual-mode behavior section: solo mode (`/shepherd:start`) retains
    full dispatch surface + writes; teammate mode (`/shepherd:spawn`)
    restricted (no `@engineer`/`@critic`, no artifact writes). Three
    new hard prohibitions (#13–#15).
  - **`agents/engineer.md`** + **`agents/critic.md`** — new
    `WRONG-TIER-DISPATCH` halt code; root-tier-exclusive contract under
    spawn; new `[INVOCATION-CONTEXT]` brief field.
  - **`commands/spawn.md`** — new Check 0 (operator-only invocation;
    nested spawn forbidden), new `--scope` flag section, main chat now
    adopts `agents/shepherd.md` (not `planter.md`) under spawn, updated
    teammate boot prompt with INVOCATION-CONTEXT, hard-pause prompts for
    `--scope=minor` and `--scope=version`.
  - **Engineer plan template** — minimum lane counts raised: M=6 (was 4),
    L=8 (was 6), XL=10/wave (was 6/wave). Body LOC floor scaled
    accordingly (M=400, L=700, XL=1500+).

  #### Open questions / known gaps (filed as GH issues)

  - In-process teammates cannot dispatch agents (mirror of Claude Code
    #31977) — recommend `tmux` `teammateMode` for `/shepherd:spawn`.
  - `--scope=minor` and `--scope=version` ship gated behind
    double-confirm prompts; full preflight semantics for cross-patch /
    cross-minor walks are deferred to v5.2.0.

  ### Migration notes

  Operators running `/shepherd:start` in main chat see no behavior
  change — conductor profile remains the runner in solo mode. Operators
  using `/shepherd:spawn` now have main chat adopt the `shepherd` root
  profile instead of `planter`; the planter profile is loaded only by
  `/shepherd:plant` or when seed authorship is delegated mid-spawn.

  ---
  ```

- [ ] **Step 8.2: Verify**
  ```bash
  head -20 CHANGELOG.md
  ```
  Expected: v5.1.6 entry is now the top section.

---

### Task 9: File failure-mode GH issues

**Files:** none — uses `gh issue create`

- [ ] **Step 9.1: Issue: teammate engineer dispatch overreach (v5.1.5 sprint failure mode)**
  Title: `failure-mode(v5.1.5): teammate-conductor dispatched @engineer/@critic; root-tier separation needed`
  Body: documents the discovered failure mode → links to dispatch-tier-separation.md doctrine and engineer.md/critic.md WRONG-TIER-DISPATCH halt code.
  Labels: `bug`, `plugin`
  Milestone: v5.1.6

- [ ] **Step 9.2: Issue: in-process teammates blocked on #31977**
  Title: `restriction: in-process teammates cannot dispatch flock under /shepherd:spawn (upstream #31977)`
  Body: documents the platform restriction + tmux workaround + forward-compat readiness.
  Labels: `bug`, `plugin`
  Milestone: v5.1.6

- [ ] **Step 9.3: Issue: --scope=minor/version operational gaps**
  Title: `enhancement: complete --scope=minor and --scope=version preflight + sprint enumeration`
  Body: lists deferred semantics — cross-patch walk, cross-minor walk, error budget scaling, milestone rollover gating.
  Labels: `enhancement`, `plugin`
  Milestone: (no milestone — future)

- [ ] **Step 9.4: Verify**
  ```bash
  gh issue list --milestone v5.1.6 --limit 10
  ```
  Expected: the two milestone-v5.1.6 issues present.

---

### Task 10: Commit + ready PR #42 for squash-merge

**Files:** git

- [ ] **Step 10.1: Verify clean diff**
  ```bash
  git status
  git diff --stat
  ```
  Expected: ~15–18 files changed, ~1500–2500 added, ~150–250 removed.

- [ ] **Step 10.2: Stage + commit**
  ```bash
  git add -A
  git commit -m "$(cat <<'EOF'
  v5.1.6: root-shepherd tier + dispatch separation + --scope flag

  - agents/shepherd.md (NEW) — root-tier profile (main chat under /shepherd:spawn)
  - agents/conductor.md — model: inherit → sonnet; dual-mode (solo full / teammate restricted)
  - agents/engineer.md + critic.md — root-tier-exclusive; WRONG-TIER-DISPATCH halt
  - commands/spawn.md — Check 0 (operator-only); --scope sprint|patch|minor|version
  - Plan template ultra-parallel: M=6, L=8, XL=10/wave (was 4/6/6)
  - Three new doctrines: root-shepherd-orchestration, dispatch-tier-separation, scope-scale-workload
  - CHANGELOG.md v5.1.6 entry
  - SKILL.md / flock.md / README.md / CLAUDE.md cross-refs

  Signed-off-by: FL03 <joe@pzzld.org>
  EOF
  )"
  ```

- [ ] **Step 10.3: Push**
  ```bash
  git push origin v5.1.6
  ```

- [ ] **Step 10.4: Mark PR #42 ready for review**
  ```bash
  gh pr ready 42
  ```

- [ ] **Step 10.5: Squash-merge**
  ```bash
  gh pr merge 42 --squash --delete-branch
  ```
  Expected: merge into main, branch deleted on GitHub, release.yml workflow fires (PR title `vX.Y.Z` pattern matches).

- [ ] **Step 10.6: Switch back to main + sync**
  ```bash
  git checkout main
  git pull origin main
  git branch -D v5.1.6   # local cleanup
  ```

- [ ] **Step 10.7: Verify release workflow**
  ```bash
  sleep 30 && gh run list --limit 5
  ```
  Expected: release workflow ran on `main` push.

---

## Self-review

**Spec coverage:**

| User request | Task |
|---|---|
| Root profile `shepherd` for main chat | Tasks 1, 2 |
| Teams = work-only (engineer/critic root-exclusive) | Tasks 3, 4 |
| Conductor sonnet downgrade | Task 3 |
| Conductor no writes (teammate mode) | Task 3 |
| Single session, N sonnet conductor teammates | Task 6 (spawn already supports --parallel; --scope adds work scaling) |
| Ultra-parallel engineer plan template | Task 5 |
| /shepherd:spawn refined to prevent nested invocation | Task 6 (Check 0) |
| --scope sprint\|patch\|minor\|version | Tasks 1.3, 6.2 |
| Update CHANGELOG | Task 8 |
| Squash-merge PR #42 | Task 10 |
| Open issues for failure modes | Task 9 |

All requests covered.

**Placeholder scan:** No TBD/TODO in this plan — every step has concrete content. Inline code blocks where needed.

**Type consistency:** Halt code `WRONG-TIER-DISPATCH` used in Tasks 4 + 6 + 8 + 10 commit message — consistent. Three doctrine paths used everywhere — consistent.

---

## Notes

- Backward compat: `/shepherd:start` solo mode is **unchanged**. The whole restructure surfaces only under `/shepherd:spawn`.
- The conductor model change (`inherit` → `sonnet`) lowers cost for ALL conductor invocations, including `/shepherd:start` solo. This is per operator request.
- The planter profile is **unchanged** — still opus[1m], still loaded under `/shepherd:plant` or when seed authorship is delegated mid-spawn.
- This plan does NOT touch `skills/context/` (`shctx`), hooks, or any test infrastructure. Pure profile + command + doctrine restructure.
