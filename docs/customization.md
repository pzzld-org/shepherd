# Customization

Beyond `shepherd.toml`, shepherd has three customization surfaces:

1. **Project doctrines** — DRIFT rules specific to your project, loaded into every flock dispatch
2. **Custom branch / release model** — non-mod-10 sprint counts, alt release pipelines, monorepo splits
3. **Custom flock briefs** — additional bracketed sections in coder briefs beyond the canonical seven

This doc covers each.

## Project doctrines

Framework doctrines (in `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/`) are language-agnostic and version-locked to shepherd's release. Your project will likely accumulate its own doctrines that DRIFT beyond the framework set. Examples from real projects:

- **Geo-block law** (a region-restricted service) — production region pinned forever to a specific Fly region for regulatory geo-fencing reasons. Code that violates this fails CI.
- **Write-only DB client** (some project) — all schema writes go through `WriteOnlyClient` wrapper that enforces idempotency keys.
- **Header contract** (API project) — every endpoint requires `X-Request-Id` header for trace correlation.
- **Wallet-watcher invariants** (DeFi project) — any code touching user balances must come with a paired property test.

These are NOT framework doctrines and don't belong in `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/`. They belong in your project's `.claude/doctrines/`:

```
your-project/
└── .claude/
    └── doctrines/
        ├── geo-block-law.md
        ├── wallet-balance-invariants.md
        └── header-contract.md
```

Configure shepherd to load them:

```toml
[memory]
project_doctrines = ".claude/doctrines"

[hooks]
on_every_dispatch = ["code-style"]
```

The conductor reads `project_doctrines/*.md` at every `/shepherd:*` invocation and injects them into every flock-agent dispatch as a preamble. Format your project doctrines like the framework doctrines:

```markdown
# Geo-block law — production yyz forever

The `node` Fly process group is pinned to `yyz` permanently. Region change is FORBIDDEN.

## Why
A regulated upstream API geo-restricts certain regions. Any code touching that API from
a restricted region trips detection and breaks the request flow.

## Enforcement
- `fly.toml [[vm]] processes=["node"]` carries `region = "yyz"`
- CI grep at `.github/workflows/discipline.yml` rejects PRs that change this
- `bin/gateway/` is forbidden from depending on the regulated SDK (`regulated-api-sdk`)

## See also
- ...
```

Project doctrines are first-class — auditor-completeness verifies they were honored, just like framework doctrines.

## Custom branch / release model

The framework defaults assume:

- 10 sprints per patch (mod-10 numbering)
- Patch branch named `v{X}.{Y}.{Z}`
- Sprint branch named `v{X}.{Y}.{Z}-dev.{N}`
- Squash-to-main on dev.{last} close

Most of these are configurable via `shepherd.toml [branching]`:

```toml
[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"          # any pattern with {X}{Y}{Z}
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"  # any pattern with {N}
sprints_per_patch     = 10
main_branch           = "main"
release_tag_pattern   = "v{X}.{Y}.{Z}"
```

Examples of valid alternative configs:

### 5-sprint patches

```toml
[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-sprint-{N}"
sprints_per_patch     = 5
main_branch           = "main"
```

`/shepherd:plant` will author seeds for sprint-0 through sprint-4. dev.5+ is invalid.

### Calendar-versioned releases

```toml
[branching]
patch_branch_pattern  = "release/{X}.{Y}"        # YYYY.WW
sprint_branch_pattern = "release/{X}.{Y}/dev-{N}"
sprints_per_patch     = 7                        # daily sprints?!
main_branch           = "main"
release_tag_pattern   = "{X}.{Y}"
```

### Monorepo with per-package patches

If your monorepo runs separate patches per package, you'll likely want one `shepherd.toml` per package:

```
monorepo/
├── packages/
│   ├── api/
│   │   └── .claude/shepherd.toml         # {X}.{Y}.{Z} for the API
│   ├── client/
│   │   └── .claude/shepherd.toml         # {X}.{Y}.{Z} for the client
│   └── lib/
│       └── .claude/shepherd.toml
```

Run shepherd from inside each package directory. Each manages its own patch-branch lifecycle.

### Trunk-based / no patch branches

If you don't use patch branches at all and squash directly to main:

```toml
[branching]
patch_branch_pattern  = "main"           # patch IS main
sprint_branch_pattern = "feat/{N}"
sprints_per_patch     = 0                 # 0 = no patch concept
main_branch           = "main"
```

This is degenerate — every sprint becomes a feature branch off main. The dev.{last}-rollover step is skipped (no patch to merge into main; main IS the destination).

## Custom flock briefs

The canonical coder brief has seven bracketed headers:

```
[SKILLS]
[CONTEXT-INVENTORY]
[DO-NOT-DUPLICATE]
[USER-STYLE]
[FILE-SCOPE]
[NON-GOALS]
[ACCEPTANCE]
```

If your project benefits from additional sections (e.g., `[PERFORMANCE-BUDGET]`, `[SECURITY-CHECKLIST]`, `[FEATURE-FLAG-NAME]`), extend the brief in `.claude/doctrines/coder-brief-extensions.md`:

```markdown
# Coder brief extensions for this project

In addition to the canonical seven sections, every coder brief MUST include:

[PERFORMANCE-BUDGET]
- Maximum allocations per call: {N}
- Maximum tail latency: {ms}

[FEATURE-FLAG-NAME]
- Flag this work behind: {flag}
- Default: off in production
```

The conductor reads this at session-open and the engineer's plan output includes the extra sections. The Brief-Validity Checklist in `flock.md` is operator-extensible — add a checkbox per new section.

## Custom audit concerns

The default audit concerns are: `code-quality`, `data-flow`, `dependency-topology`, `datastore-state`, `completeness`. Projects may want additional concerns:

```markdown
# Audit concerns for this project

Beyond the default 5, this project's auditor swarm includes:

- `security` — every PR touching authn/authz routes
- `performance` — every PR touching the hot path
- `compliance` — every PR touching audit-log emission
```

Drop this in `.claude/doctrines/audit-concerns.md` and the conductor's auditor-swarm dispatch picks them up.

## Custom planter inputs

The planter's Phase 0 mesh has 12 default rows (per `planter.md` §V). Projects may want additional mesh inputs:

```markdown
# Planter mesh extensions

Beyond the 12 default rows, every planter session for this project queries:

- Row 13 — Custom production-state check via `our-cli status --json`
- Row 14 — Open compliance findings from internal portal
```

Drop this in `.claude/doctrines/planter-mesh-extensions.md`.

## Customization order of operations

When configuring a new project:

1. Author `shepherd.toml` from `examples/<closest-fit>/shepherd.toml` as a starting point
2. Tune `[branching]`, `[gates]`, `[paths]` to match the project
3. Configure `[skills]` and `[skills.detection]` to attach the right skills
4. Author project doctrines in `.claude/doctrines/` over the first 2–3 sprints (don't try to write them all up front)
5. As patterns emerge, codify them as project doctrines

## See also

- [`docs/configuration.md`](configuration.md) — the full schema
- [`docs/integration.md`](integration.md) — composition with per-language skills
- [`examples/rust-service/shepherd.toml`](../examples/rust-service/shepherd.toml) — concrete working example
- [`examples/rust-service/doctrines/`](../examples/rust-service/doctrines/) — project-doctrine examples
