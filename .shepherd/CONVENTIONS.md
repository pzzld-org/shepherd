# Naming conventions — `.shepherd/` (quick reference)

Scaffolded mirror for in-project reference. The CANONICAL artifact schema —
full layout, ownership table, id grammar, git split — lives at
`skills/context/references/naming-conventions.md` in the shepherd plugin;
`shepherd lint` enforces it. This mirror summarizes the v6.4.4 shape.

## Layout

```
.shepherd/
  shepherd.db*  shepherd.lock  project.json     # gitignored runtime
  ctx/                                          # THE knowledge silo — tracked
  docs/{specs,diagrams,journal}/                # cross-run documents — tracked
  profiles/{profile}/style.md                   # per-profile style + instructions
  templates/                                    # project Jinja2 template overrides
  runs/{run}/                                   # ALL run-scoped artifacts
    run.json                                    # CLI-written state (gitignored)
    seed.md  mesh.md  plan.md  phase0.md        # tracked
    close.md  handoff.md                        # tracked
    lanes/{lane}/plan.md                        # tracked, conductor-owned
    graph/  dispatch/  reports/  audits/        # gitignored run state
  cache/  logs/  tmp/                           # gitignored machine state
                                                # cache/snapshots/ = precompact
```

There is no `memory/`. It is RETIRED (v6.4.4) — `ctx/` is the one knowledge
silo, `cache/` the one disposable-state dir. `shepherd lint` FAILs if
`memory/` exists; `shepherd migrate --layout v4` drains it.

## Rules

- `{run}` == sprint slug (`v641-dev0`) or patch slug (`v641`); identifiers
  are `[a-z0-9][a-z0-9-]*` — no path separators, no `..`, never absolute.
  A date-topic name (`2026-05-20-v517-canonical-state`) is a SPEC name, not
  a run id — a run directory wearing one makes `runs/` read as a second
  `docs/specs/`.
- `run.json` is written ONLY via `shepherd run …` (schema-validated,
  atomic); never hand-authored.
- Filenames inside a run dir are FIXED (no slug/date prefixes — the run
  dir carries identity). Date-prefixed names remain for cross-run docs
  under `docs/` (date-only for human-editable, timestamped for
  machine-generated).
- **Run-scoped, so it lives in `{run_dir}`:** audits (`audits/`), discovery
  and worker reports (`reports/`), the handoff (`handoff.md`), the close
  report (`close.md`). **Cross-run, so it lives in `docs/`:** specs,
  diagrams, the journal. Nothing run-scoped is ledgered under `docs/`.
- Profiles resolve project → user (`~/.shepherd/profiles/`) → bundled;
  writes always target the project tier.
