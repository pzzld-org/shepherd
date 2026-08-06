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
`styles/<lang>.md` → `profiles/<lang>/style.md`; `--layout v4` moves
`memory/snapshots/*` → `cache/snapshots/` and `memory/*.md` → `ctx/` — every
layout migration is idempotent and never clobbers existing destination files.

## One knowledge silo

**`ctx/` is the ONLY knowledge silo. `cache/` is the ONLY disposable-machine-
state directory. `memory/` is RETIRED (v6.4.4) and `shepherd lint` FAILs if it
exists.**

Until v6.4.4 the namespace carried two directories that read as the same
thing. `ctx/` was documented as the cross-run knowledge silo and is tracked.
`memory/` was created by `precompact_snapshot.sh` for one narrow purpose —
`memory/snapshots/precompact-*.json`, disposable rehydration state — and was
gitignored to keep that churn out of `git status`. It appeared in no `[paths]`
key and in no table in this document.

Two directories, one obvious meaning between them, and the wrong one is
ignored. The predictable thing happened: `FL03/axiom`'s `.shepherd/memory/`
holds three hand-authored markdown files (`project_v023_dev5_carryforwards.md`
and two `feedback_*.md`), none of them tracked. Carry-forwards and feedback are
`ctx/` content by definition — `ctx/` in that same repo holds
`failure-patterns-ledger.md`, `dedup-ledger.md`, `wiring-ledger.md`. An
operator wrote durable knowledge into the directory named "memory", which is
the correct instinct and the wrong directory, and git dropped all of it. The
defect is not that someone filed a note wrong; it is that the layout offered
two plausible destinations and silently punished the wrong choice.

The split is by LIFETIME, and it is the same split the run layout already
uses (durable tracked / disposable ignored):

| Directory | Holds | Lifetime | Git |
|---|---|---|---|
| `ctx/` | Cross-run knowledge: ledgers, carry-forwards, audits, type maps | Durable — compounds across runs | tracked |
| `cache/` | Machine state: precompact snapshots, resolver caches | Disposable — safe to delete any time | ignored |

Neither `.gitignore` carries a `memory/` rule any more. That is deliberate:
ignoring it is what made it a silent sink, so a stray `memory/` now shows up in
`git status` and fails `shepherd lint` instead of swallowing files. The fix is
one idempotent command — `shepherd migrate --layout v4`.

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
| `{run_dir}/reports/discovery-<id>.md` | @discovery report (`DISCOVERY-WRITE-PATH`) | ignored |
| `{run_dir}/reports/<deliverable-slug>.md` | @worker deliverable report | ignored |
| `{run_dir}/reports/partial-close.md` | Early-close open-items report | ignored |
| `{run_dir}/audits/audit-<concern>.md` | @auditor close-mode findings (`AUDITOR-WRITE-PATH`) | ignored |
| `{run_dir}/audits/intro-audit-<concern>.md` | @auditor intro-mode findings | ignored |
| `{run_dir}/audits/audit-wave-review-<lane>-w<N>.md` | @auditor wave-review verdict | ignored |

**Run-scoped artifacts are NEVER ledgered under `{paths.docs}` (v6.4.4).**
`reports/` and `audits/` have been in this table since v6.4.1 and `run init`
scaffolds both, but every writer was still pinned to `{paths.reports}` =
`.shepherd/docs/reports/` with a `<date>-` prefix — the agent bodies
(`auditor.md`, `discovery.md`, `worker.md`), `flock.md`, and `lock_guard.sh`'s
`AUDITOR-WRITE-PATH`/`DISCOVERY-WRITE-PATH` regexes alike. So the run-scoped
directories stayed empty while a run's own audits and discovery reports piled
into the CROSS-RUN docs tree: `FL03/axiom` has 1548 files in
`.shepherd/docs/reports/` and one run directory. Doctrine said one thing, every
writer did another, and nothing reconciled them. All three layers now name the
run-scoped path, and the guard DENIES the legacy target with a message that
names the correct one.

Filenames in these sub-directories carry NO date prefix — the run directory
already carries the identity, exactly as for the fixed top-level run files. The
discriminator is the concern / discovery id / lane+wave, which is what actually
distinguishes two artifacts within one run; a date does not (a run produces
many audits on the same day).

