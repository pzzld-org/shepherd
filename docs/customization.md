# Customization

Shepherd's engine, WIT contract, guard corpus, and layout are release-owned.
Customize a project through its canonical configuration and authored content,
not by forking an adapter or adding a command implementation.

## Project doctrines

Project-only rules belong to the project. A common layout is:

```text
your-project/
  .claude/doctrines/             # project-owned source, if Claude is used
    security.md
    data-invariants.md
  .shepherd/shepherd.toml
```

Keep each doctrine bounded and avoid copying the same rule into `content/roles`,
`content/skills`, and a run brief. The native content compiler enforces the
per-surface limits; the project owns the meaning. The old `[memory]` table is a
layout-migration input only and is not a v6.5.1 configuration surface.

Do not place project doctrine in `~/.shepherd` unless it is intentionally a
user-wide default. Do not place run-specific decisions in a cross-run doctrine.
Seeds, plans, findings, and handoffs belong under `.shepherd/runs/<run>/`.

## Branch and release model

The `[branching]` table controls project branch and slug patterns. The defaults
are suitable for a patch branch with sprint branches beneath it:

```toml
[branching]
patch_branch_pattern = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
patch_slug_pattern = "v{X}{Y}{Z}"
sprint_slug_pattern = "v{X}{Y}{Z}-dev{N}"
sprints_per_patch = 10
main_branch = "main"
release_tag_pattern = "v{X}.{Y}.{Z}"
allow_direct_main_commit = false
```

Changing this table changes naming and lifecycle expectations. Keep the run
slug grammar stable within a sprint so every harness can resume the same
directory.

## Skills and project templates

Use `[skills.mandatory]`, `[skills.by_domain]`, and `[skills.detection]` to
compose local skills. A skill should explain one repeatable method and point to
a reference for detail. Project-owned render templates may live under
`.shepherd/templates/`; the native `render` command never falls back to a user
template directory.

Filesystem style profiles are retired. They had no native reader and created a
second policy authority beside `content/` and the configured skill set. Put a
repeatable language method in one bounded skill, gate it through `[gates]`, and
keep project-only explanatory prose in the flat `.shepherd/docs/` root.

## Harness-specific additions

Claude, Codex, and Pi may have host-specific metadata, but it must remain at the
adapter boundary:

- Claude hook response names stay in `@pzzld/pi-claude`.
- Codex hook response names stay in `@pzzld/pi-codex`.
- Pi provider discovery stays in `@pzzld/pi-shepherd` and its
  `shepherd.pi.json` contract.

The component receives typed, host-neutral records. Do not add a harness branch
to guard policy, content parsing, identity normalization, or run-state logic.

## Adding a language or domain

1. Add or install a focused skill.
2. Add its domain mapping and file patterns in project configuration.
3. Keep the language-specific gate commands in `[gates]`.
4. Run `shepherd compile --check` and the native gate.

The core language enum supports Rust, Python, TypeScript, Go, mixed, and
Markdown projects. Adding a skill does not require a new CLI or a new compiler.

## See also

- [Configuration](configuration.md) for the typed schema and layout-v5 paths.
- [Integration](integration.md) for adapter boundaries.
- [Root README](../README.md) for compile and verification commands.
