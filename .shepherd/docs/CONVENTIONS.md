# Shepherd layout v5

This file is the project-local filesystem contract. The typed Rust loader,
registry, run store, and migration planner enforce the same shape. Harness
adapters consume it; they do not create a second namespace.

## Project namespace

```text
.shepherd/
  shepherd.toml                 # tracked project configuration
  shepherd.local.toml           # ignored machine-only override, optional
  shepherd.<harness>.toml       # tracked harness overlay, optional
  project.json                  # stable project identity
  shepherd.db*                  # native registry state, ignored
  shepherd.lock                 # native writer lock, ignored
  ctx/                          # structured cross-run context
  docs/                         # flat cross-run documents
  templates/                    # project-owned template overrides
  runs/<run>/                   # every artifact owned by one run
    run.json
    seed.md
    mesh.md
    plan.md
    handoff.md
    close.md
    lanes/<lane>/plan.md
    dispatch/
    reports/
    audits/
    events/
    snapshots/
    fixtures/
```

`~/.shepherd/` is a separate user-default tier. It may contain direct canonical
`shepherd*.toml` files. It never contains a project registry, project context,
run ledger, copied project artifact, style profile, or template fallback.

## Ownership rules

- A run id is a validated lower-case slug. The directory name is its identity.
- A seed, mesh, plan, lane plan, dispatch record, report, audit, event,
  snapshot, fixture, handoff, or close record belongs only under its associated
  `runs/<run>/` directory.
- `docs/` is flat and cross-run. Date or topic prefixes may disambiguate names,
  but nested `docs/specs`, `docs/reports`, `docs/handoffs`, and similar trees
  are retired.
- `ctx/` holds durable cross-run structured context. It is not a second run
  artifact store.
- `run.json`, dispatch identity, and registry mutations are written through the
  native `shepherd` CLI using validated, atomic, no-follow boundaries. Adapters
  never invent another ledger.
- Generated harness carriers are compiler output identified by
  `.shepherd-generated.json`. Authored roles and skills have one source under
  `content/`; generated files are not edited by hand.
- Symlinks are rejected at state and publication boundaries. A configured path
  must remain inside the project `.shepherd/` namespace.

## Retired roots

Do not recreate `memory/`, `cache/`, `logs/`, `tmp/`, `archive/`, `scripts/`,
`types/`, `profiles/`, `styles/`, user-home `templates/`,
`dispatcher-patches/`, branch-keyed `dispatch/`, nested `docs/`, or a second
CLI/runtime tree. Migration may read a legacy root only long enough to snapshot
and deterministically assign or retire its contents under explicit confirmation.
