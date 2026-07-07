# Integration with local skills

Shepherd composes with your locally developed skills rather than replacing them. Shepherd owns
orchestration; per-language and per-domain skills own implementation detail.

## The composition model

```
                        ┌─────────────────────────────────────┐
                        │  shepherd (this plugin)              │
                        │  • flock dispatch                    │
                        │  • Phase 0 mesh                      │
                        │  • principles (subtract / wrapper / …) │
                        │  • brief contract                    │
                        └────────────────┬────────────────────┘
                                         │
                       reads shepherd.toml [skills.*]
                                         │
                ┌────────────────────────┴────────────────────────┐
                ▼                        ▼                         ▼
       ┌──────────────────┐  ┌──────────────────┐    ┌──────────────────┐
       │  Language skills │  │  Domain skills   │    │  Personal skill  │
       │  rust, python,   │  │  finance,        │    │  code-style      │
       │  typescript, go, │  │  payments,       │    │  (your per-      │
       │  webassembly     │  │  supabase, …     │    │   language taste)│
       └──────────────────┘  └──────────────────┘    └──────────────────┘
```

The conductor builds each coder brief by reading the lane's `[FILE-SCOPE]`, walking
`[skills.detection]` to find the matching domains, adding the `[skills.by_domain]` entries to
`[SKILLS]`, and always including `[skills.mandatory]` (default `code-style`). The coder invokes
each `[SKILLS]` entry via the Skill tool on dispatch.

## What lives where

| Concern | Lives in |
|---|---|
| When to dispatch auditors vs coders | `skills/shepherd/references/pipeline.md` |
| Whether `pub struct Foo {params}` is hollow | shepherd principle (wrapper-must-earn) + `rust` skill (the grep) |
| What `cargo check` returns, which `clippy::*` lints to allow | `rust` skill |
| snake_case vs camelCase | `code-style:rust.md` (your preference) |
| Upstream exchange WS schema shape | not a skill — project knowledge in `CLAUDE.md` |
| `requests` vs `httpx` in Python | `code-style:python.md` |
| Payment-provider API endpoint shapes | `payments` skill |

## Hooking your skills in

```toml
[skills]
mandatory = ["code-style"]

[skills.by_domain]
rust = ["rust"]; wasm = ["webassembly"]; finance = ["finance"]; supabase = ["supabase:supabase"]

[skills.detection]
rust = ["**/*.rs"]; wasm = ["cmp/**", "**/*.wit"]; finance = ["**/circuits/**", "**/strategies/**"]
supabase = ["**/supabase/**", "**/migrations/**.sql"]
```

The engineer's plan output includes a `[SKILLS]` line per coder lane, copied into the dispatch
brief verbatim, e.g. for a lane scoped to `crates/circuits/src/drift.rs`:

```markdown
[SKILLS]
- code-style       (mandatory)
- rust             (file scope matches **/*.rs)
- finance          (file scope matches **/circuits/**)
```

If the engineer omits a mandatory skill, the Brief-Validity Checklist
(`skills/shepherd/references/flock.md §Brief assembly`) rejects the brief.

## Conductor-only skills

```toml
[hooks]
on_conductor_only = ["workflow"]   # main chat only
on_engineer_only   = ["workflow"]  # plan-time dispatch only
on_planter_only    = []
```

`workflow` is the working example — the conductor needs it for branch-cut + PR-open + release, the
coder doesn't.

## Customizing for non-Rust projects

Swap `[project].language`, `[gates]`, and `[skills.by_domain]`/`[skills.detection]` for the
language — see `docs/configuration.md §Language matrix` for the check/lint/format triples per
language. The branch lifecycle, principle enforcement, audit swarm, and SUBTRACT-DON'T-ADD
constraint apply identically.

## Adding a new language

1. Author a skill via [skill-creator](https://github.com/anthropic-experimental/skill-creator)
   covering idioms, build commands, the wrapper-must-earn detection grep, subtract-detection patterns.
2. Publish it (personal `~/.claude/skills/` or marketplace).
3. Add `<language> = ["<skill-slug>"]` to `[skills.by_domain]`.

Shepherd composes; it does not gatekeep — a new language is a config + skill addition, not a fork.

## Per-project doctrines

See [`docs/customization.md` — Project doctrines](customization.md#project-doctrines) for the full
mechanism (`.claude/doctrines/`, `[memory].project_doctrines`, conductor injection at every
dispatch).

## When the integration breaks

- Coder dispatches without `code-style` → `[skills.mandatory]` not enforced; check the engineer's plan
- Coder applies cargo conventions to a Python file → `[skills.detection]` is wrong for `**/*.py`
- Coder uses an outdated build command → `[gates].check` doesn't match the actual build system

Each is a config issue, not a framework issue. Audit `shepherd.toml` first.

## See also

- [`docs/configuration.md`](configuration.md) — the full schema
- [`docs/customization.md`](customization.md) — bring-your-own branch model, custom doctrines
