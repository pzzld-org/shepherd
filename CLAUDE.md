# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A dedicated repository for the **shepherd** Claude Code plugin, authored by FL03 (github.com/FL03). The plugin lives at the repo root — the repo *is* the plugin. A self-hosted marketplace manifest at `.claude-plugin/marketplace.json` makes it installable via `/plugin marketplace add fl03/shepherd`.

Shepherd is a sprint-by-sprint version-cycle conductor. A six-agent flock (engineer, critic, coder, auditor, worker, discovery) on a three-section pipeline (INTRODUCTION → BODY → CLOSE), with three meta-orchestrators above (root shepherd, conductor, planter), driven by a project-local `shepherd.toml` in each consumer repo.

There is no build system. Plugin assets are markdown briefs, YAML frontmatter, and shell scripts under `skills/context/scripts/` (the `shctx` runtime).

## Repository layout

```bash
.claude-plugin/
  plugin.json                  # shepherd plugin manifest (this repo IS the plugin)
  marketplace.json             # single-plugin marketplace; source = {"source":"github","repo":"FL03/shepherd"}

agents/{engineer,critic,coder,auditor,worker,discovery}.md   # full system prompts per flock lane
agents/{shepherd,conductor,planter}.md                      # meta-orchestrator profiles (shepherd: root v5.1.6+; conductor + planter: v5.1.4+)
commands/{plant,start,spawn,loop,toolkit,ctx,cleanup,focus}.md   # slash-command entry points
docs/                          # operator docs (configuration, integration, customization)
examples/{rust-service,minimal}/  # binding examples (shepherd.toml + CLAUDE-snippet)

hooks/
  hooks.json                   # event registrations — wires Claude Code lifecycle events to scripts
  scripts/                     # hook implementations (bash, sourced from `_lib.sh`)
  tests/                       # `bash hooks/tests/run.sh` smoke harness

skills/
  shepherd/                    # conductor quick-reference + doctrines + references
    SKILL.md                   # entry point for every /shepherd:* invocation
    {flock,pipeline}.md                          # active skill support files
    doctrines/*.md             # framework-intrinsic rules
    references/*.md            # branching-model, seed-template, grading-rubric, etc.
  context/                     # shctx runtime (SQLite registry, queries, scripts)
    SKILL.md
    schema/                    # SQL migrations + views
    scripts/                   # shctx + cmd_* implementations (bash)
    queries/                   # canonical SQL views materialized for briefs
    references/                # schema docs, naming conventions, profiles
    examples/                  # inject-coder, profile-modifier, journal entries
    styles/                    # bundled per-language code-style defaults
    tests/                     # bash test harness — `bash skills/context/tests/run.sh`

.artifacts/                    # self-dogfooded ctx artifacts (this repo runs shctx on itself)
  docs/{plans,reports,specs,handoffs,journal,diagrams}/  # tracked; v6.1.2 standard layout
  styles/ types/ scripts/ templates/ archive/            # tracked
  toolkit.json                 # tracked; project tool registry (⊕ user-global)
  shepherd.db, shepherd.lock   # gitignored runtime (legacy root.db auto-detected)

.github/                       # workflows + issue templates + dependabot
```

## Installing locally

Three install paths, in increasing order of integration:

```bash
# (a) Direct symlink — fastest dev iteration
ln -s "$PWD" ~/.claude/plugins/shepherd

# (b) Marketplace add via Claude Code (recommended for consumers)
# Inside a Claude Code session:
#   /plugin marketplace add fl03/shepherd
#   /plugin install shepherd@fl03

# (c) Manual marketplace registration (no GitHub round-trip)
mkdir -p ~/.claude/plugins/marketplaces/fl03
cp -r ./.claude-plugin ~/.claude/plugins/marketplaces/fl03/
# Then add a "fl03" entry pointing at that path in ~/.claude/settings.json
```

## Shepherd plugin commands

