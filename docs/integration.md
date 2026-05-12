# Integration with local skills

Shepherd is designed to **compose with**, not replace, your locally developed skills. The framework owns orchestration; per-language and per-domain skills own implementation detail.

## The composition model

```
                        ┌─────────────────────────────────────┐
                        │  shepherd (this plugin)              │
                        │  • flock dispatch                    │
                        │  • Phase 0 mesh                      │
                        │  • doctrines (subtract / wrapper / …) │
                        │  • brief contract                    │
                        └────────────────┬────────────────────┘
                                         │
                       reads shepherd.toml [skills.*]
                                         │
                ┌────────────────────────┴────────────────────────┐
                ▼                        ▼                         ▼
       ┌──────────────────┐  ┌──────────────────┐    ┌──────────────────┐
       │  Language skills │  │  Domain skills   │    │  Personal skill  │
       │  rust            │  │  finance         │    │  code-style      │
       │  python          │  │  polymarket      │    │  (per-language   │
       │  typescript      │  │  supabase        │    │   ledger of YOUR │
       │  go              │  │  claude-api      │    │   preferences)   │
       │  webassembly     │  │  workflow        │    │                  │
       └──────────────────┘  └──────────────────┘    └──────────────────┘
```

The conductor builds each coder brief by:

1. Looking at the lane's `[FILE-SCOPE]`.
2. Walking `[skills.detection]` from `shepherd.toml` to determine which **language domain** + **subject domain** the lane touches.
3. Adding the corresponding `[skills.by_domain]` entries to `[SKILLS]` in the brief.
4. Always including `[skills.mandatory]` (default: `code-style`).

The coder, on dispatch, invokes each `[SKILLS]` entry via the Skill tool. Per-language idioms come from the language skill; personal preferences come from `code-style`.

## What lives where

| Concern | Lives in |
|---|---|
| When to dispatch auditors vs coders | shepherd doctrines (`pattern-b-overlap.md`) |
| Whether to dispatch in parallel | shepherd doctrines + Brief-Validity Checklist |
| Whether `pub struct Foo {params}` is hollow | shepherd doctrine (principle) + `rust` skill (Rust grep) |
| What `cargo check` returns and how to parse it | `rust` skill |
| Which `clippy::*` lints to allow | `rust` skill |
| Whether to use snake_case or camelCase | `code-style:rust.md` (your personal preference) |
| What `tokio::select!` is and when to use it | `rust` skill |
| What `Coinbase WS` schema looks like | (not a skill — project knowledge in CLAUDE.md or domain doc) |
| Whether to use `requests` or `httpx` in Python | `code-style:python.md` |
| ESLint config for new TS files | `code-style:typescript.md` |
| Polymarket CLOB endpoint shapes | `polymarket` skill |

## Hooking your skills into shepherd

In `.claude/shepherd.toml`:

```toml
[skills]
mandatory = ["code-style"]

[skills.by_domain]
# Language skills — shepherd auto-attaches when [FILE-SCOPE] matches detection
rust       = ["rust"]
wasm       = ["webassembly"]
python     = ["python"]
typescript = ["typescript"]

# Domain skills — shepherd attaches when [FILE-SCOPE] matches detection
finance    = ["finance"]
supabase   = ["supabase:supabase"]
polymarket = ["polymarket"]
claude_api = ["claude-api"]

[skills.detection]
# File-scope patterns → domain
rust       = ["**/*.rs"]
wasm       = ["cmp/**", "**/*.wit"]
python     = ["**/*.py"]
typescript = ["**/*.ts", "**/*.tsx"]
finance    = ["**/circuits/**", "**/strategies/**"]
supabase   = ["**/supabase/**", "**/migrations/**.sql"]
polymarket = ["**/polymarket/**", "**/clob/**", "**/pm/**"]
claude_api = ["**/anthropic/**", "**/claude/**"]
```

## Engineer-time skill assembly

The engineer's plan output, for each coder lane, includes a `[SKILLS]` line the conductor copies into the dispatch brief verbatim. Example for a lane scoped to `crates/circuits/src/drift.rs`:

