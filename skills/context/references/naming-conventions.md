# Naming conventions — per-project namespace

Shepherd v5.0.0 enforces strict file-naming patterns under the per-project namespace directory. `shctx lint` runs the check; misnamed files surface as findings. Configuration knobs live in `[context.naming]` of `.claude/shepherd.toml`.

## Namespace selection — `.shepherd/` default, `.artifacts/` opt-in

The namespace directory is **`.shepherd/` by default** in v5.0.0. Projects that prefer the legacy `.artifacts/` layout can opt in by running `shctx init --artifacts`. Auto-detection runs at every CLI invocation: if either `.shepherd/` or `.artifacts/` already exists in the repo root, the existing one is used (preferring `.shepherd/` if both exist). When neither exists and no flag is passed, `init` scaffolds `.shepherd/`.

**Conflict guard (v5.0.9):** `shctx init` refuses to create a new namespace directory when the *other* namespace is already an initialized shctx workspace (detected by the presence of the shctx `.gitignore` marker). This prevents the split-brain that occurs when shctx data lands in one namespace while `shepherd.toml [paths]` entries reference the other. If both directories are ever found to coexist, `shctx_artifacts_root()` emits a warning and `shctx doctor` surfaces a `WARN` check with remediation steps.

Throughout the rest of this document, paths shown as `.artifacts/` apply identically to `.shepherd/` for projects on the new default — substitute the active namespace name.

The same table is mirrored to `<namespace>/CONVENTIONS.md` on `shctx init` for quick local reference inside the consumer project.

---

## Filesystem layout (recap)

```
.artifacts/
  root.db                       # SQLite registry (gitignored by default)
  shepherd.lock                 # JSON lock file (gitignored)
  CONVENTIONS.md                # auto-scaffolded; documents naming rules
  project.json                  # { "id": "<UUIDv7>", "scaffolded_at": <epoch> }
  ctx/                          # markdown knowledge silo
  plans/                        # *.plan.md, *.seed.md
  reports/                      # *.phase0.md, *.close.md, *.walk.md
  docs/
    handoffs/                   # *.handoff.md
    specs/                      # *.spec.md, *.design.md
    diagrams/                   # *.svg, *.png, *.dot
    journal/                    # YYYY-MM-DD.md (one file per day, append-mode)
  logs/                         # events-YYYY-MM-DD.jsonl (append-only)
  tmp/                          # *.jsonl scratch (cleared on init / age-out)
  profiles/                     # *.toml profile defs (sync into profiles_defs)
  styles/                       # <lang>.md per-language code-style files (addendum §A2)
```

---

## Pattern table (spec §4 — verbatim)

| Pattern | Used for |
|---|---|
| `*.seed.md` | Sprint or patch seeds |
| `*.plan.md` | Sprint plans |
| `*.phase0.md` | Phase 0 mesh reports |
| `*.close.md` | Sprint close reports |
| `*.walk.md` | Stage Graph walk traces |
| `*.handoff.md` | Sprint handoff docs |
| `*.spec.md` | Design specs (after brainstorming) |
| `*.design.md` | Design documents |
| `YYYY-MM-DD.md` | Daily journal entries (in `docs/journal/`) — one file per day, sections within for multiple events |
| `events-YYYY-MM-DD.jsonl` | Daily event log (in `logs/`) — append-only |

---

## Date discipline

**Date-only filenames** (`YYYY-MM-DD`) for **human-editable** artifacts:

- Journal entries (`docs/journal/YYYY-MM-DD.md`) — one file per day; sections within use `## HH:MM — <topic>` headings.
- Daily reports.
- Daily event-log files (`logs/events-YYYY-MM-DD.jsonl`).

**Timestamped filenames** (`YYYY-MM-DDTHH-MM-SS.*`) reserved for **machine-generated** ephemerals:

- `tmp/*.jsonl` scratch.
- Internal cache writes.
- Per-event log files where granularity below daily is required.

The rule, summarized: **date-only for human-editable, timestamped for machine-generated.**

Why: timestamped human files fragment context across N files per day. Date-only machine files clobber on rapid succession. The split keeps both regimes coherent.

---

## Sprint-branch prefixing

Many of the patterns above pair with a sprint identifier. Conventions:

- `plans/{sprint_slug}.plan.md` — e.g. `plans/v5.0.0-dev.0.plan.md`.
- `plans/{sprint_slug}.seed.md`.
- `reports/<date>-{sprint_branch}-close.md` — e.g. `reports/2026-05-04-v5.0.0-dev.0-close.md`.
- `reports/<date>-{sprint_branch}-walk.md`.
- `reports/<date>-{sprint_branch}-phase0.md`.
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
