# Naming conventions — per-project namespace

`shctx lint` enforces file-naming and directory-layout patterns under the
per-project namespace. Overrides live in `[context.naming]` of
`.claude/shepherd.toml`.

## Namespace selection

**`.shepherd/` is the default.** `.artifacts/` is legacy, opt in via `shctx
init --artifacts`. Auto-detection: whichever of `.shepherd/`/`.artifacts/`
already exists in the repo root wins (preferring `.shepherd/` if both exist).

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
default to `shepherd.db`. `shctx migrate --layout v2` moves `plans/*` →
`docs/plans/`, `reports/*` → `docs/reports/`, renames `root.db*` →
`shepherd.db*` — idempotent, never clobbers existing destination files.

## Layout (new-project scaffold)

`shepherd.db(+wal/shm/journal)`, `shepherd.lock`, `project.json` — gitignored.
`toolkit.json`, `CONVENTIONS.md`, `archive/`, `ctx/`, `docs/{plans,reports,
handoffs,specs,diagrams}`, `docs/journal/` (one file per day, append-mode),
`profiles/`, `scripts/`, `styles/`, `templates/`, `types/` — tracked.
`cache/`, `logs/`, `tmp/` — gitignored.

## Filename patterns (`<slug>.<group>.<ext>`)

`<group>` extensible via `[context.naming].extra_patterns`.

| Pattern | Location | Used for |
|---|---|---|
| `*.seed.md` | `docs/plans/` | Sprint/patch seeds |
| `*.plan.md` | `docs/plans/` | Sprint plans |
| `*.phase0.md` | `docs/reports/` | Phase 0 mesh reports |
| `*.close.md` | `docs/reports/` | Sprint close reports |
| `*.walk.md` | `docs/reports/` | Stage Graph walk traces |
| `*.handoff.md` | `docs/handoffs/` | Sprint handoff docs |
| `*.spec.md` / `*.design.md` | `docs/specs/` | Design specs / documents |
| `YYYY-MM-DD.md` | `docs/journal/` | Daily journal |
| `YYYY-MM-DD.log.md` / `.log.jsonl` | `logs/` | Daily human/machine log |
| `YYYY-MM-DDTHH-MM-SS.log.jsonl` | `logs/` | Sub-daily machine log |

Legacy equivalents drop the `docs/` prefix (`plans/`, `reports/`).

## Date discipline

**Date-only for human-editable, timestamped for machine-generated.**
Date-only: journal entries, human-readable daily logs, daily event-log files
— one file per day, sections use `## HH:MM — <topic>`. Timestamped
(`YYYY-MM-DDTHH-MM-SS.*`): `tmp/*.jsonl` scratch, internal cache writes,
sub-daily log granularity. Timestamped human files fragment context across N
files/day; date-only machine files clobber on rapid succession — the split
keeps both regimes coherent.

## Sprint-branch and spec naming

`docs/plans/{sprint_slug}.plan.md` / `.seed.md`;
`docs/reports/<date>-{sprint_branch}-{close|walk|phase0}.md`;
`docs/handoffs/<date>-dev{N}-close-handoff.md`. `{sprint_branch}` resolves
from `[branching].sprint_branch_pattern`; `<date>` is the report's authoring
day. Specs: `docs/specs/YYYY-MM-DD-<topic>-{design|spec}.md`, kebab-case
`<topic>`, unique within the day.

## Profile, style, and DB filenames

`profiles/<name>.toml` (basename matches the internal `name=` field).
`styles/<lang>.md` — `<lang>` ∈ `{rust, python, typescript, go, shell, sql}`,
bundled under `${CLAUDE_PLUGIN_ROOT}/skills/context/styles/`. The SQLite file
is `shepherd.db`; legacy `root.db` is honored automatically.

## `shctx lint` checks

Misnamed file (extension/stem matches no pattern); Misplaced file (pattern
matches, wrong directory); Date-only-vs-timestamped violation; Orphan (DB row
→ missing file, and the inverse). Exit 0 clean; non-zero with a diagnostic
count otherwise.

## Configuration overrides

```toml
[context.naming]
strict = true                                    # fail status on lint violations
extra_patterns = ["*.bench.md", "*.flame.svg"]   # additional accepted patterns
ignore_paths = ["legacy/"]                       # skip these subtrees
```

See `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` for the full schema.
