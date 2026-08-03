# Artifact schema — namespace, run layout, ownership

The canonical map of WHERE every shepherd artifact lives and WHO writes it.
Doctrine cites paths in the `{run_dir}/…` forms defined here — restating a
path elsewhere is a drift bug. `shctx lint` enforces the filename and
directory patterns; overrides live in `[context.naming]` of `shepherd.toml`
(canonically `<workdir>/shepherd.toml` as of v6.4.2; `.claude/shepherd.toml`
still resolves — see `docs/configuration.md §Resolution`).

## Namespace selection

**`.shepherd/` is the only project-visible namespace.** `.artifacts/` is
legacy — honored by every resolver, never written into new doctrine; opt in
via `shctx init --artifacts`. Auto-detection: whichever of
`.shepherd/`/`.artifacts/` already exists in the repo root wins (preferring
`.shepherd/` if both exist).

**Conflict guard:** `shctx init` MUST refuse to create a new namespace
directory when the *other* namespace is already an initialized shctx
workspace (detected by its `.gitignore` marker) — this prevents split-brain
where data lands in one namespace while `shepherd.toml [paths]` points at the
other. If both coexist, `shctx doctor` surfaces a `WARN` check.

Legacy `.artifacts/`, `root.db`, and top-level `plans/`/`reports/` are fully
supported and auto-detected. Resolver order (`resolve_workdir`):
`SHEPHERD_WORKDIR` → `SHCTX_ROOT_OVERRIDE` → existing `.shepherd/` → existing
`.artifacts/` → default `.shepherd/`. DB resolver (`shctx_db_path`): checks
`shepherd.db` first, falls back to `root.db` if it exists; new projects
default to `shepherd.db`. `shepherd migrate --layout v2` moves `plans/*` →
`docs/plans/`, `reports/*` → `docs/reports/`, renames `root.db*` →
`shepherd.db*`; `--layout v3` moves `docs/plans/{slug}.seed.md` →
`runs/{slug}/seed.md` (plan/phase0/close/handoff likewise) and
`styles/<lang>.md` → `profiles/<lang>/style.md` — idempotent, never clobbers
existing destination files.

## User home — `~/.shepherd`

`~/.shepherd` is the user-level home (`SHEPHERD_HOME` env overrides the
location): cross-project defaults, never project state. It hosts
`~/.shepherd/profiles/{profile}/style.md` and `~/.shepherd/templates/`.
Project tiers ALWAYS override user tiers; user tiers override bundled
plugin defaults.

## Run identity

`{run}` == the sprint slug (e.g. `v641-dev0`); patch-arc runs use the patch
slug (e.g. `v641`). Slugs are generated from
`[branching].sprint_slug_pattern`/`patch_slug_pattern` — NEVER invented ad
hoc. Run and lane identifiers sanitize to `[a-z0-9][a-z0-9-]*`: lowercase,
starts alphanumeric, no `..`, no path separators, no absolute paths. A
directory is a run iff it contains `run.json` (written by `shepherd run
init`) — runs are indexed by `run.json` presence, NEVER by mtime scans.

**Canonical means exactly the pattern's output — nothing appended, nothing
substituted (v6.4.2).** A run id carries NO harness name, NO implementation
name, and NO ordinal suffix. It is exactly the string
`[branching].sprint_slug_pattern` (or `patch_slug_pattern`) produces for the
version/dev-number in scope — not that string plus `-codex`, `-01`,
`-claude`, or any other operator- or agent-chosen decoration. Observed in the
wild: a live run in `FL03/axiom` is directoried as `v039-dev0-codex-01` —
three unauthorized tokens (`codex`, the ordinal `01`, and their separators)
appended to the canonical `v039-dev0` the pattern actually derives.

**Why this is a hard rule, not a style preference.** The bridge contract
(`skills/bridge/SKILL.md`) has multiple shepherd implementations sharing ONE
run and arbitrating write access by custody through `run.json` — not by
each implementation keeping its own directory. A harness- or ordinal-
suffixed run directory silently FORKS the run: instead of two
implementations coordinating over one `{run_dir}`, each computes a
different path and works in parallel isolation, unaware the other exists —
exactly the split the bridge contract exists to prevent. The whole
mechanism depends on one property: two shepherds deriving the slug from the
same version MUST land on the same directory, with no implementation-
specific input anywhere in that derivation. A suffix that identifies which
harness or which parallel attempt created a run breaks that property by
definition, no matter how useful it looks locally.