The tracked/ignored split is the durable/disposable split: durable knowledge
(seed/mesh/plan/phase0/close/handoff + lane plans) compounds in git; run
state (`run.json`, `graph/`, `dispatch/`, `reports/`, `audits/`) is
disposable. The root `.gitignore` implements it as `.shepherd/runs/**` plus
per-file negations for exactly the tracked set. **`runs/` is deliberately NOT
ignored wholesale** — a run's seed, plan, and lane plans ARE the project's
plans and belong in history; only the disposable state around them is not.

**The layout is SCAFFOLDED, never emergent (v6.4.3).** `shepherd run init`
creates every directory in the table above — `lanes/`, `graph/`, `dispatch/`,
`reports/`, `audits/` — so a run has the identical shape from the moment it
exists, whoever created it. Until v6.4.3 only `lanes/` was scaffolded and the
rest materialized as a side effect of activity, so "does this run have a
`reports/`" answered *did this sprint dispatch a read-only role*, not *is this
a run* — a layout that appears only when used is a layout nothing downstream
can rely on. `shepherd run layout <run>` verifies a run against the table
(read-only, exit 6 on drift); `--repair` creates what is missing.
`RUN_SUBDIRS`/`RUN_TRACKED_FILES` in `shepherd_cli.models_run` are the single
source of truth both the scaffold and the check read, so the code and this
table cannot drift apart.

**The run directory is created FIRST, by the planter.** `/shepherd:plant`
runs `shepherd run init {run}` before writing anything, so `{run_dir}` exists
with its full layout and the seed lands into it rather than the directory
appearing underneath the seed. The run dir then carries forward untouched
into the `/shepherd:spawn` session — same `{run}`, same paths, no
re-derivation and no second directory (`commands/plant.md §Artifacts`,
`agents/planter.md §Plant mode`).

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

### The `docs/` vs `{run_dir}` boundary

One question decides it: **would this artifact still be worth reading if the
run it came from were deleted?** Yes → cross-run, `docs/`. No → run-scoped,
`{run_dir}`. Nothing sits in both.

| Cross-run → `{paths.docs}` | Run-scoped → `{run_dir}` |
|---|---|
| Specs / design docs (`docs/specs/YYYY-MM-DD-<topic>-{design\|spec}.md`, kebab-case `<topic>`, unique within the day) | Seed, mesh, plan, phase0, close, handoff |
| Journal entries (`docs/journal/YYYY-MM-DD.md`) | Lane plans |
| Diagrams (`docs/diagrams/`) | Audits (`audits/`), discovery + worker reports (`reports/`) |
| The carry-forward ledger (`[ledger]`) | Dispatch records, stage-graph state |

A spec describes a design that outlives its sprint, so it is cross-run even
when a single sprint prompted it. An audit grades one run's work and is
meaningless detached from it, so it is run-scoped even though it reads like a
document. Getting this backwards produces exactly the two failures v6.4.4
fixed: run reports ledgered into `docs/` (see §Run layout), and run
directories named like specs (see §Run identity).

A cross-run doc NEVER lands in `{run_dir}`, and a run-scoped artifact NEVER
lands in `docs/`. `shctx lint`'s misplaced-file check enforces both directions.

## Layout (namespace scaffold)

`shepherd.db(+wal/shm/journal)`, `shepherd.lock`, `project.json`, `cache/`,
`logs/`, `tmp/`, and the ignored `runs/` internals — gitignored.

`cache/snapshots/precompact-<session>-<epoch>.json` holds the PreCompact
snapshots `precompact_snapshot.sh` writes and `focus_rehydrate.sh` reads back
after a compaction; `[compaction].snapshot_retention` bounds the directory and
`shepherd prune` enforces it. They lived under `memory/snapshots/` from v6.1.3
to v6.4.3 — see §One knowledge silo. Both retired locations (`memory/snapshots/`
and pre-v6.1.3 top-level `snapshots/`) are still READ, so a snapshot taken
immediately before an upgrade still rehydrates; the reader picks the newest
snapshot across all three rather than the first directory that exists, so a
leftover retired directory can never shadow a fresh snapshot.

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