| Command | Model | What it does |
|---|---|---|
| `/shepherd:plant [scope]` | **Opus recommended** (Fable 5 premium; Sonnet/Haiku allowed, degraded) | Author drift-resistant sprint seeds upstream of execution |
| `/shepherd:start` (solo) | Sonnet | Run one sprint end-to-end in main chat (conductor SOLO mode), then pause |
| `/shepherd:start --teammate` (v5.1.6+) | Sonnet | Lane-execute mode for spawned teammate sessions; skip INTRO/engineer/critic; read assigned lane brief from boot prompt; walk lane micro-Stage-Graph |
| `/shepherd:spawn [sprint_slug] [--scope <sprint\|patch\|minor\|version>] [--parallel <N> \| --auto]` | Sonnet | Main chat adopts **root-shepherd profile** (v5.1.6+); spawns teammate-conductors per the plan's lane-per-conductor structure. `--scope` declares workload scale (default `sprint`). `--auto` aliases `--scope patch`. `--parallel <N>` fans out N sibling sprints for `--scope >= patch`. **Operator-explicit only** — refuses from teammate sessions. See `commands/spawn.md`. |
| `/shepherd:loop [task] [--max N] [--agent worker\|discovery] [--interval D]` | Sonnet | Bounded Loop-Until-Done (Pattern 6) with per-flock-role templates (`skills/shepherd/references/loop-templates.md`). |
| `/shepherd:ponytail [target] [--mode review\|refine] [--apply] [--cement]` (also `/ponytail`) | Sonnet | **v6.1.6** — senior-engineer **review→refine→verify** on a target (diff/path/file/PR), OUTSIDE the sprint pipeline. Runs the senior-engineering standard (`skills/shepherd/doctrines/senior-engineering.md`) through `@auditor` (+ optional `@coder`), adapted to project + user via styles/doctrines/config/priors. Review-only default; `--apply` refines; `--cement` persists observed conventions. |
| `/shepherd:toolkit [list\|add\|rm\|pin\|md ...]` | Sonnet | Manage the **toolkit** (`toolkit.json`, local ⊕ user-global) — registered MCP/skill/plugin/CLI tools surfaced every session so a session never forgets a capability. Wraps `shctx toolkit`. |
| `/shepherd:ctx` | Sonnet | Inspect / refresh the per-project SQLite context registry |

> **Retired (v5.1.4; stub files removed v6.1.3):** `/shepherd:autorun` is superseded by `/shepherd:spawn --auto` (which itself aliases `--scope patch` in v5.1.6+). `/shepherd:parallel` is superseded by `/shepherd:spawn --parallel <N>`. The retired-redirect stub files (`commands/{autorun,parallel}.md`, `skills/shepherd/{autorun,parallel,planter}.md`) were deleted in v6.1.3; the replacements are canonical in `commands/spawn.md`. The `[autorun].min_grade` config key remains live (it governs `--auto` grade gating).

> **v5.1.6 dispatch tier separation:** under `/shepherd:spawn`, `@engineer` and `@critic` become **root-tier-exclusive** (only the root shepherd in main chat may dispatch them). Teammate-conductors surface `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` escalations instead. Under `/shepherd:start` solo mode this restriction does NOT apply — conductor IS root in solo. See `skills/shepherd/doctrines/dispatch-tier-separation.md`.

Shepherd is project-agnostic. Each consumer project configures it via `.claude/shepherd.toml`. The full schema is at `docs/configuration.md`. A working example lives at `examples/rust-service/shepherd.toml`; a stripped-down template at `examples/minimal/shepherd.toml`.

## Shepherd file contracts

When editing shepherd, these invariants must hold:

