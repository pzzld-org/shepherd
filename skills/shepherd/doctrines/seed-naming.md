# Seed + plan filenames use slug form, NEVER the dotted branch form

> Origin: v5.1.1 (2026-05-16). Operator caught the planter producing
> `v0.3.2-dev.5.seed.md` (dotted form bleeding from `{sprint_branch}`) when
> the convention had been `v032-dev5.seed.md` (concatenated, no dots in
> the version triplet portion). This doctrine encodes the rule so the
> drift stops.

## The rule

**Branches keep dots; filenames collapse them.**

| Asset | Form | Example |
|---|---|---|
| Git branch (sprint) | dotted — `{sprint_branch_pattern}` | `v5.1.2-dev.3` |
| Git branch (patch)  | dotted — `{patch_branch_pattern}`  | `v5.1.2` |
| Seed file (sprint)  | slug — `{sprint_slug_pattern}` | `v512-dev3.seed.md` |
| Seed file (patch)   | slug — `{patch_slug_pattern}`  | `v512.seed.md` |
| Plan file (sprint)  | slug — `{sprint_slug_pattern}` | `v512-dev3.plan.md` |
| Close report        | dated — `<date>-{sprint_slug}-close.md` | `2026-05-16-v512-dev3-close.md` |

The version triplet (`X.Y.Z`) collapses to `XYZ` for filename purposes.
The `dev.N` suffix collapses `-dev.N` → `-devN`.

## Why two patterns

Git accepts dotted branch names natively — `v5.1.2-dev.3` is a perfectly
valid git ref. So branches keep dots: it's the operator's mental model AND
matches the canonical version syntax.

Filenames with multiple dots become ambiguous to humans + tools:
- `v0.3.2-dev.5.seed.md` reads "is this the 0.3.2-dev sprint's seed for
  version 5, or sprint 5 of v0.3.2-dev?"
- Some shell globs misbehave on multi-dot filenames
- Markdown ToC generators sometimes choke on dot-rich names
- The operator's visual scan is harder with periods bleeding into
  category-like positions

The slug form `v032-dev5.seed.md` has one period — the file extension
boundary. Unambiguous.

## Configuration

`shepherd.toml [branching]` declares both patterns:

```toml
[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"          # branches keep dots
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
patch_slug_pattern    = "v{X}{Y}{Z}"            # filenames collapse them
sprint_slug_pattern   = "v{X}{Y}{Z}-dev{N}"
```

If `*_slug_pattern` is absent, the framework falls back to `*_branch_pattern`
and emits a deprecation warning at session start. This preserves
back-compat for projects that have existing dotted seed files; they should
migrate at convenience.

## Migration for projects with existing dotted seeds

Two paths:

### Path A — Rename existing files

```bash
# Discover dotted seeds
find .artifacts/plans -name 'v*.seed.md' -o -name 'v*.plan.md' \
  | grep -E 'v[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?\.(seed|plan)\.md$'

# Bulk rename (dry-run first)
for f in $(find .artifacts/plans -name 'v*' | grep -E 'v[0-9]+\.[0-9]+\.[0-9]+'); do
  new=$(echo "$f" | sed -E 's/v([0-9]+)\.([0-9]+)\.([0-9]+)-dev\.([0-9]+)/v\1\2\3-dev\4/' | sed -E 's/v([0-9]+)\.([0-9]+)\.([0-9]+)/v\1\2\3/')
  echo "$f → $new"
  # git mv "$f" "$new"   # uncomment after dry-run review
done
```

### Path B — Accept both forms during transition

`shctx lint` (v5.1.1+) accepts both `v0.3.2-dev.5.seed.md` (legacy) and
`v032-dev5.seed.md` (slug). It emits a warning on legacy form, not an
error. New seeds go in slug form; existing dotted seeds stay until the
operator renames at leisure.

Recommended: Path B for in-flight patches; Path A at patch close before
opening the next one.

## Verifying adherence (auditor's job)

The `completeness` auditor at sprint close greps the plans/reports
directories:

```bash
# Find dotted seeds — should be 0 in new projects
rg -l 'v[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?\.(seed|plan)\.md' "$paths_plans" "$paths_reports" 2>/dev/null
```

Hits in this grep → grade-cap warning (not block); operator decides
whether to rename or accept the legacy form for that patch.

## Path-verification (related — v5.1.1+)

A second naming-related drift the operator caught: planters citing file
paths in seeds without verifying the paths exist. The planter's
drift-resistance contract already says "Every GH#, file path, memory
anchor, and doc reference resolves at seed-time" — but the planter
sometimes hallucinates paths anyway (dropping `.rs` suffixes, inventing
directory structures).

This doctrine encodes the rule but enforcement lives elsewhere:
- Planter MUST verify paths via `Read` / `Glob` before commit (planter.md
  drift-resistance contract)
- `shctx workspace search` (v5.1.2 — Lane B in this sprint, deferred to
  v5.1.3) will let planters mass-verify paths
- An optional pre-commit hook on seed/plan writes (future v5.2.x) could
  grep cited paths against the filesystem and BLOCK on hallucinated cites

For now: the planter's behavioral contract is the discipline; future
sprints will add teeth.

## Anti-patterns this doctrine catches

1. **Seed filename uses dotted form.** `v0.3.2-dev.5.seed.md` slipped in
   because the planter copied `{sprint_branch}` literally. Use
   `{sprint_slug}` for filenames.
2. **`shepherd.toml` missing `*_slug_pattern`.** Triggers deprecation
   warning + falls back to branch-form filenames. Operator should add
   the slug patterns at next config edit.
3. **Hallucinated paths in seeds.** Planter cites
   `crates/circuits/src/drift` (dir-as-file) when the actual path is
   `crates/circuits/src/drift.rs`. Planter must Glob/Read-verify before
   commit.

## See also

- `examples/minimal/shepherd.toml` — slug patterns added v5.1.1
- `examples/rust-service/shepherd.toml` — slug patterns added v5.1.1
- `docs/configuration.md` §[branching] — both pattern pairs documented
- `skills/shepherd/planter.md` §II — drift-resistance contract (verifiable)
- `skills/shepherd/references/seed-template.md` — seed shape uses
  `{sprint_slug}.seed.md` (updated v5.1.1)
- `skills/context/scripts/cmd_lint.sh` — accepts both forms during
  transition (warns on legacy)
