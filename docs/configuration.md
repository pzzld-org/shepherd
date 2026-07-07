# Configuration

Shepherd speaks principles (Phase 0 mesh, SUBTRACT-DON'T-ADD, wrapper-must-earn, Pattern B
overlap); per-language mechanics load via `[skills.by_domain]`. Examples lean Rust — see the
[Language matrix](#language-matrix) for other languages.

## Resolution

Drop a `shepherd.toml` at one of these locations, highest precedence first, **per key**:

```
.claude/shepherd.local.toml    project-pinned, gitignored (overrides)
.claude/shepherd.toml          project-pinned, in the repo (base)
$XDG_CONFIG_HOME/shepherd.toml user-global default
```

A `.local.toml` setting one key inherits the rest — a partial, not whole-file, override — resolved
via `cfg_get`. `[models]`/`[prune]`/`[eval]`/`[dups]` use `cfg_section_get` instead: keys resolve
*within* their `[section]`, never colliding elsewhere.

If no config is found, entry commands MUST scaffold one and proceed — never refuse, never run
blind: `shctx config init` writes `.claude/shepherd.toml` idempotently, deriving name/gates/paths
from the repo. `/shepherd:spawn`: scaffold → `[CONFIG]` notice → proceed (action-biased — never
stops to confirm, `skills/shepherd/SKILL.md §Operator surface`). `/shepherd:plant`: scaffold → one
`AskUserQuestion` confirming `[branching]`/`[gates]` → continue.

## Schema

### `[project]` — identity

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | *(required)* | repo/project name |
| `language` | enum | `"rust"` | `rust\|python\|typescript\|go\|mixed`; drives `[skills.by_domain]` |
| `description` | string | `""` | free text |

### `[branching]` — branch topology

| Key | Type | Default |
|---|---|---|
| `patch_branch_pattern` | string | `"v{X}.{Y}.{Z}"` |
| `sprint_branch_pattern` | string | `"v{X}.{Y}.{Z}-dev.{N}"` |
| `patch_slug_pattern` | string | `"v{X}{Y}{Z}"` |
| `sprint_slug_pattern` | string | `"v{X}{Y}{Z}-dev{N}"` |
| `sprints_per_patch` | int | `10` |
| `main_branch` | string | `"main"` |
| `release_tag_pattern` | string | `"v{X}.{Y}.{Z}"` |
| `allow_direct_main_commit` | bool | `false` — MUST NEVER be `true` except solo bootstrap |

`{X}{Y}{Z}{N}` are fixed integer placeholders. Branches keep dots; filenames use `*_slug_pattern`
instead (falls back to `*_branch_pattern` + a deprecation warning). See
`skills/shepherd/references/seed-template.md`.

### `[gates]` — between-wave validation

| Key | Type | Default | Meaning |
|---|---|---|---|
| `check`/`lint`/`format` | string | project-specific | run in order between waves and at close; empty skips; non-zero halts the wave + triggers hot-fix dispatch |
| `extra` | list of `{name,cmd}` | `[]` | supplementary gates after the primary three pass |
| `target_clean_threshold_gb` | int | `20` | auto-clean `target/` (`0` disables) |
| `subtract_paths` | list of globs | project-specific | scopes SUBTRACT-DON'T-ADD to production source — `skills/shepherd/SKILL.md §Principles` |

### `[dups]` — field-shape dedup

Tunes `shctx dups`, the field-shape detector that catches a renamed-shadow duplicate. See
`skills/context/SKILL.md §Dedup`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `dups_threshold` | float 0..1 | `0.7` | cluster/report/check similarity floor |
| `dups_block` | float 0..1 | `0.85` | hook DENY threshold |
| `dups_name_weight` | float | `0.5` | field-name vs typed-pair Jaccard weight |
| `dups_min_fields` | int | `2` | ignore shapes below N fields |
| `dups_hook` | enum | `"warn"` | `off\|warn\|block` |

Keys are `dups_`-prefixed. `warn` surfaces a reuse suggestion, never blocks; `block` denies a
≥`dups_block`-similar write; `off` disables; fails open with no `python3` or empty corpus. Refresh:
`shctx refresh --scope=shapes`. Fail the sprint on a shadow via a `shape-dedup` `[gates].extra`
entry; exempt twins via `shctx dups registry allow A B`.

### `[paths]` — artifact locations

| Key | Default |
|---|---|
| `plans` | `.shepherd/docs/plans` |
| `reports` | `.shepherd/docs/reports` |
| `docs` | `.shepherd/docs` |
| `ctx` | `.shepherd/ctx` |

Relative to the repo root, auto-created on write. `shctx init` scaffolds the standard tree;
`shctx migrate --layout v2` moves a legacy project onto it. See
`skills/context/references/naming-conventions.md`.

**Namespace default is `.shepherd/`** (legacy `.artifacts/` opts in via `shctx init --artifacts`).
`[paths]` MUST match the active namespace or `shctx doctor` flags a conflict; `shctx init` REFUSES
to scaffold a second namespace when the other exists. `$SHEPHERD_WORKDIR` precedence: env var →
`$SHCTX_ROOT_OVERRIDE` (legacy) → `.shepherd/` → `.artifacts/` → default `.shepherd/`.

### `[context]` — context registry

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `true` | DB-optional pre-migration; refused post-migration |
| `db_path` | string | `.shepherd/shepherd.db` | SQLite registry |
| `lock_path` | string | `.shepherd/shepherd.lock` | single-writer lock |
| `project_id_path` | string | `.shepherd/project.json` | stable `project_id` |
| `auto_refresh` | list | `["on-sprint-open"]` | additive: `on-sprint-open`, `on-engineer-dispatch`, `on-close-finalize`, `on-wave-gate` |
| `announce_shctx_path` | enum | `"on"` | `on\|off` — surfaces the resolved `shctx` path |
| `announce_core_doctrine` | enum | `"on"` | `on\|off` — points to `skills/shepherd/references/operating-philosophy.md` |
| `announce_adaptation` | enum | `"on"` | `on\|off` — surfaces sprint/prior counts + newest lesson + trend alert |

Sub-tables `[context.refresh]`, `[context.lock]`, `[context.naming]` — see
`skills/context/schema/0001_init.sql`. The toolkit (`toolkit.json`) is documented at
`skills/context/references/toolkit.md`. NEVER store secrets in it.

### `[skills]` — local-skill integration

| Key | Type | Default | Meaning |
|---|---|---|---|
| `mandatory` | list | `["code-style"]` | MUST appear in every `[SKILLS]`; Brief-Validity Checklist rejects a brief missing one |
| `by_domain` | table | — | domain → skill-slug list |
| `detection` | table | — | domain → glob-pattern list, matched against `[FILE-SCOPE]` |

### `[mcp]` / `[cli]` — tool availability

Boolean per server/binary; `false` downgrades the Phase 0 mesh row to "if available" and omits the
tool from the engineer's brief.

| `[mcp]` key | Default | | `[cli]` key | Default |
|---|---|---|---|---|
| `github` | `true` | | `fly` | `true` |
| `sentry` | `true` | | `gh` | `true` |
| `supabase` | `true` | | `docker` | `true` |
| `grafana` | `false` | | `just` / `make` | `false` |

### `[ledger]` — issue-ledger awareness

| Key | Type | Default |
|---|---|---|
| `phase_0_full_ledger` | bool | `true` — `0` disables |
| `classify_into` | list | `["blocking-this-sprint","labeled-non-issue","tracking-future","drift-risk"]` |
| `non_issue_labels` | list | `["wontfix","tracking-future","design-question","rfc"]` |
| `carry_forward_file` | string | `"{paths.plans}/v{X}.{Y}.{Z}-carry-forwards.md"` |
| `chronic_threshold_patches` | int | `2` |

`phase_0_full_ledger=true` requires enumerating + classifying the full (not just current-milestone)
open-issue space at every sprint open.

### `[release]` — release pipeline

| Key | Type | Default | Meaning |
|---|---|---|---|
| `driver` | enum | `"github-workflow"` | `conductor` (shepherd drives it) \| `github-workflow` (GH Actions does) \| `operator` (notes only) |
| `release_notes_path` | string | `"{paths.docs}/v{X}.{Y}.{Z}-release-notes.md"` | |
| `workflow_file` | string | `.github/workflows/release.yml` | required when `driver="github-workflow"` |
| `devlast_guard` | enum | `"block"` | `block\|warn\|off` — refuses a branch numbered ≥ `sprints_per_patch` (`dev.{last}` closes to a release) |

### `[tmux]` — teammate pane observability

| Key | Type | Default | Meaning |
|---|---|---|---|
| `pane_cleanup` | enum | `"on"` | `on\|off` — reap panes of closed teammates at SessionEnd |

`shctx panes status`/`capture`/`tail <lane>` observe live panes (pane id auto-captured).

### `[memory]` — memory + doctrine paths

| Key | Type | Default | Meaning |
|---|---|---|---|
| `project_memory` | string | `~/.claude/projects/<project>/memory` | read-only auto-memory |
| `project_doctrines` | string | `.claude/doctrines` | project DRIFT rules; loaded into EVERY flock dispatch |

### `[hooks]` — local skill / hook integration

| Key | Type | Default | Meaning |
|---|---|---|---|
| `on_every_dispatch` | list | `["code-style"]` | loaded by every flock agent, plus its own `[SKILLS]` |
| `on_conductor_only` | list | `[]` | conductor-only |
| `on_engineer_only` | list | `["workflow"]` | engineer-only |
| `on_planter_only` | list | `[]` | planter-only |
| `quiet_warnings` | bool | `false` | suppress informational `additionalContext` (still logged) |
| `flag_handrolled_fanout` | bool | `false` | `dispatch_guard.sh` Check 6 — warn when a teammate hand-rolls a flock fan-out instead of compiling it |
| `workflow_model_guard` | enum | `"block"` | `block\|warn\|off` — `workflow_model_guard.sh` PreToolUse(Workflow) dispatch-model-pin gate (#178) |

`workflow_model_guard`: blocks (default) a submitted Dynamic Workflow script whose `agent()` calls
carry neither `model:` nor `agentType:` — the shape that silently inherits the MAIN-LOOP model
instead of resolving from `[models]` (`skills/context/references/model-map.md`). String-content-
blind (a prompt merely mentioning "model:" cannot fake a pass) and fails open on anything it can't
see (a saved/named workflow, an unreadable `scriptPath`, no `python3`). One-off acknowledgment: a
`// shepherd:model-pin-override` line comment anywhere in the script — always logged, never silent,
reported via `additionalContext` even in block mode. `warn` proceeds with the same message via
`additionalContext`; `off` disables the scan entirely. See `hooks/scripts/workflow_model_guard.sh`.

### `[spawn]` — teammate-spawn coordination

| Key | Type | Default | Meaning |
|---|---|---|---|
| `coordinate_drive_guard` | enum | `"block"` | `block\|warn\|off` — Stop-hook backstop |
| `wave_ack_timeout_sec` | int | `60` | wait before continuing without a wave-ack |
| `cross_dep_timeout_sec` | int | `300` | escalates CROSS-DEP-WAIT |
| `max_parallel` | int | `4` | upper bound on `--parallel <N>` |
| `dashboard_cadence` | duration | `"3m"` | `shctx dash` loop interval |
| `staged_timeout_minutes` | int | `90` | `--staged` poll timeout before `STAGED-TIMEOUT` |

`coordinate_drive_guard`: `block` re-engages the root at a premature end-turn, capped at 2 nudges
then fails open; `warn` nudges via stderr; `off` disables; fast-paths outside a live spawn session
(`skills/harness/SKILL.md`, `skills/motivation/SKILL.md`). `ENABLE_PROMPT_CACHING_1H=1` opts
`--scope >= patch` into the 1-hour prompt-cache TTL.

### `[autorun]` — unattended sequential walks

| Key | Type | Default | Meaning |
|---|---|---|---|
| `min_grade` | letter grade | `"B"` | floor for continuing an unattended walk |
| `on_grade_floor` | enum | `"abort"` | `abort` (stop) \| `pause` (one operator decision) \| `continue` (warn, proceed) |
| `inter_sprint_pause` | enum | `"brief"` | `brief` (~5s) \| `signoff` (hard pause) \| `none` |

### `[compaction]` — compaction resilience

| Key | Type | Default | Meaning |
|---|---|---|---|
| `precompact_snapshot` | enum | `"on"` | `on\|off` — PreCompact hook snapshots ready/in-flight sets, trace tail, mailbox, lock, focus digest; NEVER blocks compaction |
| `snapshot_retention` | int | `5` | snapshots retained per namespace (`0` = unlimited) |

`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (int 1-100, `settings.json` → `env`) is the only auto-compaction
timing knob — global, no disable toggle. Agents CANNOT self-trigger or steer compaction; shepherd
only makes each event safe (snapshot).

### `[focus]` — focus loop rehydration

| Key | Type | Default | Meaning |
|---|---|---|---|
| `rehydrate` | enum | `"on"` | `on\|off` — re-inject the latest precompact snapshot as `additionalContext` after compaction |
| `heartbeat_actions` | int | `20` | `0` disables — soft self-prompt: re-anchor after ~N actions |
| `heartbeat_interval` | duration | `""` | `""` (off) or e.g. `"45m"` — deterministic wall-clock re-anchor via native `/loop` |

**FOCUS-HEARTBEAT has two unequal legs — do not collapse them.** `heartbeat_interval` is the
DETERMINISTIC leg — a real `/loop`-driven wake, the only leg that GUARANTEES a re-anchor.
`heartbeat_actions` is a SOFT self-prompt, NOT a counted guarantee. Treating it as one reintroduces
long-active-stretch drift; set `heartbeat_interval` where a guarantee matters. See
`skills/motivation/SKILL.md §FOCUS-HEARTBEAT`.

### `[close]` — close-phase behavior

| Key | Type | Default | Meaning |
|---|---|---|---|
| `autonomous_sentinel` | enum | `"off"` | `off\|on` |

`off` is detection-only: a SOAK-LOOP surfaces an OUTCOME-REGRESSION, operator decides. `on` ALONE
does nothing — the seed MUST ALSO declare `close: autonomous-sentinel` AND carry a complete
`sentinel_rails` block (gates-before-deploy, max_severity, max_concurrent, hf_cap,
no_destructive_db_ops, auto_rollback, live_flip, operator_override_each_tick, audit_trail). All
THREE gates are independently required. See `skills/motivation/SKILL.md §Sentinel`.

### `[eval]` — latent-output eval harness

Scores a latent output (reflection, discovery report, seed) against a rubric via `services/llm`.
Keys are `eval_`-prefixed. See `services/eval/README.md`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `eval_judge_model` | model alias | *(empty → `opus`)* | never a silent downgrade; `--model` on `shctx eval run` overrides |
| `eval_on_close` | enum | `"off"` | `on\|off` — auto-runs the reflection eval at CLOSE-FINALIZE |

### `[discovery]` — capability auto-discovery

| Key | Type | Default | Meaning |
|---|---|---|---|
| `auto_capabilities` | enum | `"on"` | `on\|off` — enumerates plugins/skills into ephemeral `discovered-capabilities.json` (distinct from curated `toolkit.json`, `skills/context/references/toolkit.md`); fails open |

### `[models]` — per-role subagent model map

Resolved via `shctx models resolve <role>`, injected as the `model:` pin — see
`skills/context/references/model-map.md`.

| Role | Default |
|---|---|
| `root` (advisory only) | `opus[1m]` |
| `planter`, `engineer` | `opus[1m]` |
| `conductor`, `critic`, `discovery`, `coder`, `auditor`, `worker` | `sonnet` |

Resolution: explicit `[models].<role>` key, else built-in default.

### `[prune]` — workdir + registry GC

Retention windows for `shctx prune` (`skills/context/SKILL.md §Workdir hygiene`). `--dry-run` is
default; `--confirm` MOVES eligible targets to `/tmp/shepherd-prune-<epoch>/` (reversible).
Eligible: branch≠current ∧ terminal ∧ aged. NEVER touched: `index_releases`, current focus,
`sprint_metrics`, pinned memory, active locks/loops.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `logs_days` | int (days) | `60` | age floor: `logs/events-*.jsonl`, `logs/hooks/*.jsonl` |
| `dispatch_days` | int (days) | `30` | age floor: `dispatch/<sprint>/` dirs |
| `snapshots_keep` | int | `20` | precompact snapshots retained (newest-first) |
| `findings_sprints` | int | `6` | keep discovery/audit findings for the last N sprints |

Flags override config (`--logs-days=`, `--dispatch-days=`, `--snapshots-keep=`); `--vacuum`
reclaims space; `--json` emits a machine-readable plan.

## Path interpolation

`{X}/{Y}/{Z}/{N}` placeholders in `branching`/`release`/`ledger`, and `{paths.*}` references,
interpolate at runtime — e.g. `"{paths.docs}/v{X}.{Y}.{Z}-release-notes.md"` → `.shepherd/docs/
v0.2.9-release-notes.md` for v0.2.9.

## Defaults

If `shepherd.toml` is missing, shepherd falls back to the per-key defaults tabulated above and
warns on every invocation until a file exists.

## Validation

`/shepherd:spawn` validates at Step 0. Blocking: patch/sprint patterns share no common prefix;
`gates.check` binary not on `$PATH`; a `paths.*` dir isn't writeable; `[skills.by_domain]` names an
uninstalled skill; `driver="github-workflow"` but `workflow_file` doesn't resolve. Warnings only:
an `[mcp]` server is `true` but unloaded; `phase_0_full_ledger=true` under 5 open issues.

## Language matrix

| Language | check | lint | format | Build manifest |
|---|---|---|---|---|
| Rust | `cargo check --workspace` | `cargo clippy -- -D warnings` | `cargo fmt --all` | `Cargo.toml` |
| Python | `uv run mypy .` | `uv run ruff check .` | `uv run ruff format .` | `pyproject.toml` |
| TypeScript | `pnpm tsc --noEmit` | `pnpm eslint .` | `pnpm prettier --check .` | `package.json` |
| Go | `go build ./...` | `go vet ./...` | `gofmt -l -w .` | `go.mod` |
| Mixed | (compose per language) | (compose per language) | (compose per language) | per-language |

Add `<lang> = ["<lang>"]` to `[skills.by_domain]`/`[skills.detection]`; author an unlisted
language's skill via [skill-creator](https://github.com/anthropic-experimental/skill-creator).

## See also

- [`docs/integration.md`](integration.md) — skill composition
- [`docs/customization.md`](customization.md) — custom branch model, doctrines
- [`examples/rust-service/shepherd.toml`](../examples/rust-service/shepherd.toml) — worked example
