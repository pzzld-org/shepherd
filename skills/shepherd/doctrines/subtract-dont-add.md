# SUBTRACT-DON'T-ADD doctrine

**Every sprint MUST end strictly net-negative on (tables, columns, deps, abstractions, LOC).**

This is a structural constraint enforced by the auditor at sprint close. Sprints that end net-positive without operator pre-authorization grade-cap at C+.

## Why

The default failure mode of long-running engineering work is accretion: every sprint adds features, every refactor adds abstractions, every fix adds workarounds. The codebase grows monotonically and entropy compounds. Without a structural counter-pressure, the system collapses under its own weight.

SUBTRACT-DON'T-ADD reverses the default. Every sprint is a net-deletion sprint — until the codebase is genuinely incomplete and a feature is the headline, in which case the operator pre-authorizes net-positive in the seed.

## What counts

Categories the auditor measures:

- **LOC delta** — total added vs deleted across the sprint, **scoped to
  `[gates.subtract_paths]`** (production source code only). Net-negative
  wins. Process work (audit reports, close reports, handoffs, release
  notes, plans, journals) is OUTSIDE the scope by construction.
- **Dependency delta** — new third-party crates / packages vs deleted ones.
- **Abstraction delta** — new traits, generics, wrapper structs, indirection layers vs collapsed ones.
- **Schema delta** — new tables/columns/indices vs deleted ones.
- **File count delta** — new source files vs deleted ones (less weight; some additions are warranted).

Generated code (lockfiles, OpenAPI clients) doesn't count.

> Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5),
> §5. Wave-2 completeness auditor flagged net +4051 LOC sprint-wide as a
> SUBTRACT violation. Most of that LOC was Wave-1 documentation (FF
> matrix audit, ctx silo refresh, plan + amend-2 + Phase 0 + worker
> reports + audit reports). The doctrine's intent is "no scope-creep
> *code*; consolidate via dedup" — not "no documentation". v5.0.4
> codifies the path-scoped measurement.

## What this is NOT

> **Every sprint MUST end net-negative is a CONSTRAINT, not a JOB DESCRIPTION.**

Don't mistake deletion for work. If the seed promised a feature and the sprint shipped 1,200 LOC of deletion but the feature didn't land, the close grade caps at C+ regardless of the SUBTRACT win.

The actual test is: **did the seed's deliverables ship?** SUBTRACT is the constraint that those deliverables had to fit under. Both must pass.

## How to ship NET-NEGATIVE while delivering features

1. **Replace, don't append.** New helper? Find the closest-existing one and extend it instead of forking a parallel implementation. The goal is replacement ratio: every new line of code should retire ≥ 1 line of older code.
2. **Inline single-callers.** A function used in one place is a needless name. Inline it.
3. **Collapse hollow wrappers** (per `wrapper-must-earn.md`). `Foo { params: P }` with no invariant, no lifetime, no Arc-Inner share, no substantive trait-receiver IS a deletion candidate.
4. **Delete deprecated migration shims** as soon as the migration completes. Don't let `#[deprecated]` linger past one sprint.
5. **Audit the dependency tree every dev.0** — every patch should drop ≥ 1 third-party dependency.
6. **Remove dead feature flags** the moment the rollout completes.
7. **Inline single-impl traits.** A trait with one `impl` block that no test mocks doesn't earn its existence.

## When the operator pre-authorizes net-positive

When a sprint's headline IS a new feature, the seed must declare the expected sign. Example seed snippet:

```yaml
sprint_metadata:
  expected_loc_delta: "+800..+1500 (feature: ensemble agreement gate)"
  subtract_floor: "no LOC ceiling; auditor checks dependency-delta + abstraction-delta only"
```

Without this declaration, the auditor reads the framework default (`net-negative required`) and grade-caps the sprint.

## Auditor enforcement (close-time)

The framework specifies WHAT to measure (LOC delta, dependency delta,
abstraction delta, schema delta). The detection commands are language-
specific and live in the corresponding language skill. As a baseline:

```bash
# Total LOC delta — scoped to [gates.subtract_paths] from shepherd.toml.
# The auditor reads the glob list from config; if absent, falls back to
# language-skill defaults (Rust: crates/**/*.rs bin/**/*.rs **/*.toml **/*.sql).
git diff {patch_branch}..HEAD --shortstat -- $(read_subtract_paths_from_config)
```

If `[gates.subtract_paths]` is unset, the auditor reads the language
skill's default glob list. Documentation, audit artifacts, plans,
reports, and journals are excluded by construction — they live under
`{paths.reports}`, `{paths.docs}`, `{paths.plans}`, none of which match
the source-code globs.

For dependency-delta and abstraction-delta detection, the auditor invokes the project-language skill's deletion-detection patterns:

- **Rust** → `rust` skill §subtract-detection (Cargo.toml dep grep; `pub trait/struct/enum` adds/removes)
- **TypeScript** → `typescript` skill §subtract-detection (package.json dep diff; `export class/interface` adds/removes)
- **Python** → `python` skill §subtract-detection (pyproject.toml/requirements.txt diff; `class`/`def` adds/removes)
- (others) — language skill carries the patterns

Auditor `completeness` concern carries this gate. If net-positive without pre-auth → file finding `SUBTRACT-VIOLATION` and grade-cap C+.

## See also

- `wrapper-must-earn.md` — the structural test for hollow wrappers
- `pattern-b-overlap.md` — auditors run during Wave 2 coder dispatch
- `chain-repair.md` — when seed drift demands amendment instead of forging ahead
