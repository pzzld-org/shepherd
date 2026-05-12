# shepherd

Sprint-by-sprint version-cycle conductor. A production-grade orchestration framework that turns a single Claude Code session into a disciplined release engineer driving a closed five-agent flock through repeatable sprint pipelines.

```bash
┌──────────────────────────────────────────────────────────────────┐
│  /shepherd:plant     Opus-pinned seed authorship (upstream)      │
│  /shepherd:start     One sprint end-to-end, then PAUSE           │
│  /shepherd:autorun   Sequential autopilot (no inter-sprint pause)│
│  /shepherd:parallel  Multi-sprint worktree fan-out               │
└──────────────────────────────────────────────────────────────────┘
```

## v5.0.0 — Context Registry

`/shepherd:ctx` introduces a per-project SQLite registry at `.artifacts/root.db`. It indexes:

- code symbols (replaces hand-maintained `canonical-types.md`)
- GitHub issues, PRs, releases, milestones (cached with TTL)
- artifact files (markdown reports indexed by hash + kind)
- project memories (replaces external `remember` plugin)
- profiles (modifiers/extensions to flock behavior)
- lock history (autorun + parallel coordination)
- event log

Quick start in any consumer project:

```bash
shctx init                   # scaffold .artifacts/, create root.db
shctx refresh --scope=all    # populate caches
shctx status                 # verify
```

See [`skills/context/SKILL.md`](skills/context/SKILL.md) for the full CLI.

### Per-language style files

Project-local code-style overrides live at `.artifacts/styles/<lang>.md` (rust, python, typescript, go, shell, sql). They are tracked in git and complement — never replace — the user-level `code-style` skill. The conductor mechanically injects the matching style file as a `[CODE-STYLE]` block into every coder brief whose `[FILE-SCOPE]` touches that language; the auditor's `completeness` check fails any code-touching lane that omits it.

```bash
shctx style init --all       # scaffold all six language files from bundled defaults
shctx style init rust        # scaffold a single language
shctx style list             # show which languages have a project-local file
shctx style show rust        # print the current rust style
shctx style edit rust        # open in $EDITOR
```

Bundled defaults ship at [`skills/context/styles/<lang>.md`](skills/context/styles/); `shctx style init` copies them into the consumer project's `.artifacts/styles/`.

## What it is

Shepherd is the framework. The conductor (main chat, Sonnet) writes seeds, dispatches a closed flock of five agents, runs gates, audits, and ties off — then pauses or loops or fans out depending on the command invoked.

| Lane | Model | Mode | Job |
| ---- | ----- | ---- | --- |
| `@engineer` | Opus | Single, once per sprint | Phase 0 mesh + sprint plan authorship |
| `@critic` | Sonnet | Single, sequential gate | Adversarial review of plans, money-paths, merges |
| `@coder` | Sonnet | Parallel waves | Implementation; one per disjoint file scope |
| `@auditor` | Sonnet | Swarm of 3–5 | Read-only review at sprint close, split by concern |
| `@worker` | Sonnet | Single or parallel | Bounded execution: monitoring, research, ops |

The flock is **closed**. Plus an upstream **planter** mode (Opus, conductor variant — not a sixth lane) that authors drift-resistant seeds.

## What it solves

Naive `claude` sessions on long-running engineering work suffer:

- **Tunnel vision** — the conductor sees the current sprint deliverable and ignores the 200-issue ledger underneath.
- **Duplication** — types, traits, helpers re-invented because nobody grepped first.
- **Silent scope drift** — sprints add features that weren't seeded.
- **Audit theater** — code "passes review" because the reviewer was the same context that wrote it.
- **Release pipeline malpractice** — squash-merging unsigned, untested, un-tagged commits.

Shepherd's answer:

- **Phase 0 mesh** — every sprint opens with a ground-truth audit (open issues, recent PRs, Sentry/Fly/Supabase state, prior carry-forwards). Engineer can't skip it; auditors verify it.
- **Issue-ledger awareness** — every sprint's Phase 0 enumerates the FULL open-issue ledger (not just the current milestone) and surfaces non-current-milestone CRITICAL/HIGH items as drift risks.
- **Anti-duplication grep gate** — every coder brief carries `[DO-NOT-DUPLICATE]` greps the coder runs BEFORE writing new code. `must-be-zero` violations halt the lane.
- **Wrapper-grep gate** — every sprint close greps for hollow wrapper structs introduced in lane scope (per `feedback_wrapper_must_earn_its_existence.md`).
- **SUBTRACT-DON'T-ADD doctrine** — every sprint MUST end net-negative on (deps, abstractions, LOC). Auditor fails the close on violation.
- **Adversarial critic** — every plan above XS scope, every money-path change, every merge to main is gated by `@critic` first.
- **Read-only auditor swarm** — 3–5 auditors split by concern, dispatched in parallel with Wave 2 coders (Pattern B overlap).
- **Carry-forward refresh** — `completeness` auditor diffs the GH ledger against the sprint's seed, files chronic items at ≥ 2 patch crossings.

## Install

### From the Claude Code marketplace (recommended)

```text
/plugin marketplace add fl03/shepherd
/plugin install shepherd@fl03
```

This registers the self-hosted marketplace manifest at the repo root, then pulls in shepherd as a managed plugin. Subsequent updates flow through `/plugin update shepherd@fl03`.

### Personal install via symlink (current user only)

