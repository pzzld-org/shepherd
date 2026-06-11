# Naming conventions — per-project namespace

Shepherd v5.0.0 enforces strict file-naming patterns under the per-project namespace directory. `shctx lint` runs the check; misnamed files surface as findings. Configuration knobs live in `[context.naming]` of `.claude/shepherd.toml`.

## Namespace selection — `.shepherd/` default, `.artifacts/` opt-in

The namespace directory is **`.shepherd/` by default** in v5.0.0. Projects that prefer the legacy `.artifacts/` layout can opt in by running `shctx init --artifacts`. Auto-detection runs at every CLI invocation: if either `.shepherd/` or `.artifacts/` already exists in the repo root, the existing one is used (preferring `.shepherd/` if both exist). When neither exists and no flag is passed, `init` scaffolds `.shepherd/`.

**Conflict guard (v5.0.9):** `shctx init` refuses to create a new namespace directory when the *other* namespace is already an initialized shctx workspace (detected by the presence of the shctx `.gitignore` marker). This prevents the split-brain that occurs when shctx data lands in one namespace while `shepherd.toml [paths]` entries reference the other. If both directories are ever found to coexist, `shctx_artifacts_root()` emits a warning and `shctx doctor` surfaces a `WARN` check with remediation steps.

Throughout the rest of this document, paths shown as `.artifacts/` apply identically to `.shepherd/` for projects on the new default — substitute the active namespace name.

The same table is mirrored to `<namespace>/CONVENTIONS.md` on `shctx init` for quick local reference inside the consumer project.

---

## Filesystem layout (recap)

Standard layout scaffolded by `shctx init` for **new projects** (v6.1.0+):

```
${SHEPHERD_WORKDIR}/              # .shepherd/ by default; .artifacts/ for legacy opt-in
  shepherd.db (+ -wal/-shm/-journal)   # SQLite registry (gitignored)
  shepherd.lock                   # JSON lock file (gitignored)
  project.json                    # { "id": "<UUIDv7>", "scaffolded_at": <epoch> } (gitignored)
  toolkit.json                    # tool registry (TRACKED)
  CONVENTIONS.md                  # auto-scaffolded; documents naming rules
  .gitignore                      # auto-scaffolded
  archive/                        # retired artifacts (tracked)
  cache/                          # ephemeral caches (gitignored)
  ctx/                            # markdown knowledge silo (tracked)
  docs/
    plans/                        # *.plan.md, *.seed.md (tracked)
    reports/                      # *.phase0.md, *.close.md, *.walk.md (tracked)
    handoffs/                     # *.handoff.md (tracked)
    specs/                        # *.spec.md, *.design.md (tracked)
    diagrams/                     # *.svg, *.png, *.dot (tracked)
    journal/                      # YYYY-MM-DD.md (one file per day, append-mode; tracked)
  logs/                           # {date}.log.jsonl + hooks/ (gitignored)
  profiles/                       # *.toml profile defs (tracked)
  scripts/                        # project-local scripts (tracked)
  styles/                         # <lang>.md per-language code-style files (tracked)
  templates/                      # project-local templates (tracked)
  tmp/                            # scratch (gitignored)
  types/                          # JSON schemas / type defs (tracked)
```

### Back-compatibility

Legacy projects using **`.artifacts/`**, **`root.db`**, and **top-level `plans/`+`reports/`** are fully supported and auto-detected — no action required. The resolver (`resolve_workdir`) checks `SHEPHERD_WORKDIR` → `SHCTX_ROOT_OVERRIDE` → existing `.shepherd/` → existing `.artifacts/` → defaults to `.shepherd/`. The DB resolver (`shctx_db_path`) checks for `shepherd.db` first, then falls back to `root.db` when it already exists; new projects default to `shepherd.db`.

To opt into the new layout:

```bash
shctx migrate --layout v2
```

This moves `plans/*` → `docs/plans/`, `reports/*` → `docs/reports/`, renames `root.db*` → `shepherd.db*`, and creates the new directories. It is safe, idempotent, and re-runnable — it never clobbers existing destination files.

---

## Pattern table (spec §4)

Artifact filenames follow the convention `<slug>.<group>.<ext>` where `<slug>` is a sprint identifier or date, `<group>` is a semantic type tag, and `<ext>` is the file extension. The same convention that seeds and plans already use (e.g. `v512-dev3.seed.md`) applies uniformly.

`<group>` ∈ {`seed`, `plan`, `phase0`, `close`, `walk`, `handoff`, `spec`, `design`, `log`, ...} — extensible via `[context.naming].extra_patterns`.

