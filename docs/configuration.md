# Configuration

Shepherd configuration is a typed Rust schema. The native `shepherd` binary
loads it; adapters do not parse or merge configuration themselves.

## Canonical locations

The project tier is `.shepherd/`. The user tier is `~/.shepherd/`. The project
tier wins over the user tier, and a harness-specific file wins over the base
file within its tier.

```text
project  .shepherd/shepherd.local.toml       # ignored, machine-only overrides
         .shepherd/shepherd.<harness>.toml   # tracked harness settings
         .shepherd/shepherd.toml             # tracked project settings

user     ~/.shepherd/shepherd.local.toml     # ignored, machine-only defaults
         ~/.shepherd/shepherd.<harness>.toml # user harness defaults
         ~/.shepherd/shepherd.toml           # user defaults
```

`shepherd.local.toml` is for local paths or credentials. Tracked files reject
credential-shaped keys, literal credential formats, and environment expansion.
Shepherd does not print the offending value in a validation error. Environment
variables are not expanded inside TOML.

Legacy `.claude/shepherd*.toml`, `.artifacts/`, and XDG configuration are
accepted only as migration inputs. They are not canonical write targets. A
project should have one effective project configuration after migration.

Inspect resolution without mutating files:

```sh
shepherd config path
shepherd config show
shepherd config get project.name
shepherd doctor
```

Initialize explicitly when needed:

```sh
shepherd init --confirm
shepherd config init --confirm
shepherd home which
shepherd home show
shepherd home init --confirm
```

`init` is the project bootstrap. `home init` is a separate authorization because
it writes outside the repository. Both are idempotent.

## Schema groups

The schema is closed. Unknown keys fail validation rather than being silently
ignored. The principal groups are:

| Table | Purpose |
| --- | --- |
| `[project]` | Name, language (`rust`, `python`, `typescript`, `go`, `mixed`, `markdown`), description, and declared harness labels. |
| `[branching]` | Patch/sprint branch and slug patterns, main branch, release tag pattern, and direct-main policy. |
| `[gates]` | Check, lint, format, extra commands, and subtract paths. |
| `[paths]` | Canonical `docs`, `ctx`, and `runs` roots. Layout-v5 rejects `plans` and `reports` as write destinations. |
| `[dups]` | Duplicate declaration policy and registry path. |
| `[skills]` | Mandatory skills, domain mappings, and file-pattern detection. |
| `[ledger]` | Run ledger and carry-forward behavior. |
| `[context]` | Refresh, lock, naming, and context selection policy. |
| `[hooks]` | Host hook toggles. Hook mechanics remain adapter-local. |
| `[spawn]`, `[autorun]`, `[compaction]`, `[focus]`, `[close]` | Execution lifecycle policies. |
| `[eval]`, `[models]`, `[prune]` | Recorded evaluation metadata, model labels, and retention policy. |

The layout roots are not a second policy language. A valid v6.4.6 configuration
must resolve `docs`, `ctx`, and `runs` beneath the project `.shepherd/` namespace
unless an explicitly supported embedding host supplies an equivalent root.

## Portable model hints

`[models]` stores model intent, not a provider-specific model id. The canonical
values are `inherit-caller`, `reasoning-high`, and `standard`. Defaults are:

| Role | Hint |
| --- | --- |
| root | `inherit-caller` |
| planter, engineer | `reasoning-high` |
| conductor, critic, discovery, coder, auditor, worker | `standard` |

`shepherd models resolve <role>` returns the portable hint. Add
`--harness claude`, `--harness codex`, or `--harness pi` to resolve that hint
through the compiler's typed `HarnessProfile`. The CLI imports that Rust table;
adapters and configuration do not maintain a second model map. Unknown hints
fail when a harness-native value is requested.

## Layout-v5 paths

These paths are fixed by the native layout contract:

```text
.shepherd/docs     # flat cross-run documents
.shepherd/ctx      # structured cross-run context
.shepherd/runs     # run-specific artifacts
.shepherd/shepherd.db
.shepherd/shepherd.lock
.shepherd/project.json
```

Do not configure or create `docs/specs`, `docs/reports`, `plans`, `reports`, or
`memory` as new destinations. Migration may read old locations, snapshot them,
and move their contents to their canonical owners.

## Migration

Migration is a separate native command. It emits a plan before it mutates and
requires an explicit scope authorization:

```sh
shepherd migrate --layout v5 --scope project --dry-run
shepherd migrate --layout v5 --scope project --confirm \
  --snapshot-dir /tmp/shepherd-layout-v5-project
shepherd migrate --layout v5 --scope user-home --dry-run
```

The planner checks for malformed state, unsafe symlinks, path traversal,
collisions, duplicate authorities, and input bounds before execution. A second
dry run should report no work. Keep the snapshot until the migrated namespace
has passed `shepherd doctor` and the project gate.

## Run ownership

The run slug is the identity. `shepherd run ...` owns `runs/<run>/run.json` and
its atomic lifecycle transitions. Adapters may record typed dispatch and
resume facts, but may not invent a second run ledger.

Run-specific files belong under the run:

```text
.shepherd/runs/<run>/
  seed.md mesh.md plan.md handoff.md close.md
  lanes/<lane>/plan.md
  dispatch/ reports/ audits/
```

Cross-run documents belong directly under `.shepherd/docs/`; keep that directory
flat. Structured searchable state belongs in `.shepherd/ctx` or the native
registry. This split prevents a run from depending on a date-prefixed nested
docs tree and makes resume portable across Claude, Codex, and Pi.

## Context and prompt budgets

The compiler applies the same versioned UAX #29 measurement to every harness.
It measures lines, Unicode words, UTF-8 bytes, and a model-neutral token
estimate. Current hard limits are:

| Surface | Lines | Words | Bytes |
| --- | ---: | ---: | ---: |
| Skill | 100 | 500 | 6 KiB |
| Always-loaded skill | 60 | 200 | 3 KiB |
| Role | 100 | 600 | 7 KiB |
| Reference | 220 | 1,500 | 16 KiB |
| Doctrine | 160 | 1,000 | 12 KiB |
| Command | 140 | 750 | 9 KiB |
| Always-loaded bundle | 300 | 2,000 | 22 KiB |
| Harness skill set | 700 | 3,500 | 42 KiB |

These are ceilings. Prefer one authoritative instruction, references loaded on
demand, and short role contracts. Do not copy the same policy into a role, a
skill, and a run brief. An empty or over-budget surface fails compilation.

## Secret hygiene

Never place API keys, tokens, passwords, private keys, or environment expansion
syntax in a tracked project or harness file. Store machine-only values in a
gitignored `.local.toml` and keep credentials in the host's normal secret
store. Run `shepherd doctor` after configuration changes. Do not include secret
values in run artifacts, reports, or handoffs.

## See also

- [Integration](integration.md) for adapter and skill composition.
- [Customization](customization.md) for project policy, skills, and templates.
- [Memory](memory.md) for structured context versus host-native memory.
- [Root README](../README.md) for build, Component Model, and command status.
