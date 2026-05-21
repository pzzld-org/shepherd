---
title: Workspace member isolation gate
slug: workspace-member-isolation-gate
status: binding
since: v5.1.7
---

# Workspace member isolation gate

## Rule

When a project uses workspace topology (multiple packages/crates/modules
managed by a single root tool — cargo workspaces, npm/pnpm/yarn workspaces,
turborepo, lerna, go work, bazel, gradle multi-project, maven reactor,
mix umbrella, etc.), the acceptance gate for any sweep touching workspace
structure or any member's manifest/feature/dependency surface MUST include
**per-member isolated builds**, not only the workspace-unified build.

A workspace-unified build (`cargo check --workspace`, `pnpm -r build`,
`turbo build`, `go work sync && go build ./...`) silently provides things
the isolated per-member build cannot see:

- transitively-resolved features unified across members
- hoisted dependencies satisfied by a sibling's `node_modules`
- workspace-level lockfile entries patching versions
- shared cache from upstream member that masks rebuild failures
- `replace` directives, `paths` mappings, link-protocol overrides
- root-level config (`.cargo/config.toml`, `tsconfig.base.json`,
  `pyproject.toml` workspace settings) that's not loaded in isolation

Result: workspace-unified passes, per-member fails. The defect class is
**"silently green on the unified gate, broken when a consumer pins the
member individually"** — affects downstream consumers, isolated CI jobs,
and reproducibility.

## What counts as the isolation gate

For each touched workspace member, run the equivalent of:

| Ecosystem | Workspace-unified | Per-member isolated |
|---|---|---|
| cargo | `cargo check --workspace --features full` | `cargo check -p <member> --features <composite> --frozen` |
| pnpm | `pnpm -r build` | `cd <member> && pnpm build --filter=. --no-deps` |
| npm workspaces | `npm run -ws build` | `cd <member> && npm run build --workspaces=false` |
| turborepo | `turbo build` | `turbo build --filter=<member> --no-cache` |
| go work | `go build ./...` from root | `cd <member> && go build ./...` (clean module cache) |
| bazel | `bazel build //...` | `bazel build //path/to:member` from a fresh server |

The general pattern: **change the cwd into the member, drop any
workspace-unified resolution context, build only that member.** If it
fails in isolation, the gate fails — regardless of whether the workspace
pass succeeded.

## Three sub-classes the gate catches

1. **Missing dep/feature forward.** A member's composite feature activates
   sub-crate via `dep:X` but doesn't forward sub-crate's required features.
   Workspace resolution masks the gap; isolation surfaces it.
2. **Manifest entry in wrong section.** `feature = [...]` placed under
   `[dependencies]` or `[dev-dependencies]` instead of `[features]`, or
   equivalent typo in `package.json` `dependencies` vs `peerDependencies`.
   Workspace parse may load; member-isolation parse rejects.
3. **Aggregator omitting sub-member feature forward.** Umbrella/re-export
   crate activates sub-member but doesn't propagate sub-member's own
   composite feature flags downstream.

## How the gate is implemented

Shepherd does not generate the CI workflow itself — each ecosystem has its
own conventions. The doctrine specifies the **acceptance contract**; the
project owns the implementation. Typical realizations:

- **GitHub Actions matrix** — one job per workspace member, running the
  isolated build command for that member
- **`Makefile` / `just` recipe** — `make isolation-check` iterates members
- **Pre-commit hook** — runs the isolation matrix when manifest files
  change
- **`shepherd.toml [gates].extra` entry** — declared per-project, fed into
  the intro-mode regression auditor (per
  `doctrines/sqlite-canonical-state.md` and the v5.1.7 closes for #44)

When `shepherd.toml [gates].extra` declares an isolation-check command,
the intro-mode regression auditor automatically runs it per
`agents/auditor.md` Canonical gates section.

## Required during any of these dispatches

- Multi-file feature/dependency sweeps (touching ≥2 member manifests)
- Adding a new internal dep with `default-features = false` or similar
  feature-erasure flag
- Re-exporting / umbrella-crate updates
- Lockfile regeneration that crosses workspace members
- Any sprint where the engineer's `[FILE-SCOPE]` includes manifests in
  ≥2 workspace members

## Anti-patterns

1. **"Workspace passes, we're green."** Workspace-unified is a necessary
   but insufficient gate when member topology is in scope.
2. **"It's just a Rust thing."** Every workspace-tool ecosystem has the
   same shape. The bug class is workspace-tool-general, not language-
   specific.
3. **"Add `--no-default-features` everywhere."** Treats the symptom; the
   isolation gate catches the actual missing forward.
4. **Lumping isolation-check into the workspace gate command.** Cargo's
   `cargo check --workspace -p A -p B -p C` is still workspace-unified
   resolution. Isolation requires separate process invocations per member,
   ideally with `CARGO_TARGET_DIR=target/.lanes/<member>` (per
   `doctrines/cargo-sequential-gates.md` and the v5.1.7 conductor cargo
   discipline section).

## Field origin

> Axiom v0.3.3-dev.4 (2026-05-20): three distinct feature-weaving defects
> in a single XL sprint, each hidden by `cargo check --workspace
> --features full` passing while `cargo check -p <single_pkg> --features
> <composite>` failed. Operator feedback (2026-05-20): "axiom shepherd's
> feedback is supposed to be general but this is unnecessary unless you
> can find a way to generally apply the concept they want."

Generalized per the operator's direction: the workspace-unified-vs-isolated
gap is a tool-class problem (any workspace-aware build tool has it), not a
language-specific one. The doctrine targets the contract; per-ecosystem
realization is project-owned.

## Cited from

- `agents/auditor.md` — intro-mode `Canonical gates (intro-mode regression)`
  section runs `[gates].extra` entries which is where projects declare
  their isolation-check command
- `doctrines/cargo-sequential-gates.md` — composes with this doctrine for
  Rust projects
- `doctrines/sqlite-canonical-state.md` — audit findings from the
  isolation gate land as `audit_findings` rows
