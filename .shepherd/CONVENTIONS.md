# Naming conventions — `.shepherd/` (quick reference)

Scaffolded mirror for in-project reference. The CANONICAL artifact schema —
full layout, ownership table, id grammar, git split — lives at
`skills/context/references/naming-conventions.md` in the shepherd plugin;
`shepherd lint` enforces it. This mirror summarizes the v6.5.0 shape.

## Layout

```
.shepherd/
  shepherd.db*  shepherd.lock  project.json     # gitignored runtime
  ctx/                                          # cross-run knowledge silo
  docs/{handoffs,specs,diagrams,journal}/       # cross-run documents
  profiles/{profile}/style.md                   # per-profile style + instructions
  templates/                                    # project Jinja2 template overrides
  runs/{run}/                                   # ALL run-scoped artifacts
    run.json                                    # CLI-written state (gitignored)
    seed.md  mesh.md  plan.md  phase0.md        # tracked
    close.md  handoff.md                        # tracked
    lanes/{lane}/plan.md                        # tracked, conductor-owned
    graph/  dispatch/  reports/  audits/        # gitignored run state
  cache/  logs/  tmp/                           # gitignored
```

## Rules

- `{run}` == sprint slug (`v650-dev0`) or patch slug (`v650`); identifiers
  are `[a-z0-9][a-z0-9-]*` — no path separators, no `..`, never absolute.
- `run.json` is written ONLY via `shepherd run …` (schema-validated,
  atomic); never hand-authored.
- Filenames inside a run dir are FIXED (no slug/date prefixes — the run
  dir carries identity). Date-prefixed names remain for cross-run docs
  under `docs/` (date-only for human-editable, timestamped for
  machine-generated).
- Profiles resolve project → user (`~/.shepherd/profiles/`) → bundled;
  writes always target the project tier.