- **`skills/shepherd/SKILL.md`** is the conductor quick reference — the entry point for every `/shepherd:*` invocation. All runtime references resolve relative to `${CLAUDE_PLUGIN_ROOT}` (which is the repo root, post-migration).
- **`.claude-plugin/plugin.json`** is the plugin manifest. Version bumps must stay in sync with `README.md`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `.claude-plugin/marketplace.json` (BOTH the top-level `version` AND the nested `plugins[0].version`), and `CHANGELOG.md`. `shctx release` automates the five non-CHANGELOG files (its `json` bumper patches both marketplace keys as of v6.0.8); the `CHANGELOG.md` section is always hand-authored. See `skills/context/scripts/cmd_release.sh`.
- **`agents/<role>.md`** — each file is the full system prompt injected into the corresponding flock-agent brief. Do not abbreviate or inline these; the conductor reads them at dispatch time.
- **`agents/shepherd.md`** (v5.1.6+) — canonical **root-tier** profile. Adopted by main chat under `/shepherd:spawn`. Owns engineer/critic dispatch, artifact materialization from teammate payloads, dispute resolution, close-swarm coordination. Single source of truth for root-tier behavior.
- **`agents/conductor.md`** — canonical conductor profile (Tier 2). Adopted by `/shepherd:start` (SOLO mode) and by spawned teammate sessions (TEAMMATE mode). Dual-mode behavior is binding (v5.1.6+): solo retains full surface; teammate is restricted. **Model: sonnet** (downgraded v5.1.6 from `inherit`).
- **`agents/planter.md`** — canonical planter profile (parallel meta). Adopted by `/shepherd:plant`; also loaded by shepherd profile mid-spawn for delegated seed work. Covers escalation response, git custody, cleanup stewardship. **v6.0.8 model policy (#119):** Opus (`claude-opus-4-8` / `[1m]`) is the RECOMMENDED default; Fable 5 (`claude-fable-5`) is the SUPERIOR (pricier) upgrade; Sonnet/Haiku are ALLOWED with a degraded-seed-quality WARNING. The former hard `PLANTER ABORT — wrong model` gate is REPLACED by a soft `PLANTER MODEL ADVISORY` — planting proceeds regardless of model. The planter is also granted the `Agent` tool (front of its `tools:` list) for a strictly bounded read-only `@discovery` wave in plant mode (#119): 1–3 parallel lanes, `subagent_type=shepherd:discovery`, never the flock pipeline.
- **`skills/shepherd/doctrines/*.md`** — framework-intrinsic rules. New doctrines go here; project-specific doctrines go in the consumer repo's `.claude/doctrines/`. v5.1.6 doctrines: `root-shepherd-orchestration.md`, `dispatch-tier-separation.md`, `scope-scale-workload.md`. v5.1.7 doctrine: `sqlite-canonical-state.md`. v5.1.8 doctrine: `claude-code-platform-alignment.md` (maps shepherd's teammate model to Claude Code v2.1.32+ Agent Teams). v6.0.7 doctrine: `workflow-patterns.md` (six-pattern selection doctrine — decision tree, composition grammar, halt codes). v6.0.8 doctrine: `hotfix-dispatch.md` (hotfix cardinality ladder — 1 HF → single subagent via dynamic workflow, never a teammate; 2–5 HF → batched dynamic workflow dispatched by root; ≥6 HF → dedicated HOT-FIX lane + conductor + loop; #135). v6.1.2 doctrines: `toolkit.md` (tool registry — local ⊕ user-global `toolkit.json`, three surfaces [SessionStart hook, `shctx toolkit` CLI, `[TOOLKIT]` brief block], tool-memory sibling of `self-improvement.md`); `loop-templates.md` (per-flock-role Loop-Until-Done catalog, paired with `references/loop-templates.md`). v6.1.3 doctrine: `outcome-enforcement.md` (seeded-outcome enforcement: seed→plan-gate→close→soak seams; paired with `references/loop-templates.md §SOAK-LOOP`). v6.1.4 doctrine: `operator-signaling.md` (session→operator signaling — the planter asks freely, execution sessions stay action-biased; `AskUserQuestion` enabled for planter/root/SOLO-conductor only; codifies seed-recommended-not-required). v6.1.4 reference: `references/glossary.md` (disambiguates the native `Workflow` tool — always present, never `ToolSearch` — from the six workflow patterns and GitHub Actions). v6.1.4 script: `shctx panes` (`skills/context/scripts/cmd_panes.sh`) — teammate-pane observability (status/capture/tail) + dead-pane prune. v6.1.5 doctrines: `autonomous-sentinel.md` (#148 — the authorized supervised-remediation superset of SOAK-LOOP: PROBE → CLASSIFY → ACT [dispatch a ≤S `@coder` hotfix through the hotfix-dispatch ladder → gates-before-deploy → re-probe] → TERMINATE; NEVER fires by default — gated behind `[close].autonomous_sentinel = "on"` [default `"off"`] + a `close: autonomous-sentinel` seed declaration + a complete `sentinel_rails` block; detection-only SOAK-LOOP [`outcome-enforcement.md §Seam 4`] remains the default and the depth-3 remediation-inside-a-watch anti-pattern still binds for the unauthorized case) and `capability-discovery.md` (#146 — auto-detect available Claude Code plugins/skills/tools and adapt without operator wiring; the SessionStart `hooks/scripts/capability_discovery.sh` probe writes an EPHEMERAL capability roster to `<ns>/cache/discovered-capabilities.json` [gitignored — DISTINCT from the curated `toolkit.json`, never overwritten], merged at read time into the `[TOOLKIT]` surfaces [`toolkit_surface.sh` + `shctx toolkit discovered` consumed by `cmd_inject.sh`] labeled auto-discovered, bounded at 12; guarded-integration pattern — "if `/remember` available, use at handoff/CLOSE-FINALIZE + resume; else shepherd-native"; records native `Workflow`-tool presence so spawn/loop degrade to in-context `Agent(...)` when omitted on web/remote sessions; config `[discovery].auto_capabilities = on (default) | off`, resolved via `cfg_get`; zero hot-path cost, never hard-depends, fail-open). v6.1.5 also includes kickoff-hardening + config-auto-scaffold (`shctx config init`) + observability (`shctx dash`), and the strive-higher rule `doctrines/agent-excellence.md` (origin v5.1.1, formalized as a file; cited by every agent profile + `self-improvement.md`/`cache-telemetry.md`/`brief-cache-discipline.md`), plus a reliability follow-up: realigns the agent profiles to `operator-signaling.md` (planter asks freely; execution stays action-biased; teammate-conductor `AskUserQuestion` is `MODE-MISUSE`), corrects the `Workflow`-tool presence claim in `references/glossary.md` to environment-dependent (web/remote sessions may omit it on a supporting build, #146), and repairs two latent defects (`shctx_skill_root` plugin-root resolution that aborted `shctx init`; 9 hooks hardcoding `root.db` instead of `shepherd.db` via the new `hook_db_path()` helper). v6.1.6 doctrines (two lanes): (Lane A — teammates actually leverage the native Workflow tool) `workflow-tool-self-check.md` — the operational front-end consolidating the scattered detect/never-ToolSearch/benefit guidance into ONE recorded first-action self-check (visible-tool-list test → `workflow_tool: present|absent` → compile out-of-context when present [the conductor's OWN benefit: clean context + ≤16 background agents], degrade to in-context `Agent(...)` when absent on web/remote); wired into `agents/{conductor,shepherd}.md` + `commands/{spawn,start}.md` + `references/glossary.md §1` + `capability-discovery.md §V`, enforced by an `@auditor` completeness extension (`PRIMITIVE-INVERSION` when a teammate hand-rolls where the tool was present; `WORKFLOW-SELFCHECK-TOOLSEARCH` when it ToolSearched). (Lane B — senior-dev cementing) `senior-engineering.md` — the "ponytail" doctrine: eight senior primitives for `@auditor` + `@coder` (comprehend-intent/Chesterton's-fence, root-cause-over-symptom, blast-radius-weighted severity, justify-the-tradeoff, conform-to-THIS-project-and-user by precedence ladder, cross-concern systemic-risk detection, bounded restraint, preserved read-only/tier discipline), always-on (cited in both profiles + a `[SENIOR-STANDARD]` brief block gated by `[ponytail].senior_standard`) and the operative contract `/shepherd:ponytail` (`commands/ponytail.md`, also `/ponytail`) invokes on demand; config `[ponytail]`; `SENIOR-STANDARD-MISUSE` anti-pattern. NOTE (v6.1.7 correction): the v6.1.5 "#146 environment-dependent / web-remote-omits-it" claim is RETRACTED — the native `Workflow` tool (Dynamic Workflows) is **enabled across Claude Code entrypoints, web / remote / cloud-container included**; a `ToolSearch` miss on it (or on `TaskCreate`/`TeamCreate`/`SendMessage`) is expected and is NEVER evidence of absence (native primitives are never `ToolSearch` targets). The visible-tool-list test remains the only presence authority; the in-context `Agent(...)` degrade is reached only on an explicit disable / below-floor build. **v6.1.7 doctrines:** `dispatch-generosity.md` (only `@engineer` is count-capped; reach generously for auditor/worker/discovery + bounded loops; out-of-context compiled fan-out makes extra dispatch context-cheap; pull, not policing — no new halt code) and `staged-handoff.md` (`/shepherd:spawn --staged` overlaps a concurrent `/shepherd:plant`, waiting on a durable `seed-ready` mailbox signal; zero new schema). **v6.1.7 also rewrites `operator-signaling.md`:** `AskUserQuestion` is now **planter-only** — execution sessions (root `/shepherd:spawn`, SOLO `/shepherd:start`) no longer carry the tool and reach the operator only via turn-ending pauses; the planter must use the TOOL, never prose (`INLINE-QUESTION-MISUSE`).
- **`hooks/hooks.json`** — wires Claude Code lifecycle events to shepherd's hook scripts. As of v6.0.5 (events unchanged from v5.1.8), registered events: `SessionStart`, `PreToolUse` (Bash/Write/Edit/Agent/Task), `PostToolUse` (Bash/Agent/Task/Edit|Write), `SubagentStop`, `TeammateIdle`, `Stop`, `CwdChanged` (v5.1.8+), `UserPromptSubmit` (v5.1.8+), `WorktreeCreate` (v5.1.8+), `WorktreeRemove` (v5.1.8+). v5.1.8 also introduces shepherd's first uses of `type: "agent"` hooks — embedded prompts that spawn a Haiku subagent to verify Phase 0 mesh "landed in tree" claims (`PostToolUse(Edit|Write)` with `if: "Edit(*.plan.md)"`) and wave-gate cherry-pick state on `Stop`. Both fast-path to `ok: true` when no work is needed; default-on but bounded in cost. **v6.0.5** adds `hooks/scripts/coordinate_drive_guard.sh` as a `Stop` consumer (command type): under `/shepherd:spawn` it blocks a premature root halt while teammates are idle / lead mail is unread (the dispatch-boundary passive-wait bug, `doctrines/coordinate-active-drive.md`); it fast-paths to exit 0 outside spawn sessions, is runaway-bounded (2-nudge cap, fail-open), and is config-gated via `[spawn].coordinate_drive_guard`. **v6.0.7** replaces the `type: "agent"` close-finalize Stop hook with `hooks/scripts/close_finalize_check.sh` (command type, deterministic script): fires only when BOTH signals are positive (strict slug-scoped close report committed in HEAD AND sprint branch still on origin); fast-paths for non-sprint branches, subworktrees, plant-mode artifacts, and missing Signal A/B; no destructive remediation in block reason (#127 fires #1–17 fix). Note: the `PostToolUse(Edit|Write)` `type: "agent"` hook fires on both `Edit` and `Write` tool calls matching `*.plan.md`. Note: `TaskCreated` and `TaskCompleted` events fire on the platform when Agent Teams are enabled but are NOT currently handled by a registered hook script; root must route via the task title prefix observed in `TeammateIdle` or via `SendMessage` WAVE-COMPLETE payloads. See `skills/shepherd/doctrines/claude-code-platform-alignment.md §V`. **v6.0.8 (#121):** all hook scripts resolve artifact paths through a single `${SHEPHERD_WORKDIR}` resolution point in `hooks/scripts/_lib.sh` (`resolve_namespace`): `SHEPHERD_WORKDIR` override → `SHCTX_ROOT_OVERRIDE` → pre-existing `.shepherd/` → pre-existing `.artifacts/` → default `.shepherd/` (now matching the skills-side `resolve_workdir` precedence exactly). Hooks and doctrines must NOT hardcode either literal; this repo and the operator's downstream project both run on a pre-existing `.artifacts/` tree, which is honored (never mass-renamed). **v6.1.4** registers `SessionEnd` (→ `hooks/scripts/tmux_pane_cleanup.sh` — dead-pane cleanup, #66.6, config `[tmux].pane_cleanup`) and a 4th `PreToolUse(Bash)` consumer `hooks/scripts/release_trigger_guard.sh` (blocks creating/publishing `dev.{≥sprints_per_patch}`; raw pre-filter avoids `jq` on non-matching Bash calls; config `[release].devlast_guard`). **v6.1.5** registers a 4th `SessionStart` consumer `hooks/scripts/capability_discovery.sh` (#146 — capability auto-discovery; writes the ephemeral roster `<ns>/cache/discovered-capabilities.json`; config `[discovery].auto_capabilities`).
- **`skills/context/styles/<lang>.md`** are the bundled per-language style defaults shipped with the plugin. `shctx style init <lang>` copies them into a consumer project's `.artifacts/styles/<lang>.md`. The conductor auto-injects the project-local copy into every coder brief whose `[FILE-SCOPE]` matches.
- The flock remains closed at six domain agents (engineer, critic, coder, auditor, worker, discovery), with **three meta-orchestrators** above (v5.1.6+): root `agents/shepherd.md`, conductor `agents/conductor.md`, parallel-meta `agents/planter.md`. The meta tier does NOT open the closed-flock contract. Non-code work goes to `@worker` per `skills/shepherd/doctrines/worker-patterns.md`.

## Skill SKILL.md frontmatter

Every skill's entry point is a `SKILL.md` with required YAML frontmatter:

```yaml
---
name: <slug>
slug: <slug>
version: <semver>
description: |
  ...
metadata:
  triggers:
    - "/skill-name"
---
```

The `triggers` list is what Claude Code uses to match slash commands to skills.

## Sprint orchestration (when running shepherd on this repo)

Shepherd is the *product* here, but this repo dogfoods its own ctx runtime. If you run a `/shepherd:*` sprint on this repo, ensure `.claude/shepherd.toml` exists first (copy from `examples/minimal/shepherd.toml` and adjust). The `.artifacts/` tree is already scaffolded for ctx.

## Versioning

- Shepherd follows semver. MAJOR = closed-flock contract change. MINOR = new commands/doctrines/config keys. PATCH = dispatch logic / brief template fixes.
- Tag format: `v{X}.{Y}.{Z}` (e.g. `v5.0.5`). Docker image is published via `.github/workflows/docker.yml` on `repository_dispatch` or manual trigger.
- Version sources of truth (must move together): `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `README.md` header, `CHANGELOG.md`. `shctx release` plans the bump; review the dry-run before letting it execute.

## Repo invariants — v5.0.0 additions

- `.artifacts/shepherd.db` (v6.1.2; legacy `root.db` is auto-detected via `shctx_db_path()`) is the per-project SQLite registry. Schema lives in `skills/context/schema/`.
- `.artifacts/toolkit.json` is the project-local tool registry (tracked), merged at read time with the user-global `$XDG_CONFIG_HOME/shepherd/toolkit.json`. Managed via `shctx toolkit`; surfaced by `hooks/scripts/toolkit_surface.sh` (SessionStart) and `cmd_inject.sh` (`[TOOLKIT]` block). NEVER store secrets in it.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions. Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Naming: `YYYY-MM-DD-<topic>-{design|spec}.md`.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/`, `.artifacts/cache/`, and `.artifacts/logs/` are gitignored. Tracked subtrees (v6.1.2 standard layout): `.artifacts/docs/` (incl. `docs/plans/`, `docs/reports/`, `docs/{diagrams,handoffs,specs,journal}/`), `.artifacts/profiles/`, `.artifacts/styles/`, `.artifacts/ctx/`, `.artifacts/types/`, `.artifacts/scripts/`, `.artifacts/templates/`, `.artifacts/archive/`, and `.artifacts/toolkit.json`. Legacy top-level `plans/`+`reports/` are still honored (auto-detected); `shctx migrate --layout v2` moves them under `docs/`.