| Pattern | Location | Used for |
|---|---|---|
| `*.seed.md` | `docs/plans/` (new) / `plans/` (legacy) | Sprint or patch seeds |
| `*.plan.md` | `docs/plans/` (new) / `plans/` (legacy) | Sprint plans |
| `*.phase0.md` | `docs/reports/` (new) / `reports/` (legacy) | Phase 0 mesh reports |
| `*.close.md` | `docs/reports/` (new) / `reports/` (legacy) | Sprint close reports |
| `*.walk.md` | `docs/reports/` (new) / `reports/` (legacy) | Stage Graph walk traces |
| `*.handoff.md` | `docs/handoffs/` | Sprint handoff docs |
| `*.spec.md` | `docs/specs/` | Design specs (after brainstorming) |
| `*.design.md` | `docs/specs/` | Design documents |
| `YYYY-MM-DD.md` | `docs/journal/` | Daily journal entries — one file per day, sections within for multiple events |
| `events-YYYY-MM-DD.jsonl` | `logs/` | Legacy daily event log — append-only |
| `YYYY-MM-DD.log.md` | `logs/` | Human-readable daily log (new; `<group>=log`) |
| `YYYY-MM-DD.log.jsonl` | `logs/` | Machine event stream, date-granularity (new) |
| `YYYY-MM-DDTHH-MM-SS.log.jsonl` | `logs/` | Machine event stream, timestamp-granularity (new) |

---

## Date discipline

**Date-only filenames** (`YYYY-MM-DD`) for **human-editable** artifacts:

- Journal entries (`docs/journal/YYYY-MM-DD.md`) — one file per day; sections within use `## HH:MM — <topic>` headings.
- Human-readable daily logs (`logs/YYYY-MM-DD.log.md`).
- Daily event-log files (`logs/events-YYYY-MM-DD.jsonl` legacy; `logs/YYYY-MM-DD.log.jsonl` new).

**Timestamped filenames** (`YYYY-MM-DDTHH-MM-SS.*`) reserved for **machine-generated** ephemerals:

- `tmp/*.jsonl` scratch.
- Internal cache writes.
- Per-event log files where granularity below daily is required (`logs/YYYY-MM-DDTHH-MM-SS.log.jsonl`).

The rule, summarized: **date-only for human-editable, timestamped for machine-generated.**

Why: timestamped human files fragment context across N files per day. Date-only machine files clobber on rapid succession. The split keeps both regimes coherent.

---

## Sprint-branch prefixing

Many of the patterns above pair with a sprint identifier. Conventions:

- `docs/plans/{sprint_slug}.plan.md` — e.g. `docs/plans/v5.0.0-dev.0.plan.md` (new). Legacy: `plans/{sprint_slug}.plan.md`.
- `docs/plans/{sprint_slug}.seed.md` (new). Legacy: `plans/{sprint_slug}.seed.md`.
- `docs/reports/<date>-{sprint_branch}-close.md` — e.g. `docs/reports/2026-05-04-v5.0.0-dev.0-close.md` (new). Legacy: `reports/<date>-{sprint_branch}-close.md`.
- `docs/reports/<date>-{sprint_branch}-walk.md` (new). Legacy: `reports/<date>-{sprint_branch}-walk.md`.
- `docs/reports/<date>-{sprint_branch}-phase0.md` (new). Legacy: `reports/<date>-{sprint_branch}-phase0.md`.
- `docs/handoffs/<date>-dev{N}-close-handoff.md`.

`{sprint_branch}` resolves from `[branching].sprint_branch_pattern`. `<date>` is `YYYY-MM-DD` of the report's authoring day.

---

## Spec/design discipline

Specs live in `docs/specs/` with the form `YYYY-MM-DD-<topic>-{design|spec}.md`:

- `2026-05-04-shepherd-context-design.md` — design document (architecture, schema).
- `2026-05-04-shepherd-context-addendum.md` — operator follow-ups against an approved design.
- A future implementation spec would be `2026-05-04-shepherd-context.spec.md` (RFC-shaped, post-brainstorming).

The `<topic>` slug is kebab-case, descriptive, and unique within the day.

---

## Profile and style files

- `profiles/<name>.toml` — basename matches the `name = "..."` field inside the file.
- `styles/<lang>.md` — `<lang>` is the language slug (e.g. `rust`, `python`, `typescript`, `go`, `shell`, `sql`). Per addendum §A2; bundled defaults under `${CLAUDE_PLUGIN_ROOT}/skills/context/styles/`.

## SQLite registry filename

The database file is **`shepherd.db`** in v6.1.0+ (new projects and migrated projects). Legacy projects using `root.db` are honored automatically — `shctx_db_path()` detects whichever file exists (preferring `shepherd.db`). Run `shctx migrate --layout v2` to rename `root.db` → `shepherd.db` on an existing project.

---

## Lint behavior

`shctx lint` walks the active namespace directory and reports:

- **Misnamed file** — extension or stem doesn't match any pattern.
- **Misplaced file** — pattern matches but directory is wrong (e.g. `*.plan.md` outside `plans/`).
- **Date-only-vs-timestamped violation** — timestamp detected on a human-editable path, or vice versa.
- **Orphan** — `artifacts` table row with `path` pointing at a missing file (and the inverse: file present, no DB row).

Exit code 0 if clean; non-zero with a diagnostic count otherwise. Lint runs as part of `shctx status` summary; explicit `shctx lint` runs the full check with verbose output.

---

## Configuration overrides

Override defaults via `[context.naming]` in `.claude/shepherd.toml`:

```toml
[context.naming]
strict = true                                    # fail status on lint violations
extra_patterns = ["*.bench.md", "*.flame.svg"]   # additional accepted patterns
ignore_paths = ["legacy/"]                       # skip these subtrees
```

See `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` for the full schema.
