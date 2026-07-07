# Customization

Beyond `shepherd.toml`, shepherd has three customization surfaces:

1. **Project doctrines** — DRIFT rules specific to your project, loaded into every flock dispatch
2. **Custom branch / release model** — non-mod-10 sprint counts, alt release pipelines, monorepo splits
3. **Custom flock briefs** — additional bracketed sections in coder briefs beyond the canonical seven

## Project doctrines

Framework rules (language-agnostic, version-locked to the shepherd release) live across
`skills/shepherd/`, `skills/adaptation/`, `skills/motivation/`, `skills/harness/`, and
`skills/context/`. Your project will accumulate its own doctrines that DRIFT beyond that set —
examples: a region-restricted service's Fly-region pin, a mandatory `WriteOnlyClient` wrapper for
schema writes, a required `X-Request-Id` trace header, a paired-property-test rule for any code
touching user balances.

These are NOT framework rules and do NOT belong under `skills/`. They belong in your project's
`.claude/doctrines/`:

```
your-project/.claude/doctrines/
├── geo-block-law.md
├── wallet-balance-invariants.md
└── header-contract.md
```

Configure shepherd to load them:

```toml
[memory]
project_doctrines = ".claude/doctrines"
```

The conductor reads `project_doctrines/*.md` at every `/shepherd:*` invocation and injects them as
a preamble into every flock-agent dispatch. Format them like the worked example at
`examples/rust-service/doctrines/`. Project doctrines are first-class: the auditor's
`completeness` concern verifies they were honored, exactly like framework rules.

## Custom branch / release model

Framework defaults: 10 sprints per patch, patch `v{X}.{Y}.{Z}`, sprint `v{X}.{Y}.{Z}-dev.{N}`,
squash-to-main on `dev.{last}` close. All of `[branching]` is configurable — any pattern
containing `{X}{Y}{Z}` / `{N}` works: 5-sprint patches (`sprint-{N}`, `sprints_per_patch = 5`),
calendar-versioned releases (`release/{X}.{Y}`, `sprints_per_patch = 7`), monorepo per-package
(one `shepherd.toml` per package directory, run shepherd from inside each), or trunk-based with no
patch branches (`patch_branch_pattern = "main"`, `sprints_per_patch = 0` — every sprint is a
feature branch off main, the `dev.{last}`-rollover step is skipped). See
`docs/configuration.md §[branching]` for the full key list.

## Custom flock briefs

The canonical coder brief has seven bracketed headers: `[SKILLS]`, `[CONTEXT-INVENTORY]`,
`[DO-NOT-DUPLICATE]`, `[USER-STYLE]`, `[FILE-SCOPE]`, `[NON-GOALS]`, `[ACCEPTANCE]`. To add project
sections (e.g. `[PERFORMANCE-BUDGET]`, `[SECURITY-CHECKLIST]`), extend
`.claude/doctrines/coder-brief-extensions.md`:

```markdown
In addition to the canonical seven, every coder brief MUST include:
[PERFORMANCE-BUDGET]
- Maximum allocations per call: {N}
```

The conductor reads this at session-open and the engineer's plan output includes the extra
sections. The Brief-Validity Checklist (`skills/shepherd/references/flock.md §Brief assembly`) is
operator-extensible — add a checkbox per new section.

## Custom audit concerns

Default concerns: `code-quality`, `data-flow`, `dependency-topology`, `datastore-state`,
`completeness`. Add project-specific concerns (e.g. `security`, `performance`, `compliance`) in
`.claude/doctrines/audit-concerns.md`; the conductor's auditor-swarm dispatch picks them up.

## Custom planter inputs

The planter's Phase 0 mesh has 12 default rows (`agents/planter.md`). Add project-specific rows
(e.g. a custom production-state check, open compliance findings) in
`.claude/doctrines/planter-mesh-extensions.md`.

## Order of operations

1. Author `shepherd.toml` from `examples/<closest-fit>/shepherd.toml`
2. Tune `[branching]`, `[gates]`, `[paths]` to match the project
3. Configure `[skills]` and `[skills.detection]` to attach the right skills
4. Author project doctrines in `.claude/doctrines/` over the first 2-3 sprints — do not front-load them
5. Codify recurring patterns as project doctrines as they emerge

## See also

- [`docs/configuration.md`](configuration.md) — the full schema
- [`docs/integration.md`](integration.md) — composition with per-language skills
- [`examples/rust-service/shepherd.toml`](../examples/rust-service/shepherd.toml) — concrete working example
- [`examples/rust-service/doctrines/`](../examples/rust-service/doctrines/) — project-doctrine examples