```markdown
[SKILLS]
- code-style       (mandatory per shepherd.toml [skills.mandatory])
- rust             (file scope matches **/*.rs)
- finance          (file scope matches **/circuits/**)
```

If the engineer omits a mandatory skill, the Brief-Validity Checklist rejects the brief.

## Conductor-only skills

Some skills should load on the conductor (main chat) but not on every flock dispatch:

```toml
[hooks]
# Loaded by conductor on every /shepherd:* invocation
on_conductor_only = ["workflow"]

# Loaded by engineer on plan-time dispatch (in addition to its own [SKILLS])
on_engineer_only = ["workflow"]

# Loaded by planter only
on_planter_only = []
```

`workflow` is a good example — the conductor needs it for branch-cut + PR-open + release pipeline, but the coder doesn't.

## Customizing for non-Rust projects

Example `shepherd.toml` for a Python project:

```toml
[project]
name     = "myproject"
language = "python"

[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"

[gates]
check  = "uv run mypy ."
lint   = "uv run ruff check ."
format = "uv run ruff format --check ."

[skills]
mandatory = ["code-style"]

[skills.by_domain]
python = ["python"]

[skills.detection]
python = ["**/*.py"]
```

Example for a TypeScript project:

```toml
[project]
name     = "myproject"
language = "typescript"

[branching]
patch_branch_pattern  = "release/{X}.{Y}.{Z}"
sprint_branch_pattern = "release/{X}.{Y}.{Z}/sprint-{N}"
sprints_per_patch     = 5
main_branch           = "main"

[gates]
check  = "pnpm tsc --noEmit"
lint   = "pnpm eslint ."
format = "pnpm prettier --check ."

[skills]
mandatory = ["code-style"]

[skills.by_domain]
typescript = ["typescript"]

[skills.detection]
typescript = ["**/*.ts", "**/*.tsx"]
```

The framework's branch lifecycle, doctrine enforcement, audit swarm, and SUBTRACT-DON'T-ADD constraint apply identically.

## Adding a new language

If your project's primary language doesn't have a published per-language skill yet:

1. Author one with [`skill-creator`](https://github.com/anthropic-experimental/skill-creator).
2. The skill should cover: language idioms, build commands, common patterns, the language's wrapper-must-earn detection grep, the language's subtract-detection patterns.
3. Publish it (personal `~/.claude/skills/` or marketplace).
4. Add `<language> = ["<skill-slug>"]` to your `shepherd.toml [skills.by_domain]`.

Shepherd composes; it doesn't gatekeep. New languages are a config + skill addition, not a fork.

## Per-project doctrines (not framework)

Sometimes a project carries a doctrine that's NOT a framework rule but needs to load into every dispatch. Examples:

- "Geo-block law — node region pinned forever" (Axiom)
- "Database writes go through the WriteOnlyClient wrapper" (some other project)
- "All API endpoints require X-Request-Id header" (some other project)

These live in `[memory].project_doctrines` (default `.claude/doctrines/`):

```toml
[memory]
project_memory    = "~/.claude/projects/-Users-jo3-src-fl03-axiom/memory"
project_doctrines = ".claude/doctrines"

[hooks]
on_every_dispatch = ["code-style"]
```

The conductor loads `project_doctrines/*.md` at session-open and injects them into every flock dispatch's preamble. The framework doctrines (in `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/`) are language-agnostic and immutable per shepherd version; project doctrines drift with your project.

## When the integration breaks

Symptoms:

- Coder dispatches without `code-style` → `[skills.mandatory]` not enforced; check the engineer's plan output.
- Coder applies cargo conventions to a Python file → `[skills.detection]` is wrong; `python` skill not attached for `**/*.py`.
- Coder uses outdated build command → `[gates].check` in `shepherd.toml` doesn't match the project's actual build system.

Each of these is a config issue, not a framework issue. Audit `shepherd.toml` first.

## See also

- [`docs/configuration.md`](configuration.md) — the full schema
- [`docs/customization.md`](customization.md) — bring-your-own branch model, custom doctrines
- [`skills/shepherd/doctrines/README.md`](../skills/shepherd/doctrines/README.md) — language-agnostic stance + integration model