**It is now mechanized, not just documented (v6.4.2):**
- Derivation is ALWAYS from `[branching].sprint_slug_pattern`/
  `patch_slug_pattern` — never hand-typed, never harness-decorated.
- `shepherd run init` REFUSES to create a run directory whose name isn't
  the canonical slug for the version in scope; a caller passing a
  harness-suffixed or ordinal-suffixed id gets a rejection naming the
  canonical id it should have used instead.
- `shepherd run canonicalize` migrates an existing non-canonical run
  directory (and its `run.json`) onto the canonical path — the fix for a
  run like `FL03/axiom`'s `v039-dev0-codex-01` above, without hand-editing
  paths or losing run history.
- `shctx lint` WARNs on every existing non-canonical run directory it
  finds under `{paths.runs}`, so a violation predating this rule surfaces
  on the next lint pass instead of staying silently forked forever.

## Run layout — `{run_dir}` = `{paths.runs}/{run}`

`[paths].runs` defaults to `.shepherd/runs`. Every run-scoped artifact lives
under its run directory with a FIXED name — the directory carries the run
identity, so filenames inside it take no slug prefix.

| Path | Purpose | Git |
|---|---|---|
| `{run_dir}/run.json` | Machine run state + #242 boundary-merge ledger | ignored |
| `{run_dir}/seed.md` | Sprint/patch seed | tracked |
| `{run_dir}/mesh.md` | Planter mesh report | tracked |
| `{run_dir}/plan.md` | Master implementation plan | tracked |
| `{run_dir}/phase0.md` | Phase-0 mesh report | tracked |
| `{run_dir}/close.md` | Sprint close report | tracked |
| `{run_dir}/handoff.md` | Sprint handoff | tracked |
| `{run_dir}/lanes/{lane}/plan.md` | Lane plan (checkbox steps + append-only `## Deviations`) | tracked |
| `{run_dir}/graph/` | Stage-graph state, trace, compiled workflows | ignored |
| `{run_dir}/dispatch/` | Dispatch records | ignored |
| `{run_dir}/reports/` | Materialized read-only-role reports | ignored |
| `{run_dir}/audits/` | Audit findings | ignored |

The tracked/ignored split is the durable/disposable split: durable knowledge
(seed/mesh/plan/phase0/close/handoff + lane plans) compounds in git; run
state (`run.json`, `graph/`, `dispatch/`, `reports/`, `audits/`) is
disposable. The root `.gitignore` implements it as `.shepherd/runs/**` plus
per-file negations for exactly the tracked set.

## Ownership

| Writer | Writes | Never |
|---|---|---|
| root | `run.json` — VIA `shepherd run …` ONLY, never a direct file write; `close.md`, `handoff.md`; materializes read-only roles' returned reports into `reports/`/`audits/` | `lanes/` internals |
| planter | `seed.md`, `mesh.md` | `plan.md`/`phase0.md`, `run.json` |
| engineer | `plan.md`, `phase0.md` — authored by the engineer, materialized to disk by root (the engineer runs read-only) | `run.json`, `lanes/` |
| conductor | `lanes/{lane}/**` for ITS OWN lane — and NOTHING else in the run dir | top-level run files, sibling lanes |
| coder | its own worktree ONLY | any `{run_dir}` path |

`run.json` is NEVER latent-space-written: `shepherd run init|set|lane|wave`
is the single schema-validated writer, so producer and consumer cannot
diverge. `conductor_write_guard` scopes each conductor to its own
`lanes/{lane}/`.

## Filename patterns

Run-dir files are FIXED names (table above) — a slug-prefixed file inside a
run dir is misplaced. The `<slug>.<group>.<ext>` patterns below remain for
LEGACY trees predating layout v3; `<group>` stays extensible via
`[context.naming].extra_patterns`.

