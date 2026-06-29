# 🐑 shepherd

[![GitHub License](https://img.shields.io/github/license/FL03/shepherd?style=for-the-badge&logo=github)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/FL03/shepherd?style=for-the-badge&logo=github)](https://github.com/FL03/shepherd/releases)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-d97757?style=for-the-badge)](https://github.com/FL03/shepherd)

> **Turn one Claude Code session into a disciplined release engineer.** Shepherd drives a closed six-agent flock through repeatable, audited sprint pipelines, with mechanical guardrails that refuse drift before it happens.

Shepherd is a [Claude Code](https://claude.com/claude-code) plugin for **long-running engineering work**: multi-hour sprints, full patch arcs, parallel feature lanes. Instead of one model improvising its way through a large task and slowly losing the plot, you get a structured pipeline with fixed roles, gated phases, read-only audits, a per-project memory, and hooks that hard-block the failure modes long sessions are prone to.

It is a behavioral layer, not a heavy framework. There is no build step and no server. Everything ships as markdown briefs, YAML frontmatter, shell scripts, and a SQLite registry. It wires together Claude Code's native primitives (subagents, Agent Teams, the `/loop` scheduler, hooks) so they stay focused and on-task over a long horizon.

```text
┌────────────────────────────────────────────────────────────────────────┐
│  /shepherd:plant     Author drift-resistant sprint seeds (Opus)         │
│  /shepherd:start     Run ONE sprint end-to-end, then pause for sign-off  │
│  /shepherd:spawn     Root + teammate-conductor lanes (Agent Teams)       │
│                        --scope <sprint|patch|minor|version>             │
│                        --parallel <N> | --auto                          │
│  /shepherd:focus     Keep the session on-task (focus loop + heartbeat)  │
│  /shepherd:loop      Bounded loop-until-done (per-role templates)        │
│  /shepherd:toolkit   Tool registry, so a session never forgets a tool   │
│  /shepherd:ctx       Inspect / refresh the per-project SQLite context    │
│  /shepherd:cleanup   Prune stale teammates, worktrees, locks            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Contents

- [Why shepherd](#why-shepherd)
- [How it works in 60 seconds](#how-it-works-in-60-seconds)
- [Install](#install)
- [Quickstart](#quickstart)
- [Commands](#commands)
- [Usage playbooks](#usage-playbooks)
- [Under the hood](#under-the-hood)
- [Configure](#configure)
- [Compose with your own skills](#compose-with-your-own-skills)
- [Troubleshooting and FAQ](#troubleshooting-and-faq)
- [File map](#file-map)
- [Versioning](#versioning)
- [Contributing](#contributing)
- [License](#license)

---

## Why shepherd

A naive long-running Claude session fails in predictable ways. Shepherd answers each one with a mechanism, not a suggestion.

| Failure mode | What goes wrong | Shepherd's mechanism |
| :--- | :--- | :--- |
| **Tunnel vision** | The session fixates on the current task and ignores the 200-issue ledger underneath. | Phase 0 mesh enumerates every open issue and PR, and surfaces out-of-milestone CRITICAL/HIGH as drift risks before any code is written. |
| **Duplication** | Types and helpers get re-invented because nobody grepped first. | A `[DO-NOT-DUPLICATE]` grep gate ships in every coder brief; a write-time hook blocks a new symbol that reuses an existing name or field shape. |
| **Scope drift** | Sprints quietly grow features that were never seeded. | Every brief is anchored to the seed; the auditor's `completeness` concern fails any lane that drifted. |
| **Audit theater** | "It passed review" because the reviewer was the context that wrote the code. | A read-only auditor swarm (3 to 5 agents, split by concern) reviews in parallel, dispatched from a separate tier. |
| **Wrapper bloat** | Hollow structs and indirection added for structure's sake. | A wrapper gate at sprint close plus a `subtract-don't-add` doctrine that asks for net-negative lines, deps, and abstractions. |
| **Release malpractice** | Squash-merging unsigned, untested, un-tagged commits. | The conductor drives the full squash-to-main pipeline with ordered gates and signed commits. |
| **Going off-task after hours** | On a multi-hour sprint the root slowly drifts from the objective. | A **focus loop** that survives compaction natively, plus a **focus heartbeat** that re-anchors the root to the objective on a cadence and self-checks for drift. |
| **Passive stalls** | The root spawns helpers and then just waits, doing nothing. | A coordinate-active-drive contract plus a Stop hook that mechanically blocks a premature halt while work is outstanding. |

If you have ever watched a long agent run produce a confident summary of work it did not actually finish, shepherd is built for exactly that gap.

---

## How it works in 60 seconds

Three ideas, and you have the model.

**1. A closed flock of six agents.** Each has one job and a fixed dispatch contract.

| Agent | Job |
| :--- | :--- |
| `@engineer` | Audits ground truth, then authors the sprint plan. |
| `@critic` | Adversarially reviews the plan and the money-paths before any code. |
| `@coder` | The only role that writes production code, dispatched in parallel waves. |
| `@auditor` | Read-only reviewer; a swarm at sprint close, split by concern. |
| `@worker` | Bounded catch-all: monitoring, ops, research summaries, cleanup. |
| `@discovery` | Read-only orientation and research. |

The flock is closed on purpose. Adding a seventh role is a major-version decision, not a casual one. Non-code work goes to `@worker`; research goes to `@discovery`.

**2. A three-section pipeline.** Every sprint runs the same shape:

```text
INTRODUCTION   ground-truth mesh  ->  @engineer plan  ->  @critic gate
     │
BODY           coder waves with between-wave gates (format / check / lint)
     │           auditor swarm overlaps the last wave
     │
CLOSE          merge -> tag -> squash-to-main -> carry-forward -> close report
```

**3. Three meta tiers that drive it.** A planter authors seeds, a conductor runs a sprint or a lane, and a root shepherd coordinates parallel teammate-conductors. You rarely think about the tiers directly; you pick a command and the right tier is adopted for you.

Everything else (the SQLite memory, the toolkit, the loop templates, the hooks) exists to keep those three ideas honest over a long session.

---

## Install

### From the marketplace (recommended)

```text
/plugin marketplace add FL03/shepherd
/plugin install shepherd@fl03
```

This registers the self-hosted marketplace manifest and installs shepherd as a managed plugin. Update later with `/plugin update shepherd@fl03`.

### Personal install via symlink

```bash
git clone https://github.com/FL03/shepherd.git ~/src/FL03/shepherd
ln -s ~/src/FL03/shepherd ~/.claude/plugins/shepherd
```

### Per-project pin

```bash
mkdir -p .claude-plugin
ln -s /path/to/FL03/shepherd .claude-plugin/shepherd
```

Shepherd has no build system. Runtime dependencies are `git`, `bash`, `sqlite3`, and `jq` (`sqlite3` ships on macOS; install `jq` with `brew install jq` or your package manager). The GitHub issue and PR ledger that powers the Phase 0 mesh also needs the `gh` CLI; without it, that step is skipped rather than failing. It works across the Claude Code CLI, web, and IDE entrypoints.

---

## Quickstart

From zero to your first audited sprint in about five minutes.

```bash
# 1. Configure shepherd for this repo (one file, lives in your repo).
#    Start from the bundled example and edit it to match your gates + branch scheme.
cp /path/to/shepherd/examples/minimal/shepherd.toml .claude/shepherd.toml

# 2. Initialize the per-project context registry.
#    Run this from inside Claude Code:
/shepherd:ctx
#    or directly:  shctx init && shctx refresh --scope=all && shctx status
```

Then, in Claude Code:

```text
# 3. Author the first sprint seed (Opus recommended for seed quality).
/shepherd:plant

# 4. Switch to Sonnet and run the sprint end-to-end.
/shepherd:start
```

`/shepherd:start` runs one full sprint (mesh, plan, critic gate, coder waves, audit swarm, close) and then **pauses** for your sign-off before touching the next one. That pause is deliberate: the first sprint is where you confirm the gates, branch patterns, and seed quality are right for your repo.

Once a sprint or two has gone clean, graduate to `/shepherd:spawn --auto` to run a whole patch arc, or `/shepherd:spawn --parallel 3` to fan out independent sprints across worktrees. See the [playbooks](#usage-playbooks).

> A minimal `shepherd.toml` and a worked multi-crate Rust example both live in [`examples/`](examples/). If you skip the config file, shepherd warns at every invocation and falls back to sensible Rust-project defaults.

---

## Commands

| Command | What it does |
| :--- | :--- |
| `/shepherd:plant [scope]` | Author drift-resistant sprint seeds. Scope is one of: nothing (next sprint plus lookahead), `dev.N`, `dev.N..dev.M`, `arc` (whole patch), or `next-version`. Opus recommended. |
| `/shepherd:start [--teammate]` | Run one complete sprint, then pause for sign-off. The lightweight solo path: one sprint, no teams, no lanes. |
| `/shepherd:spawn [slug] [--scope ...] [--parallel N \| --auto]` | The primary command for substantive work. Main chat becomes the root shepherd and spawns one teammate-conductor per lane via Agent Teams. |
| `/shepherd:focus [...] [--heartbeat]` | Start or refresh the sprint focus loop, or fire a re-anchor heartbeat now. Keeps a long session locked onto the objective. |
| `/shepherd:loop [task] [--max N] [--agent ...] [--interval ...]` | Run a bounded loop-until-done with a per-role template. Dispatches `@worker` or `@discovery` until a "no new findings" condition or the iteration cap. |
| `/shepherd:toolkit [list\|add\|rm\|pin\|md]` | Manage the tool registry so the session never forgets that an MCP server, skill, plugin, or CLI exists. |
| `/shepherd:ctx` | Inspect or refresh the per-project SQLite context registry. |
| `/shepherd:cleanup` | Prune stale or crashed teammate entries, leftover worktrees, and lock files. |

`/shepherd:start` and `/shepherd:spawn` are disjoint execution paths, not a wrapper relationship. Start is solo and in-session; spawn is multi-lane via Agent Teams. Plant feeds both.

---

## Usage playbooks

Concrete recipes for the situations you will actually hit.

### "I want to run one careful sprint and review it myself"

```text
/shepherd:start
```

Use this when you are new to shepherd on a repo, when the change is delicate, or when you want a hand on the wheel. It runs the full pipeline once and stops. Inspect the close report, then run it again for the next sprint.

### "I want to autopilot a whole patch"

```text
/shepherd:spawn --auto
```

`--auto` is an alias for `--scope patch`. It runs sequential sprints to patch completion, with a fresh context per sprint so quality does not decay as the patch grows. Each sprint still gets its plan, gates, and audit.

### "I have independent work that can run in parallel"

```text
/shepherd:spawn --parallel 3
```

Fans out three disjoint sprints across separate git worktrees, each driven by its own teammate-conductor. Use this when the work decomposes into slices that do not touch the same files. The root coordinates and merges each lane as it goes green.

### "I want to plan ahead before executing"

```text
/shepherd:plant arc          # seed the entire patch arc
/shepherd:plant dev.5        # seed a specific sprint
/shepherd:plant dev.5..dev.7 # seed a range
```

Seeds are the ground truth the engineer translates into a plan. A good seed is dense and drift-resistant. Author seeds with Opus; Sonnet and Haiku work but produce a degraded-seed advisory.

### "My long sprint keeps drifting off-task after a few hours"

This is what the **focus heartbeat** is for. The focus loop already re-anchors the orchestrator at every wake and survives compaction. The heartbeat adds a cadence *inside* a long active stretch, where no teammate event forces a wake:

```text
/shepherd:focus --objective "ship the v6.3 auth migration" --invariants '["no schema change without approval"]'
# later, if you sense it wandering:
/shepherd:focus --heartbeat
```

On `--heartbeat`, and automatically every `[focus].heartbeat_actions` orchestrator actions (default 20), the root re-reads its objective and emits a compact re-anchor block, then self-checks: did the last stretch actually advance the active node within the invariants? If it wandered into adjacent or unseeded work, it stops, returns to the objective, and files the digression instead of chasing it inline. For a true wall-clock cadence, set `[focus].heartbeat_interval = "45m"` and let the native `/loop` own the clock.

### "What does shepherd already know about this repo?"

```text
/shepherd:ctx
```

Inspects the SQLite registry: indexed code symbols, GitHub issues / PRs / releases, artifact files, project memories, flock profiles, and the event log. Refresh it whenever the repo state has moved on.

### "I need to poll or monitor something until a condition holds"

```text
/shepherd:loop "watch CI for the release tag, report when green" --agent worker --max 12 --interval 5m
```

Runs a bounded loop with a hard cap and a measurable termination predicate. Loops are never open-ended.

### "Clean up after a parallel run"

```text
/shepherd:cleanup
```

Prunes stale or crashed teammate entries, removes leftover worktrees, and clears lock files. Operator-confirmed; it never silently removes a live lane.

---

## Under the hood

### The closed flock

Six agents, fixed contracts. `@engineer` runs on Opus (plan quality is worth it); the rest default to Sonnet. The contract changes only on a major version bump, so you can rely on the role boundaries staying put. Coders are the only role that writes production code, and they are always scoped to a disjoint set of files so parallel waves cannot collide.

### The three-section pipeline

- **Introduction.** A Phase 0 mesh audits ground truth (open issues and PRs, recent Sentry / Supabase / Fly state, carry-forwards from prior sprints). The engineer then authors the plan, and the critic gates it adversarially before a single line is written.
- **Body.** Coder waves run with gates between them (`format`, `check`, `lint`, all configurable). The auditor swarm overlaps the last wave so review is not a serial tail.
- **Close.** Merge, tag, squash-to-main, carry-forward refresh, and a written close report. Under `/shepherd:spawn`, the body fans out as lanes (vertical slices across waves), each owned by a teammate-conductor.

### The three meta tiers

| Tier | Profile | Adopted under | Role |
| :--- | :--- | :--- | :--- |
| Root | `agents/shepherd.md` | `/shepherd:spawn` | Dispatches engineer and critic, materializes teammate output, resolves disputes, coordinates the close swarm. |
| Conductor | `agents/conductor.md` | `/shepherd:start` (solo) or a spawned teammate | Executes a sprint or a single lane. |
| Planter | `agents/planter.md` | `/shepherd:plant` | Authors seeds and stewards git custody and cleanup. |

### Phase 0 mesh

Every sprint opens with a structured ground-truth audit. The engineer cannot skip it, and the auditors verify it was complete. This is the antidote to tunnel vision: the full open-issue ledger is enumerated and classified, and anything CRITICAL or HIGH outside the current milestone is surfaced as a drift risk.

### SQLite context registry

`/shepherd:ctx` manages a per-project SQLite database at `.shepherd/shepherd.db`. It indexes code symbols, GitHub state, artifact files, project memories, flock profiles, lock history, and an event log. It backs the deduplication fast-path and the carry-forward ledger.

```bash
shctx init                   # scaffold .shepherd/ and create the database
shctx refresh --scope=all    # populate the caches
shctx status                 # verify
shctx style init --all       # scaffold per-language code-style files
```

The workdir follows a standard layout under `.shepherd/` (`docs/`, `logs/`, `cache/`, `scripts/`, plus `toolkit.json` and `shepherd.db`). Repos on the older layout keep working untouched; `shctx migrate --layout v2` performs the opt-in move.

### Self-evaluation (the eval harness)

A plugin that scores its own latent instructions. `shctx eval` grades a latent agent output (a conductor reflection, a discovery report, a seed) against a rubric, judged by your **local Claude Code** — not a hosted API. The split shepherd preaches, applied to itself: the model's per-dimension scores are latent; the rubric, the weighted overall, and the threshold verdict are deterministic, so the same scores always yield the same verdict.

```bash
echo "front-load the dups gate before the coder wave next sprint" \
  | shctx eval run --kind=reflection -        # score text; exit 0 pass / 1 fail
shctx eval run --kind=reflection --sprint=$(git branch --show-current) --record
shctx eval report --md                        # recorded verdicts, surfaced on the dash too
```

Adding a new subject is one JSON file in `services/eval/rubrics/`. The judge runs through `services/llm`, the single owner of every model call. Two test lanes: a free, deterministic gate lane (the judge is mocked) and a paid live lane (`SHEPHERD_EVAL_LIVE=1`) that proves a real judge separates good outputs from bad. See `services/eval/README.md`.

### The toolkit

A session forgets capabilities exist. The toolkit (`toolkit.json`) is a mutable registry of the tools you actually use, so it does not. It merges a project-local file with a user-global one, surfaces a compact roster at session start, and injects a `[TOOLKIT]` block into the briefs that need it.

```bash
shctx toolkit add --name=context7 --type=mcp --scope=global \
  --description="library docs; prefer over web search" --pin
shctx toolkit list --scope=all
```

Never store secrets in the toolkit.

### Loop templates and the focus heartbeat

`/shepherd:loop` runs the loop-until-done pattern as a first-class, bounded loop. Each flock role has a ready-made template (coder fix-until-green, discovery research-until-exhausted, worker monitor-and-reconcile, auditor progressive-audit), and each declares a hard cap and a measurable termination predicate.

The orchestrator runs its own variant, the **FOCUS-LOOP**, across an entire sprint to keep drive continuity through compaction and wave boundaries. The focus record (objective, active node, invariants, obligations) lives in SQLite and survives compaction natively.

New in v6.2.2, the **FOCUS-HEARTBEAT** closes the remaining gap. The focus loop re-anchors at every wake, but a long active stretch with no wake (a big materialization run, or a solo conductor doing inline work) is where the orchestrator drifts after hours. The heartbeat self-fires a re-anchor on a cadence: set `[focus].heartbeat_interval` and the native `/loop` owns the clock (the deterministic leg, a real wake on a real schedule), or lean on `[focus].heartbeat_actions` as a soft, zero-cost self-prompt. On each beat it re-reads the objective from the record, restates it, and runs a self-drift-check. If the last stretch wandered off the active node, it returns to the objective and files the digression instead of chasing it. The cost is a few tokens, never a cache eviction.

### Per-language style files

Project-local code-style overrides live at `.shepherd/styles/<lang>.md` (rust, python, typescript, go, shell, sql), tracked in git. The conductor injects the matching style file into every coder brief whose file scope touches that language.

```bash
shctx style init rust   # scaffold from bundled defaults
shctx style edit rust   # open in $EDITOR
```

### Mechanical enforcement hooks

Shepherd ships a hook suite wired through `hooks/hooks.json`. These are guards, not guidance: they hard-refuse the action.

- **`dispatch_guard.sh`** rejects a missing or wrong `subagent_type`, off-flock impersonation, and wrong-tier engineer or critic dispatch from a teammate.
- **`dedup_write_guard.sh`** and **`dups_write_guard.sh`** block a new public symbol that reuses an existing name, or a new type that matches an existing one by field shape under a different name.
- **`coordinate_drive_guard.sh`** blocks a premature root halt while teammates are idle or lead mail is unread.
- **`close_finalize_check.sh`** validates close preconditions before the stop event fires.

Run the smoke suite any time with `bash hooks/tests/run.sh`.

### Doctrines

Framework-intrinsic behavioral rules live in `skills/shepherd/doctrines/`. Each is paired with a mechanism (a hook, a guard, or a halt code) in the invariant-enforcement matrix, so a doctrine is a rule with teeth, not prose. Current doctrines include `subtract-dont-add`, `wrapper-must-earn`, `dispatch-tier-separation`, `coordinate-active-drive`, `loop-templates`, `toolkit`, `self-improvement`, `adaptation-loop`, `brief-cache-discipline`, and more.

---

## Configure

Create `.claude/shepherd.toml` at the repo root. Shepherd warns at every invocation until one exists. Resolution is per-key, highest precedence first:

```text
.claude/shepherd.local.toml    project-pinned, gitignored: operator overrides (wins)
.claude/shepherd.toml          project-pinned, checked into the repo
$XDG_CONFIG_HOME/shepherd.toml  user-global default
```

Each key resolves independently: a value in `shepherd.local.toml` overrides the same key in `shepherd.toml`, which overrides the user-global default.

A minimal config:

```toml
[project]
name     = "my-project"
language = "rust"          # rust | python | typescript | go | mixed

[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
sprints_per_patch     = 10
main_branch           = "main"

[gates]
check  = "cargo check --workspace"
lint   = "cargo clippy --workspace -- -D warnings"
format = "cargo fmt --all"

[skills]
mandatory = ["code-style"]
by_domain = { rust = ["rust"], wasm = ["webassembly"] }
```

See [`docs/configuration.md`](docs/configuration.md) for the full schema, including `[gates.extra]`, `[spawn]`, `[release]`, `[focus]` (rehydration plus the heartbeat cadence), and the skill matrix. A working multi-crate example lives at [`examples/rust-service/shepherd.toml`](examples/rust-service/shepherd.toml).

---

## Compose with your own skills

Shepherd orchestrates; your skills provide the per-keystroke voice. It is designed to wrap them, not replace them.

- **`code-style`** is injected into every coder brief by default. Shepherd handles the pipeline; your style skill handles idioms, naming, and comment discipline.
- **Domain skills** (`rust`, `webassembly`, `supabase`, and so on) wire into the required-skills matrix through `[skills.by_domain]` and attach automatically when a coder's file scope matches.
- **`superpowers:brainstorming`** and **`superpowers:writing-plans`** are loaded by `@engineer` from inside its own dispatch. Plan quality leans on them.

See [`docs/integration.md`](docs/integration.md) for the full integration model, including MCP bindings and custom doctrine authorship.

---

## Troubleshooting and FAQ

**Shepherd warns that `shepherd.toml` is missing.** Create `.claude/shepherd.toml` (see [Configure](#configure)). Without it, shepherd uses generic Rust defaults and warns on every invocation.

**`shctx: command not found`.** The `shctx` CLI ships inside the plugin at `skills/context/scripts/`. The plugin exposes it on the path when installed; if you symlinked manually, make sure the scripts directory is reachable, or invoke the commands through `/shepherd:ctx`.

**Do I have to use Agent Teams?** No. `/shepherd:start` runs a complete sprint solo in the main chat with no teams. Reach for `/shepherd:spawn` only when you want parallel lanes.

**Which model should I use?** Opus for `/shepherd:plant` (seed quality) and the engineer (plan quality). Sonnet for the conductor and the rest of the flock. Shepherd sets these defaults for you; you only switch the model in main chat between plant and start.

**My long sprint still drifts.** Confirm the focus loop is on (`[focus].loop_default = "on"`, the default) and lower the heartbeat cadence (`[focus].heartbeat_actions`, default 20). For multi-hour sessions, add a wall-clock heartbeat with `[focus].heartbeat_interval = "45m"`. See the [drift playbook](#my-long-sprint-keeps-drifting-off-task-after-a-few-hours).

**A teammate crashed and left a worktree behind.** Run `/shepherd:cleanup`. It prunes the crashed entry and its worktree; it never touches live lanes.

**Is anything sent to a third-party API?** No. When shepherd needs an LLM call it routes through your local Claude Code, never a hosted endpoint.

---

## File map

| Path | Purpose |
| :--- | :--- |
| `.claude-plugin/plugin.json` | Plugin manifest. |
| `.claude-plugin/marketplace.json` | Self-hosted marketplace entry. |
| `agents/{engineer,critic,coder,auditor,worker,discovery}.md` | The closed flock; full system prompt per role. |
| `agents/{shepherd,conductor,planter}.md` | The three meta-orchestrators. |
| `commands/{plant,start,spawn,focus,loop,toolkit,ctx,cleanup}.md` | Slash-command entry points. |
| `skills/shepherd/SKILL.md` | Conductor quick reference, loaded by every `/shepherd:*` invocation. |
| `skills/shepherd/doctrines/*.md` | Framework-intrinsic behavioral rules. |
| `skills/shepherd/references/` | Branching model, seed and brief templates, loop and workflow templates, grading rubric. |
| `skills/context/` | The `shctx` runtime: SQL migrations, views, and the bash implementation. |
| `services/{llm,eval}/` | Self-contained services: the local-Claude-Code LLM call and the rubric-driven eval harness, each with its own contract, tests, and evals. |
| `hooks/hooks.json` + `hooks/scripts/` | Lifecycle hooks and their implementations. |
| `hooks/tests/` | Smoke harness: `bash hooks/tests/run.sh`. |
| `docs/{configuration,integration,customization}.md` | Operator-facing documentation. |
| `examples/{minimal,rust-service}/` | Starter config and a worked multi-crate example. |

---

## Versioning

Shepherd follows semver:

- **Major**: changes to the closed-flock contract (adding or removing a role).
- **Minor**: new commands, doctrines, or config keys (backward-compatible).
- **Patch**: dispatch logic, doctrine, and brief-template fixes.

Current version: **6.2.3**. See [`CHANGELOG.md`](CHANGELOG.md) for the per-version history.

---

## Contributing

Issues and pull requests are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). All main-bound changes flow through a pull request; the hook suite (`bash hooks/tests/run.sh`) must stay green.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).
