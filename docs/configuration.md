# Configuration

Shepherd speaks principles (Phase 0 mesh, SUBTRACT-DON'T-ADD, wrapper-must-earn, Pattern B
overlap); per-language mechanics load via `[skills.by_domain]`. Examples lean Rust — see the
[Language matrix](#language-matrix) for other languages.

## Resolution {#config-resolution}

Config resolves **per key** across three layers. Within a layer, `local` beats `<harness>` beats
base; across layers, **project beats user**:

```
project   <workdir>/shepherd.local.toml        this machine only, gitignored  <- ULTIMATE OVERRIDE
          <workdir>/shepherd.<harness>.toml    harness knobs, TRACKED
          <workdir>/shepherd.toml              the project binding, TRACKED   <- CANONICAL
legacy    .claude/shepherd.local.toml          pre-v6.4.2, honored forever
          .claude/shepherd.toml                pre-v6.4.2, honored forever
user      ~/.shepherd/shepherd.local.toml      this machine only
          ~/.shepherd/shepherd.<harness>.toml  harness knobs
          ~/.shepherd/shepherd.toml            cross-project DEFAULTS
          $XDG_CONFIG_HOME/shepherd.toml       pre-v6.4.2 global
```

`~/.shepherd` holds **default** behavior shared across every project; a project overrides a default
simply by setting the key. `<workdir>/shepherd.local.toml` is the highest tier there is.

**Why the canonical location moved out of `.claude/`.** `.claude/` is owned by *one* harness. The
bridge contract (`skills/bridge/SKILL.md`) requires implementations to coordinate "exclusively
through the project-visible artifact schema... never harness internals" — but a project's shepherd
binding lived inside a competing harness's config directory, so a codex or GPT harness had to read
`.claude/` just to discover the repo uses shepherd. `.shepherd/` is the namespace shepherd already
owns and every harness can read. Nothing is removed: the legacy tiers resolve indefinitely, and
`shepherd config migrate` moves the file when you choose to.

**Why legacy `.claude/` outranks the whole user layer.** Those are *project* files. If the user
layer sat higher, creating `~/.shepherd/shepherd.toml` would silently override every existing
project still bound through `.claude/` — a regression for every current install, which is not worth
tidier ordering.

### Secret hygiene in tracked tiers

`shepherd.toml` and `shepherd.<harness>.toml` are **committed**, so they must carry only portable
project/harness knobs. `shepherd config validate` rejects, in tracked tiers only:

| flagged | examples |
| :--- | :--- |
| credential-shaped keys | `api_key`, `*_token`, `password`, `client_secret`, `private_key` |
| literal credential shapes | `ghp_…`, `github_pat_…`, `sk-…`, `AKIA…`, PEM headers |
| environment references | `$VAR`, `${VAR}` — shepherd never expands these |

Put those in `shepherd.local.toml`, which is gitignored. The identical content **passes** there —
the contract is about *where* a machine-specific value lives, not that it may never exist. Findings
never echo the offending value, so the check cannot leak a secret into a CI transcript.

**`<harness>`** is the active harness only — `claude` or `codex`, resolved from `SHEPHERD_HARNESS`
(explicit, always wins), then Claude Code's own markers, then `CODEX_HOME`; absent when none is
detected. Only the active harness's file is read, so a codex knob never takes effect under Claude
Code. These files hold harness-specific knobs and are **tracked in git**, unlike `*.local.toml`,
because a harness knob is a property of the project, not of one developer's checkout. The scaffolded
`.shepherd/.gitignore` encodes exactly that.

`<workdir>` is the active shctx namespace — normally `.shepherd/`, `.artifacts/` on a legacy
project — resolved through the *same* namespace resolver every other command uses
(`shepherd_cli.resolution.resolve_workdir` in Python; `resolve_workdir` in the skills `_lib.sh`,
`resolve_namespace` in the hooks `_lib.sh`). Namespace tiers are never `.shepherd/` hardcoded: a
project bootstrapped with `shctx init --artifacts` gets them at
`<repo>/.artifacts/shepherd{.local,}.toml`, not a path that would silently miss it.
The full chain is derived in exactly one place per language —
`shepherd_cli.commands.config._config_tiers` (bash twins: `shctx_config_files` in both
`hooks/scripts/_lib.sh` and `skills/context/scripts/_lib.sh`) — and every reader (`config get`,
`config show`, `config validate`, `is_shepherd_project`) and writer (`config path`, `config init`,
`config migrate`) consumes that one list, so the chain cannot drift between callers.

**Why the canonical location moved out of `.claude/`.** `.claude/` is owned by ONE harness (Claude
Code). shepherd's own bridge contract (`skills/bridge/SKILL.md`) requires that cross-shepherd
implementations coordinate "exclusively through the project-visible artifact schema... never
harness internals" — yet, before v6.4.2, a project's *entire* shepherd binding lived inside a
competing harness's config directory. `codex-shepherd`, or any future harness, had to reach into
`.claude/` just to discover that a repo uses shepherd at all — the one thing the bridge contract
says implementations must never do to each other. `.shepherd/` (or whichever namespace directory
the resolver returns) is the namespace shepherd already owns and every harness can read, so it now
leads the chain. This is the same reasoning `naming-conventions.md §Run identity` and
`bridge/SKILL.md` apply to run ids below — a cross-harness contract cannot live inside a
single-harness directory.

**Backward compatibility is unconditional.** Tiers 3-5 keep working forever — nothing about
`.claude/shepherd.toml` resolution changed. A project that never adds a `<workdir>/shepherd.toml`
sees ZERO behavior change; this is purely additive. `is_shepherd_project()` (the "does this repo
use shepherd at all" check consumed elsewhere in the CLI) returns true if EITHER `<workdir>/
shepherd.toml` OR `.claude/shepherd.toml` exists, so callers don't need to know which tier a given
project happens to bind through.

**The canonical WRITE target moved.** `shctx config path` now echoes `<workdir>/shepherd.toml`
(tier 2), not `.claude/shepherd.toml`; `shctx config init` now scaffolds tier 2. A pre-existing
`.claude/shepherd.toml` (tier 4) is left in place and preserved — `config init` reports it and
points at `config migrate` rather than silently scaffolding a second, shadowing binding beside it.

**Migration.** `shctx config migrate [--dry-run]` moves an existing `.claude/shepherd.toml` onto
the canonical `<workdir>/shepherd.toml`. It is a plain move (git-mv semantics), not a copy: the
tier-4 file simply stops existing afterward, so there is never a stale duplicate an operator could
mistake for still-authoritative. Idempotent — a second run finds nothing at tier 4 and reports
"nothing to migrate" rather than erroring. Never overwrites an existing tier-2 destination: if both
already exist (a genuine conflict, not a re-run), it reports the conflict and stops for the
operator to resolve by hand. `--dry-run` prints the plan without touching disk.

A `.local.toml` setting one key inherits the rest — a partial, not whole-file, override — resolved
via `cfg_get`. `[models]`/`[prune]`/`[eval]`/`[dups]` use `cfg_section_get` instead: keys resolve
*within* their `[section]`, never colliding elsewhere.

If no config is found, entry commands MUST scaffold one and proceed — never refuse, never run
blind: `shctx config init` writes `<workdir>/shepherd.toml` idempotently, deriving name/gates/paths
from the repo (see also `shepherd init`, below, which now runs this scaffold as one of its own
steps). `/shepherd:spawn`: scaffold → `[CONFIG]` notice → proceed (action-biased — never stops to
confirm, `skills/shepherd/SKILL.md §Operator surface`). `/shepherd:plant`: scaffold → one
`AskUserQuestion` confirming `[branching]`/`[gates]` → continue.

## Bootstrap — `shepherd init` (v6.4.2, seamless)

```
shctx init [--artifacts|--shepherd] [--no-config] [--no-doctor] [--user]
```

`shepherd init` is now the single bootstrap for a repo: it scaffolds the namespace tree, creates
`shepherd.db` and applies every pending migration, registers the project, scaffolds the canonical
`shepherd.toml` (§Resolution, above), and runs a closing `doctor` pass — one command from a bare
repo to a fully configured project. Every step is idempotent: running `shepherd init` a second time
reports what already exists rather than re-doing (or re-warning about) work already done, and a
closing bootstrap summary states created-vs-already-present for each of the five things it touches
(namespace, db, project, `shepherd.toml`, user tier).

This **replaces** the old "run `shepherd init`, then separately run `shepherd config init`"
sequencing — that hand-off was the friction point being removed, and no doctrine should still
instruct an operator (or an agent) to run the two as separate steps. `shepherd init` alone now
covers both.

Flags:

| Flag | Effect |
|---|---|
| `--artifacts` / `--shepherd` | force the legacy `.artifacts/` or new-default `.shepherd/` namespace on a fresh init (auto-detected otherwise) |
| `--no-config` | skip the `shepherd.toml` scaffold step — reproduces the pre-v6.4.2 narrow behavior when combined with `--no-doctor` |
| `--no-doctor` | skip the closing `doctor` pass (the summary block still prints) |
| `--user` | also bootstrap `~/.shepherd` (`shepherd home init`) — the only step here that touches `$HOME`, so it is opt-**in**, off by default |

`--no-config --no-doctor` with neither `--artifacts`/`--shepherd`/`--user` reproduces the exact
on-disk effect of pre-v6.4.2 `shepherd init`: no `shepherd.toml` is written, no doctor pass runs,
`~/.shepherd` is never touched.

## Schema

### `[project]` — identity

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | *(required)* | repo/project name |
| `language` | enum | `"rust"` | `rust\|python\|typescript\|go\|mixed`; drives `[skills.by_domain]` |
| `description` | string | `""` | free text |
| `harnesses` | list of string | `[]` | which shepherd implementations operate in this repo, e.g. `["claude-code", "codex"]` |

`harnesses` is declarative metadata only (v6.4.2) — a machine-readable anchor for the bridge
contract (`skills/bridge/SKILL.md`), so an implementation booting into a repo can tell "no other
harness is configured here" from "a sibling is declared and may hold custody over a run" before it
even looks at `run.json`. It is deliberately **not** enforced and **not** wired into dispatch:
shepherd does not coordinate harnesses automatically, no command reads this key to decide what to
run, and an undeclared harness working in the repo is not blocked or warned about. Keep the scope
claim honest — this is a label an operator sets, not a mechanism.

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
| `version_files` | list of string | *(not read)* — see note below |
| `mod_base` | table `{sprint, patch, minor}` | *(not read)* — see note below |

`{X}{Y}{Z}{N}` are fixed integer placeholders. Branches keep dots; filenames use `*_slug_pattern`
instead (falls back to `*_branch_pattern` + a deprecation warning). See
`skills/shepherd/references/seed-template.md`.

`version_files` and `mod_base` are doctrine-only keys (`skills/shepherd/references/branching-model.md:33` and `:46`). Neither is wired into the release pipeline yet. `services/cli/shepherd_cli/commands/release.py`'s `VERSION_FILES` module constant hardcodes the five bumped files (`.claude-plugin/plugin.json`, `skills/shepherd/SKILL.md`, `skills/context/SKILL.md`, `.claude-plugin/marketplace.json`, `README.md`) instead of reading `[branching].version_files`, and `_next_version()` hardcodes the mod-10 `< 9` rollover gears instead of reading `[branching].mod_base`; the module's own header comment (lines 25-28) documents this as a known, deferred gap. Treat both keys as planned, not live, until a config-read lands.

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

| Key | Default | Status |
|---|---|---|
| `runs` | `.shepherd/runs` | Run-scoped artifact root |
| `docs` | `.shepherd/docs` | Cross-run docs (specs, diagrams, journal, ledgers) |
| `ctx` | `.shepherd/ctx` | The one cross-run knowledge silo |
| `plans` | `.shepherd/docs/plans` | **LEGACY** — pre-layout-v3; not a write target |
| `reports` | `.shepherd/docs/reports` | **LEGACY** — pre-v6.4.4; not a write target |

Relative to the repo root, auto-created on write. `{run_dir}` = `{paths.runs}/{run}` — the per-run
artifact directory (`{run}` == sprint/patch slug); run-scoped artifacts live there under FIXED
names.

**`plans` and `reports` are read-only legacy keys.** Layout v3 moved seeds and plans into
`runs/{run}/`; v6.4.4 moved audits into `runs/{run}/audits/` and read-only-role reports into
`runs/{run}/reports/`. Neither key names a destination anything writes to any more — they stay so
`lint`/`refresh` still find pre-migration files. Do not aim a new writer at them: a run-scoped
artifact goes in `{run_dir}`, a cross-run one in `docs`/`ctx`. Which is which:
`naming-conventions.md §The docs/ vs {run_dir} boundary`.

`shctx init` scaffolds the standard tree; `shepherd migrate --layout v2` moves a legacy project onto
the docs/ layout, `--layout v3` onto `runs/` + `profiles/`, `--layout v4` retires `memory/`. Layout,
ownership, and the tracked/ignored split: `skills/context/references/naming-conventions.md`.

Two CLI commands own this layer: `shepherd run <init|show|list|set|lane|wave>` maintains
`{run_dir}/run.json` (schema-validated, the #242 boundary-merge ledger — `run wave pending` exits 6
while accepted-but-unmerged lanes remain); `shepherd render <template> [--vars-json F] [--out F]
[--manifest]` renders Jinja2 templates (StrictUndefined), resolving project `.shepherd/templates/`
→ user `~/.shepherd/templates/` → bundled package data.

**Namespace default is `.shepherd/`** (legacy `.artifacts/` opts in via `shctx init --artifacts`).
`[paths]` MUST match the active namespace or `shctx doctor` flags a conflict; `shctx init` REFUSES
to scaffold a second namespace when the other exists. `$SHEPHERD_WORKDIR` precedence: env var →
`$SHCTX_ROOT_OVERRIDE` (legacy) → `.shepherd/` → `.artifacts/` → default `.shepherd/`.

**User home is `~/.shepherd`** (`SHEPHERD_HOME` env overrides): cross-project defaults — user
profiles, user templates — never project state. Style-profile resolution, first hit wins: project
`.shepherd/profiles/{profile}/style.md` → project legacy `styles/{profile}.md` →
`~/.shepherd/profiles/{profile}/style.md` → bundled `skills/context/styles/{profile}.md`. Writes
always target the project tier.

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
`skills/context/schema/0001_init.sql`.

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
| `carry_forward_file` | string | `"{paths.docs}/v{X}.{Y}.{Z}-carry-forwards.md"` |
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
| `flag_handrolled_fanout` | bool | `true` | `dispatch_guard.sh` Check 6 — warn when a role on a live Agent-Teams substrate hand-rolls a flock fan-out instead of compiling it to a Dynamic Workflow (default ON as of v6.4.3, #263; set `false` to silence) |
| `workflow_model_guard` | enum | `"block"` | `block\|warn\|off` — `workflow_model_guard.sh` PreToolUse(Workflow) dispatch-model-pin gate (#178) |
| `teammate_heartbeat` | enum | `"on"` | `on\|off` — `teammate_heartbeat.sh` PreToolUse auto-stamp of the current teammate's `last_seen_at` so `shctx teammate liveness` needs no self-report (#193) |

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
| `lead_effort` | enum | `"ultracode"` | effort injected into lead sessions (`@engineer`, `@conductor`) at spawn; `ultracode` makes Dynamic-Workflow fan-out the default. `off` leaves the lead session's effort unchanged (#198 direction) |
| `stale_sweep_minutes` | int | `60` | reboot horizon for the lead-session-start liveness sweep (#229): rows from OTHER sessions older than this with no in-progress declaration flip to `crashed` so they leave the live set. `0` disables the sweep |

`lead_effort`: the lead sets its session effort on turn one from the boot-brief `Lead effort:` pin
(`commands/spawn.md §Lead effort`). Leads own fan-out (the engineer's intro wave, the conductor's
per-lane steps), so the effort level itself drives Workflow-first orchestration — no brief-context
spent nagging for it. Subagents/workers are unaffected. Orchestration SHAPE still comes from the
critic-gated stage graph, never the effort level (`skills/harness/references/workflow-templates.md`).

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
| `precompact_snapshot` | enum | `"on"` | `on\|off` — PreCompact hook snapshots ready/in-flight sets, trace tail, lock, focus digest; NEVER blocks compaction |
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
v0.2.9-release-notes.md` for v0.2.9. `{run_dir}` expands to `{paths.runs}/{run}` for the run in
scope — e.g. `{run_dir}/seed.md` → `.shepherd/runs/v641-dev0/seed.md`.

## Defaults

If `shepherd.toml` is missing, shepherd falls back to the per-key defaults tabulated above and
warns on every invocation until a file exists.

## Validation

`/shepherd:spawn` validates at Step 0. Blocking: patch/sprint patterns share no common prefix;
`gates.check` binary not on `$PATH`; a `paths.*` dir isn't writeable; `[skills.by_domain]` names an
uninstalled skill; `driver="github-workflow"` but `workflow_file` doesn't resolve. Warnings only:
an `[mcp]` server is `true` but unloaded; `phase_0_full_ledger=true` under 5 open issues.

### `shepherd config validate` — schema validation (v6.4.2)

```
shctx config validate [--json]
```

Validates every existing precedence-tier file (§Resolution, above) **separately** against the
`shepherd.toml` pydantic schema — never the merged/resolved config. A bad key in
`.claude/shepherd.local.toml` is reported against that file, not misattributed to `.claude/
shepherd.toml` sitting one tier lower: every issue names both the FILE it came from and the
`[section].key` path inside it, so an operator with config spread across two or three tiers knows
exactly which one to fix. A tier that doesn't exist on disk is skipped, not reported as missing.

Unknown keys and unknown `[section]`s are now **errors**, not silent fallbacks — a typo in a key
name used to be silently ignored (the default simply applied, with no signal anything was wrong).
Each unknown-key/-section error carries a `difflib`-computed did-you-mean against the real schema
(cutoff `0.6`) when a close match exists — e.g. `[gates] lint_` → `did you mean 'lint'?`. A wrong
*type* for a known key names the allowed set/type directly rather than a raw pydantic traceback.

Exit 0 when every existing tier validates clean (including when none exist at all — nothing to
validate is not a failure); nonzero when any existing tier has at least one issue. `--json` emits
`{"ok": bool, "files": [{"file", "ok", "issues": [{"path", "kind", "message", "bad_value",
"allowed", "suggestion"}, ...]}, ...]}` instead of the human-readable text report, for tooling.

### Run id canonicality — `shepherd lint` (v6.4.2)

`shctx lint` also WARNs on a non-canonical run id — a run directory whose name isn't exactly what
`[branching].sprint_slug_pattern`/`patch_slug_pattern` derives for it (e.g. a harness or ordinal
suffix appended by hand). See `skills/context/references/naming-conventions.md §Run identity` for
the full rule and rationale, and `shepherd run canonicalize` for migrating an existing violation.

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