| Pattern | Location | Used for |
|---|---|---|
| `*.seed.md` / `*.plan.md` | `docs/plans/` (legacy) | pre-v3 seeds/plans |
| `*.phase0.md` / `*.close.md` / `*.walk.md` | `docs/reports/` (legacy) | pre-v3 reports |
| `*.handoff.md` | `docs/handoffs/` (legacy) | pre-v3 handoffs |
| `*.spec.md` / `*.design.md` | `docs/specs/` | design specs / documents |
| `YYYY-MM-DD.md` | `docs/journal/` | daily journal |
| `YYYY-MM-DD.log.md` / `.log.jsonl` | `logs/` | daily human/machine log |
| `YYYY-MM-DDTHH-MM-SS.log.jsonl` | `logs/` | sub-daily machine log |

Genuinely cross-run docs stay under `{paths.docs}`: specs
(`docs/specs/YYYY-MM-DD-<topic>-{design|spec}.md`, kebab-case `<topic>`,
unique within the day), journal entries, carry-forwards (`[ledger]`).
Run-scoped docs NEVER land there — they belong in `{run_dir}`.

## Layout (namespace scaffold)

`shepherd.db(+wal/shm/journal)`, `shepherd.lock`, `project.json`, `cache/`,
`logs/`, `tmp/`, and the ignored `runs/` internals — gitignored.

Hook-owned `tmp/` files (per-session, machine-generated, never tracked):
`tmp/session-tier-<session>` (positive session-tier marker the identity-gated
Stop guard reads — #232/#228), `tmp/gates-ran-<session>.jsonl` (the #59
gate-invocation ledger `doctor` reports on), `tmp/gates-extra-warned.<session>`
(close-finalize warn-once flag).
`CONVENTIONS.md`, `archive/`, `ctx/`, `docs/{specs,diagrams}`,
`docs/journal/` (one file per day, append-mode), `profiles/`, `scripts/`,
`templates/`, `types/`, and the tracked `runs/` set — tracked. Legacy
`docs/{plans,reports,handoffs}` and `styles/` remain honored until
`--layout v3` migrates them.

## Date discipline

**Date-only for human-editable, timestamped for machine-generated.**
Date-only: journal entries, human-readable daily logs, daily event-log files
— one file per day, sections use `## HH:MM — <topic>`. Timestamped
(`YYYY-MM-DDTHH-MM-SS.*`): `tmp/*.jsonl` scratch, internal cache writes,
sub-daily log granularity. Timestamped human files fragment context across N
files/day; date-only machine files clobber on rapid succession — the split
keeps both regimes coherent.

## Profiles and styles

A style profile is a DIRECTORY: `profiles/{profile}/style.md`, where
`{profile}` is usually a language (`rust`, `python`, `typescript`, `go`,
`shell`, `sql`) but the shape is general (future siblings:
`instructions.md`, tool configs). Resolution, first hit wins:

1. project `<ns>/profiles/{profile}/style.md`
2. project legacy `<ns>/styles/{profile}.md` (pre-v6.4.1 flat layout;
   `shepherd migrate --layout v3` moves it)
3. user `~/.shepherd/profiles/{profile}/style.md` (`SHEPHERD_HOME` honored)
4. bundled `${CLAUDE_PLUGIN_ROOT}/skills/context/styles/{profile}.md`

Writes ALWAYS target tier 1 — the chain is read-side only, so a project
edit can never silently land in the user or bundled tier. TOML
behavior-overlay profiles (`profiles/<name>.toml`, basename matching the
internal `name=` field — see `references/profiles.md`) coexist beside the
style-profile directories under `<ns>/profiles/`. The SQLite file is
`shepherd.db`; legacy `root.db` is honored automatically.

## `shctx lint` checks

Misnamed file (extension/stem matches no pattern); Misplaced file (pattern
matches, wrong directory — including a slug-prefixed file inside a run dir);
Date-only-vs-timestamped violation; Orphan (DB row → missing file, and the
inverse). Exit 0 clean; non-zero with a diagnostic count otherwise.

## Configuration overrides

```toml
[context.naming]
strict = true                                    # fail status on lint violations
extra_patterns = ["*.bench.md", "*.flame.svg"]   # additional accepted patterns
ignore_paths = ["legacy/"]                       # skip these subtrees
```

See `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` for the full schema.