```bash
# Clone once, then symlink the repo root into your user plugin directory.
git clone https://github.com/FL03/shepherd.git ~/src/FL03/shepherd
ln -s ~/src/FL03/shepherd ~/.claude/plugins/shepherd
```

The repo root IS the plugin — `.claude-plugin/plugin.json` lives there.

### Per-project pin (checked into the consumer repo)

```bash
# From the consumer project root
mkdir -p .claude-plugin
ln -s /path/to/FL03/shepherd .claude-plugin/shepherd
```

## Configure

Shepherd is project-agnostic. Create `.claude/shepherd.toml` at the project root to bind it to your repo's branch convention, gate commands, and artifact paths. See [`docs/configuration.md`](docs/configuration.md) for the full schema.

Minimal example (drop into `.claude/shepherd.toml`):

```toml
[project]
name        = "axiom"
language    = "rust"

[branching]
# Branch pattern. {X}/{Y}/{Z}/{N} are placeholders the framework reads.
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
sprints_per_patch     = 10
main_branch           = "main"

[gates]
# Commands that run between coder waves and at sprint close.
# Empty = framework skips the gate.
check  = "cargo check --workspace --features full"
lint   = "cargo clippy --workspace --features full -- -D warnings"
format = "cargo fmt --all"

[paths]
plans   = ".artifacts/plans"
reports = ".artifacts/reports"
docs    = ".artifacts/docs"
ctx     = ".artifacts/ctx"

[skills]
# Per-language skills that EVERY coder brief MUST include in [SKILLS].
# code-style is mandatory; the rest are domain-driven.
mandatory  = ["code-style"]
by_domain  = { rust = ["rust"], wasm = ["webassembly"], finance = ["finance"], supabase = ["supabase:supabase"] }

[release]
# Whether the conductor should drive the squash-to-main release pipeline at dev.9.
# Most projects pin this to false and rely on a GH workflow triggered on tag.
conductor_drives_release = false
```

A working example for the Axiom project lives at [`examples/axiom/shepherd.toml`](examples/axiom/shepherd.toml).

## Usage

```bash
# Author seeds for upcoming sprints (Opus session required)
/shepherd:plant
/shepherd:plant dev.5
/shepherd:plant arc

# Run a single sprint, then pause for sign-off
/shepherd:start

# Run sprints back-to-back, no pause between
/shepherd:autorun

# Run multiple disjoint sprints in parallel worktrees
/shepherd:parallel
```

For first-time use:

1. Author your project's `shepherd.toml` (see above).
2. (Optional) author a patch-arc seed by hand at `.artifacts/plans/v{X}.{Y}.{Z}.seed.md` describing the patch's theme.
3. Run `/shepherd:plant` in an Opus session to author the dev.0 seed.
4. Switch back to Sonnet and run `/shepherd:start`.

## File map

| Path | What it is |
| ---- | ---------- |
| `.claude-plugin/plugin.json` | Plugin manifest |
| `commands/{plant,start,autorun,parallel}.md` | The four slash commands |
| `agents/{engineer,critic,coder,auditor,worker}.md` | Closed flock — agent system prompts |
| `skills/shepherd/SKILL.md` | Conductor quick reference (loaded by every command) |
| `skills/shepherd/{flock,planter,autorun,parallel}.md` | Mode-specific operational detail |
| `skills/shepherd/references/branching-model.md` | Authoritative branch lifecycle + rollover algorithm |
| `skills/shepherd/references/seed-template.md` | Canonical seed shape (what the engineer parses) |
| `skills/shepherd/references/agent-briefs.md` | Copy-paste brief templates + grade cutoffs |
| `skills/shepherd/doctrines/*.md` | Framework-intrinsic doctrines (subtract-don't-add, wrapper-must-earn, etc.) |
| `examples/axiom/` | Concrete Axiom-project bindings (config, CLAUDE.md snippet, custom doctrines) |
| `docs/{configuration,integration,customization}.md` | Operator-facing documentation |

## Integration with local skills

Shepherd is designed to integrate with — not replace — locally developed skills:

- **`code-style`** — every coder brief includes this in `[SKILLS]` by default. Code-style holds your personal language-by-language preferences (Rust idioms, comment discipline, naming conventions). Shepherd's framework provides the orchestration; `code-style` provides the per-keystroke voice.
- **`rust` / `webassembly` / `finance` / `supabase` / domain skills** — wired into the Required-Skills Matrix in `flock.md` §II.@coder. Shepherd reads `[skills.by_domain]` from `shepherd.toml` to know which domain skills to attach when the coder's file scope touches that domain.
- **`superpowers:brainstorming` + `superpowers:writing-plans`** — the engineer loads these from inside its own dispatch (not the conductor calling them). The plan-quality contract depends on these.

See [`docs/integration.md`](docs/integration.md) for the detailed integration model.

## Versioning + compatibility

Shepherd follows semver:

- **MAJOR** bumps when the closed-flock contract changes (e.g., adding a sixth lane, removing the planter, flipping critic to parallel).
- **MINOR** bumps add new commands, new doctrines, new config keys (backward-compatible).
- **PATCH** bumps fix bugs in dispatch logic, doctrines, brief templates.

Current version: **5.0.6**

See [`CHANGELOG.md`](CHANGELOG.md) for the per-version history.

## License

Apache-2.0. See `LICENSE` at the repo root.
