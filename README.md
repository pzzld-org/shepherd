# 🐑 shepherd

[![GitHub License](https://img.shields.io/github/license/FL03/shepherd?style=for-the-badge&logo=github)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/FL03/shepherd?style=for-the-badge&logo=github)](https://github.com/FL03/shepherd/releases)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-d97757?style=for-the-badge)](https://github.com/FL03/shepherd)

> **Turn one Claude Code session into a disciplined release engineer.** Shepherd drives a closed six-agent flock through repeatable, audited sprint pipelines, with mechanical guardrails that refuse drift before it happens.

Shepherd is a [Claude Code](https://claude.com/claude-code) plugin for **long-running engineering work**: multi-hour sprints, full patch arcs, parallel feature lanes — a structured pipeline with fixed roles, gated phases, read-only audits, a per-project memory, and hooks that block the failure modes long sessions are prone to.

A behavioral layer, not a heavy framework — no build step, no server. Everything ships as markdown, shell scripts, and a SQLite registry, wiring together Claude Code's native primitives (subagents, Agent Teams, `/loop`, hooks).

```text
┌────────────────────────────────────────────────────────────────────────┐
│  /shepherd:plant    Author drift-resistant sprint seeds (Opus)         │
│  /shepherd:spawn    The execution path — root + teammate-conductor(s)  │
│                     --scope <sprint|patch|minor|version>               │
│                     --parallel <N> | --auto | --staged                 │
│  /shepherd:focus    Keep the session on-task (focus loop + heartbeat)  │
│  /shepherd:loop     Bounded loop-until-done (per-role templates)       │
│  /shepherd:toolkit  Tool registry, so a session never forgets a tool   │
│  /shepherd:ctx      Inspect / refresh the per-project SQLite context   │
│  /shepherd:cleanup  Prune stale teammates, worktrees, locks            │
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
| **Tunnel vision** | Ignores the issue ledger underneath. | Phase 0 mesh enumerates every open issue/PR, surfaces out-of-milestone CRITICAL/HIGH as drift risks. |
| **Duplication** | Types/helpers get re-invented. | `[DO-NOT-DUPLICATE]` grep gate in every brief; a write-time hook blocks a reused name/field shape. |
| **Scope drift** | Sprints grow features never seeded. | Every brief is anchored to the seed; the auditor's `completeness` concern fails a drifted lane. |
| **Audit theater** | The reviewer wrote the code. | A read-only auditor swarm (3-5 agents, split by concern) reviews in parallel from a separate tier. |
| **Unreviewed handoff** | Coder's "self-gate green" claim stands in for review. | The conductor holds a PASS from a wave-review auditor first; REDO forces a named, capped redo. |
| **Wrapper bloat** | Hollow structs added for structure's sake. | A wrapper gate at close plus subtract-don't-add: net-negative lines, deps, abstractions. |
| **Release malpractice** | Squash-merging unsigned, untested commits. | The conductor drives the squash-to-main pipeline with ordered gates, signed commits. |
| **Off-task after hours** | A multi-hour sprint drifts from the objective. | A **focus loop** surviving compaction, plus a **focus heartbeat** re-anchoring on a cadence. |
| **Passive stalls** | The root spawns helpers, then waits. | A coordinate-active-drive contract + Stop hook blocking a premature halt while work is outstanding. |

---

## How it works in 60 seconds

Three ideas, and you have the model.

**1. A closed flock of six agents**, each with one job and a fixed dispatch contract.

| Agent | Job |
| :--- | :--- |
| `@engineer` | Audits ground truth, authors the sprint plan. |
| `@critic` | Adversarially reviews the plan before any code. |
| `@coder` | The only role writing production code, in parallel waves. |
| `@auditor` | Read-only reviewer; a swarm at sprint close. |
| `@worker` | Bounded catch-all: monitoring, ops, cleanup. |
| `@discovery` | Read-only orientation and research. |

Closed on purpose — a seventh role is a major-version decision.

**2. A three-section pipeline.** Every sprint runs the same shape:

```text
INTRODUCTION   ground-truth mesh  ->  @engineer plan  ->  @critic gate
     │
BODY           coder waves with between-wave gates (format / check / lint)
     │           auditor swarm overlaps the last wave
     │
CLOSE          merge -> tag -> squash-to-main -> carry-forward -> close report
```

**3. Three meta tiers that drive it.** You rarely think about the tiers directly; you run a command and the right tier is adopted for you.

| Tier | Profile | Adopted under | Role |
| :--- | :--- | :--- | :--- |
| Root | `agents/shepherd.md` | `/shepherd:spawn` | Dispatches engineer/critic, materializes teammate output, coordinates the close swarm. |
| Conductor | `agents/conductor.md` | a teammate under `/shepherd:spawn` | Executes a sprint or a single lane. |
| Planter | `agents/planter.md` | `/shepherd:plant` | Authors seeds, stewards git custody. |

Everything else — SQLite memory, toolkit, loop templates, hooks — keeps those three ideas honest.

---

## Install

### From the marketplace (recommended)

```text
/plugin marketplace add FL03/shepherd
/plugin install shepherd@fl03
```

Update later with `/plugin update shepherd@fl03`.

### Personal symlink or per-project pin

```bash
git clone https://github.com/FL03/shepherd.git ~/src/FL03/shepherd
ln -s ~/src/FL03/shepherd ~/.claude/plugins/shepherd      # personal
ln -s /path/to/FL03/shepherd .claude-plugin/shepherd      # per-project (mkdir -p .claude-plugin first)
```

No build system. Runtime deps: `git`, `bash`, `sqlite3`, `jq`. `gh` powers the Phase 0 mesh's
issue/PR ledger; without it, that step is skipped, not failed. Works across CLI, web, IDE.

---

## Quickstart

From zero to your first audited sprint in about five minutes.

```bash
# 1. Configure shepherd for this repo.
cp /path/to/shepherd/examples/minimal/shepherd.toml .claude/shepherd.toml

# 2. Initialize the per-project context registry.
/shepherd:ctx    # or: shctx init && shctx refresh --scope=all && shctx status
```

Then, in Claude Code: `/shepherd:plant` (Opus, author the first seed), then `/shepherd:spawn`
(Sonnet, run the sprint). `/shepherd:spawn` is the sole execution path — main chat becomes the
root shepherd and spawns a teammate-conductor (one lane by default) end-to-end. Add `--auto` or
`--parallel <N>` once a sprint or two has gone clean; see the [playbooks](#usage-playbooks).

---

## Commands

| Command | What it does |
| :--- | :--- |
| `/shepherd:plant [scope]` | Author drift-resistant sprint seeds. Opus recommended. |
| `/shepherd:spawn [slug] [--scope ...] [--parallel N \| --auto \| --staged]` | The execution path — root spawns a teammate-conductor per lane. |
| `/shepherd:focus [...] [--heartbeat]` | Start/refresh the focus loop, or fire a re-anchor heartbeat. |
| `/shepherd:loop [task] [--max N] [--agent ...] [--interval ...]` | Bounded loop-until-done. |
| `/shepherd:toolkit [list\|add\|rm\|pin\|md]` | The tool registry. |
| `/shepherd:ctx` | Inspect/refresh the SQLite context registry. |
| `/shepherd:cleanup` | Prune stale teammates, worktrees, locks. |

Plant feeds spawn: seed first, then execute.

---

## Usage playbooks

| Need | Command | Notes |
| :--- | :--- | :--- |
| One careful sprint, review it yourself | `/shepherd:spawn` | No flags: a single lane end to end. Good for a new repo or a delicate change. |
| Autopilot a whole patch | `/shepherd:spawn --auto` | Alias for `--scope patch` — sequential sprints, fresh context each so quality doesn't decay. |
| Independent work in parallel | `/shepherd:spawn --parallel 3` | Disjoint sprints across worktrees, each its own teammate-conductor. Use when work is file-disjoint. |
| Plan ahead before executing | `/shepherd:plant arc \| dev.5 \| dev.5..dev.7` | Opus for seed quality; Sonnet/Haiku produce a degraded-seed advisory. |
| Long sprint drifting off-task | `/shepherd:focus --heartbeat` | The heartbeat adds a cadence inside a long stretch with no wake — set `[focus].heartbeat_interval = "45m"` for wall-clock. |
| What shepherd knows about this repo | `/shepherd:ctx` | Inspects the SQLite registry: symbols, GitHub state, artifacts, memories, event log. |
| Poll/monitor until a condition holds | `/shepherd:loop "watch CI..." --agent worker --max 12 --interval 5m` | Hard cap + measurable termination predicate. |
| Clean up after a parallel run | `/shepherd:cleanup` | Operator-confirmed; never removes a live lane. |

---

## Under the hood

**Models.** `[models]` in `shepherd.toml`, resolved by `shctx models resolve`, is the one table
mapping each role to its model — set once instead of hand-pinning per spawn. Coders are always
scoped to a disjoint file set so parallel waves cannot collide. `workflow_model_guard.sh` extends
the same discipline to hand-authored Dynamic Workflow scripts: an `agent()` call with neither
`model:` nor `agentType:` silently inherits the main-loop model instead, so it's blocked by default.

**Self-contained engineer.** Can run as its own named teammate, running a read-only sub-flock
in-session (discovery + intro-audit + its own dispatched critic) and returning a hash-tied
*critic-proof*; root then accepts the plan via a thin mechanical gate (`shctx plan verify`) instead
of re-reviewing it.

**SQLite context registry.** `/shepherd:ctx` manages `.shepherd/shepherd.db`: code symbols, GitHub
state, artifacts, memories, flock profiles, lock history, event log — backs the dedup fast-path
and carry-forward ledger.

```bash
shctx init && shctx refresh --scope=all && shctx status
```

**Workdir hygiene, self-eval, toolkit.** `shctx prune`/`--confirm` reclaims accreted state (dry-run
default, moves — never deletes — to `/tmp`); `shctx eval run/report` scores a latent output via
your local Claude Code, never a hosted API; `shctx toolkit add/list` merges project + global tools.

**Per-language style files.** `.shepherd/styles/<lang>.md` (rust, python, typescript, go, shell,
sql), tracked in git, injected into every matching coder brief.

**Mechanical enforcement hooks.** `dispatch_guard.sh` rejects a bad `subagent_type`;
`dedup_write_guard.sh`/`dups_write_guard.sh` block a symbol reusing an existing name or shape;
`coordinate_drive_guard.sh` blocks a premature root halt while teammates are idle;
`workflow_model_guard.sh` blocks a Dynamic Workflow whose `agent()` calls omit both `model:` and
`agentType:` — the shape that silently inherits the main-loop model instead of resolving from
`[models]`. Smoke suite: `bash hooks/tests/run.sh`.

**Six modular skills.** `skills/shepherd` (dispatch law, pipeline, flock briefs), `skills/adaptation`
(lesson memory), `skills/motivation` (focus, FOCUS-HEARTBEAT, drive, sentinel), `skills/harness`
(Agent Teams, Workflow tool, `/loop`, `/goal`), `skills/context` (the `shctx` runtime),
`skills/thinking`. Each rule pairs with a mechanism — a hook, a guard, or a halt code.

---

## Configure

Create `.claude/shepherd.toml` at the repo root. Shepherd warns at every invocation until one exists.

```toml
[project]
name     = "my-project"
language = "rust"

[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
sprints_per_patch     = 10

[gates]
check  = "cargo check --workspace"
lint   = "cargo clippy --workspace -- -D warnings"
format = "cargo fmt --all"

[models]                 # optional — these ARE the defaults
engineer  = "opus[1m]"
conductor = "sonnet"
```

See [`docs/configuration.md`](docs/configuration.md) for the full schema. A working multi-crate example lives at [`examples/rust-service/shepherd.toml`](examples/rust-service/shepherd.toml).

---

## Compose with your own skills

Shepherd orchestrates; your skills provide the per-keystroke voice.

- **`code-style`** is injected into every coder brief by default.
- **Domain skills** (`rust`, `webassembly`, `supabase`, …) wire in via `[skills.by_domain]`, attaching when a coder's file scope matches.
- **`superpowers:brainstorming`/`writing-plans`** are loaded by `@engineer`.

See [`docs/integration.md`](docs/integration.md) for the full model.

---

## Troubleshooting and FAQ

| Question | Answer |
| :--- | :--- |
| `shepherd.toml` is missing | Create `.claude/shepherd.toml` (see [Configure](#configure)). |
| `shctx: command not found` | Ships at `skills/context/scripts/`; invoke via `/shepherd:ctx` if symlinked manually. |
| Do I have to use Agent Teams? | Yes — `/shepherd:spawn` always runs through a teammate-conductor, even for one lane; there's no separate solo mode. |
| Which model should I use? | Opus for `/shepherd:plant` and the engineer; Sonnet for the rest — shepherd sets these defaults. |
| My long sprint still drifts | Lower `[focus].heartbeat_actions` (default 20) or set `[focus].heartbeat_interval = "45m"`. |
| A teammate crashed, left a worktree | Run `/shepherd:cleanup`. |
| Anything sent to a third-party API? | No — every LLM call routes through your local Claude Code. |

---

## File map

| Path | Purpose |
| :--- | :--- |
| `.claude-plugin/plugin.json` | Plugin manifest. |
| `agents/{engineer,critic,coder,auditor,worker,discovery}.md` | The closed flock. |
| `agents/{shepherd,conductor,planter}.md` | The three meta-orchestrators. |
| `commands/{plant,spawn,focus,loop,toolkit,ctx,cleanup}.md` | Slash-command entry points. |
| `skills/shepherd/` | Dispatch law, sprint contract, pipeline, flock briefs, principles. |
| `skills/{adaptation,motivation,harness,thinking}/` | Lesson memory, drive/focus, platform mechanics, thinking discipline. |
| `skills/context/` | The `shctx` runtime: migrations, views, bash implementation. |
| `services/{llm,eval}/` | Self-contained: the local-Claude-Code LLM call and the eval harness. |
| `hooks/hooks.json` + `hooks/scripts/` | Lifecycle hooks; `bash hooks/tests/run.sh`. |
| `docs/{configuration,integration,customization}.md` | Operator-facing documentation. |
| `examples/{minimal,rust-service}/` | Starter config and a worked multi-crate example. |

---

## Versioning

Semver: **major** = closed-flock contract change; **minor** = new commands/config keys; **patch** = dispatch/brief-template fixes. Current version: **6.3.2**. See [`CHANGELOG.md`](CHANGELOG.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). All main-bound changes flow through a PR; the hook suite (`bash hooks/tests/run.sh`) must stay green.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
