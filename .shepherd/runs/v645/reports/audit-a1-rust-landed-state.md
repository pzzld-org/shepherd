# A1 — Rust landed state and regression ledger

**Reporter:** intro-mode `@auditor` · **Run:** v645 · **Materialized by:** root (payload landed in root's
notification stream, not the dispatching engineer's — see `dogfood.md` DF-11) · 2026-08-12

## Crate state

Total **1,363 Rust lines** (666 + 241 + 163 + 137 + 156), confirmed exact.

| Crate | LOC | Implemented | Stubbed / missing | Public API | Deps |
|---|---|---|---|---|---|
| `shepherd-core` (`crates/core`) | 666 | `error::Error` (5 variants, thiserror); `settings::{ShepherdConfig,WorkspaceConfig,ProjectConfig}`; `loader::{candidates,layer,validate,ConfigTier,ConfigContext,ConfigCandidate}` — the full 10-candidate / 4-tier precedence chain with the reversal for `config`; `types::Harness` (4 variants, strum-derived, snake_case round-trip) | No `run.json` / run-state machine, no Stage Graph, no canonical-JSON codec — all #282 scope, issue open | `error::{Error,Result}`, `types::*` incl. `Harness`, `settings::ShepherdConfig` (std), `loader` (config feature), `prelude` | `thiserror`, `strum` required; `nom`, `config`, `schemars`, `serde`, `serde_json`, `chrono`, `uuid`, `tracing` optional |
| `shepherd-registry` (`crates/registry`) | 241 | `error::Error` (Core/Sqlite/Migration/SchemaAhead/Unknown); 4 gate tests in `tests/default.rs` probing FTS5, tokenizer, `json_valid`, file-VFS round-trip | **No migration runner, no schema, no query surface.** README and `Cargo.toml` description say "schema, migration runner, and query surface"; `src/lib.rs:33-59` is `pub mod error;` + `pub use shepherd_core as core;` and nothing else. README §"The contract this crate owes" (line 11) frames this correctly as a future obligation | `error::{Error,Result}`, `core` re-export, `prelude` | `shepherd-core`, `rusqlite` (cache), `thiserror`; optional `serde`, `serde_json`, `tracing` |
| `shepherd-render` (`crates/render`) | 163 | `error::Error`; 2 gate tests — `rendering_is_reproducible` (64x identical minijinja render), `provenance_hashing_is_sha256_over_raw_bytes` (NIST "abc" vector) | **No template resolution, no rendering function, no manifest/provenance code.** Same pattern as registry: `src/lib.rs:39-51` is the error module plus a re-export | `error::{Error,Result}`, `core` re-export, `prelude` | `shepherd-core`, `minijinja` (builtins/macros/multi_template/serde), `sha2`, `thiserror`; optional `serde`, `serde_json`, `tracing` |
| `shepherd` / sdk (`crates/sdk`) | 137 | Umbrella: flattens `shepherd_core::*`, gates `registry`/`render` re-exports behind features, disambiguated `prelude`; 2 compile-time re-export assertion tests | N/A by design | `shepherd::{*, registry, render, prelude}` | `shepherd-core` required; `shepherd-registry`, `shepherd-render` optional |
| `shepherd-cli` (`crates/cli`) | 156 | `ShepherdCli` (clap::Parser, 4 top-level flags), `ShepherdCommand::Init(InitCmd)`, `bin/cli.rs` parses args + installs tracing subscriber | **`InitCmd` is an empty struct — `init` does nothing.** `README.md` is a 1-line stub, unlike the other four crates' substantive READMEs | `ShepherdCli`, `cmd::*`, re-exports `Harness, ShepherdConfig, error, settings, types` from `shepherd` | `shepherd` (json/parse/registry/render/schema/tracing), `clap`, `config`, `anyhow`, `thiserror`, `serde`, `serde_json`, `tracing`, `tracing-subscriber` |

**No `todo!()`, `unimplemented!()`, `TODO`, `FIXME`, `XXX`, or `HACK` anywhere under `crates/`** (grep
verified). The gap is absence, not disguised stubs.

**Not overclaiming:** #280's own status field (`seed.md:107`) already says "the Rust half is landed and
green in CI. Remaining: `packages/`…`content/`…`conformance/`…" — scoped to the workspace/CI scaffold
deliverable only. Registry and render logic are separately tracked as #283/#282/#239, none prematurely
closed (verified via `gh issue view`).

## Boundary gates

| Claimed gate | Exists | Asserts | Negative control |
|---|---|---|---|
| `core` → `wasm32-unknown-unknown` | YES (`.github/workflows/boundaries.yml:55-56`) | `cargo check -p shepherd-core --target wasm32-unknown-unknown` | Implicit — a dependency that cannot cross wasm fails the build itself; no committed fixture |
| Forbidden-dependency gate (delivery: clap/anyhow/tracing-subscriber; io: rusqlite/minijinja/libsqlite3-sys) | YES (`boundaries.yml:78-131`) | `cargo tree` on `shepherd-core --features full`, `shepherd --features full`, `shepherd` default, against two regex tiers. Includes a **positive control** (`:119-123`) asserting `shepherd --features full` still links `rusqlite`, so a dropped capability cannot make the check pass vacuously | **Prose only.** `boundaries.yml:138-140` claims "Verified against a negative control before this job was committed"; `grep -n "negative control"` across `.github/` and `scripts/` returns exactly that one comment, no fixture or self-test. #280's comment (`12e74fe`) confirms it was a one-time manual verification |
| Process/argv gate (`std::process`, `std::env::args`, `process::exit`) | YES (`boundaries.yml:134-149`) | `grep -rnE` over `crates/{core,registry,render}/src` and `crates/sdk/lib.rs`, excluding comment lines | Prose only, same as above |
| Config-I/O gate (`config::Environment`, `File::with_name`, `File::from(`) | YES (`boundaries.yml:162-178`) | Same grep pattern, forbidding filesystem/env config reads in library crates | Prose only |
| `engine-boundary` CI job named in decision 8 | YES — job `engine` in `boundaries.yml` runs all four checks in one job (workflow named `boundaries`, functionally identical) | — | — |
| `scripts/check-workspace.sh` (9 invariants) | YES — lints-inherited, version-inherited, README+description, docsrs metadata, umbrella-reachability, binary-routes-through-umbrella, one-binary, workspace-deps-ungated, members-in-feature-matrix | | **YES — real, fixture-based.** `--self-test` (`:267-354`) runs each rule against a deliberately broken fixture and asserts it fails, plus a temp-dir fixture for the ungated-deps rule |
| `scripts/check-plugin.sh` | YES — plugin root layout, hooks.json discoverability | | **YES** — `--self-test` exists (`rust.yml:137-138`, script header `:22-23`), same fixture pattern |
| `scripts/check-features.sh` | YES — isolated feature-flag builds across all 5 crates, host + `--targets` wasm cross-compile | | No self-test, and correctly so: it is a positive-assertion matrix (every combination must succeed), a different gate shape that needs no negative fixture |

**CI reality check, not aspirational:** `gh run list` shows `boundaries`, `rust-wasm`, and `rust` all green
on PR #273 HEAD `894b3fe`. Spot-checked run `31647400980` (boundaries, 14s) and `31647400972` (rust-wasm,
6 jobs, 22-36s each) — both genuinely executed, not skipped, timings consistent with
`rust-cache`/`sccache`/wasi-sdk caching.

## Uncommitted drift — the brief's claim was stale

`git diff .github/workflows/rust.yml` is empty; `scripts/check-workspace.sh` is tracked
(`git log -1 -- scripts/check-workspace.sh` → `25ccdf9`). Working tree clean at HEAD `894b3fe`, in sync
with `origin/v6.4.5`. Both files were modified/created earlier in this same session's history and have
since been committed across `25ccdf9` (add) → `12e74fe` (sccache scoping fix) → `894b3fe` (plugin-layout
restore), and both are exercised by passing CI. **Nothing half-finished — do not plan a step to finish
them.**

Only untracked paths are `.shepherd/{archive,docs/plans,docs/reports/.gitkeep,scripts,templates,types}/`,
freshly created by root's `shctx init` bootstrap.

The brief's `[RESOURCE-HARD-RULE]` disk/swap figures **do** match live `df -h` / `sysctl vm.swapusage`
exactly — that part of the invocation context is accurate. Only the git-drift claim was stale.

## Decisions 9 and 10 — CLEAN

- **Decision 9 (umbrella-only):** `crates/cli/Cargo.toml:41-48` depends only on `shepherd`;
  `grep -rn "shepherd-core\|shepherd-registry\|shepherd-render" crates/cli/Cargo.toml` returns zero
  dependency hits (one comment mention at `:83`). `crates/registry` and `crates/render` depend on
  `shepherd-core` directly, which is correct — they are the members being wrapped, not consumers.
  `check-workspace.sh:rule_binary_routes_through_umbrella` (`:145-162`) enforces it with a self-test.
- **Decision 10 (weak fan-out):** `crates/sdk/Cargo.toml:71-75` —
  `json = ["shepherd-core/json","shepherd-registry?/json","shepherd-render?/json"]`. Every capability flag
  uses `?/` throughout (`nightly`, `wasi`, `wasm`, `alloc`, `std`, `tracing` all confirmed weak).
  `check-features.sh` has a `-p` row for all 5 members (`:50,57,65,70,74-77`) and
  `check-workspace.sh:rule_members_in_feature_matrix` enforces it by name.

## Regression ledger

| Acceptance command | Exists | Last real result | Verdict |
|---|---|---|---|
| `cargo metadata --no-deps` → 5 members | runnable | ran live (read-only): `shepherd-cli, shepherd, shepherd-core, shepherd-registry, shepherd-render` | **GREEN, verified live** |
| `cargo check --workspace` | runnable, not run (compile forbidden this lane) | CI `rust` job `clippy`/`test` (superset) green, run `31647400964`, 50s | GREEN per CI |
| `scripts/check-features.sh --targets` | exists | CI `features` job `rust.yml:253-284`; #280 comment (`f0f05e1`) states "ok: all 25 feature combinations resolve" | GREEN per CI |
| `conformance/run.sh --impl=python` (#281) | **does not exist** (`ls conformance` → No such file) | N/A | **ASPIRATIONAL** — unstarted |
| `conformance/run.sh --impl=rust --suite=run-state` (#282) | does not exist | N/A | **ASPIRATIONAL** |
| `claude plugin validate` | tool exists, not invoked this lane | N/A | not checked — `894b3fe`'s own finding is that it passes on a broken tree, which is why `check-plugin.sh` exists |
| `scripts/check-plugin.sh --self-test` | exists | CI `lint` job `rust.yml:137-140`, green on `894b3fe` | GREEN per CI |
| `rg -n 'shepherd-venv-ensure\|poetry' --glob '!CHANGELOG.md'` (#266) | runnable, deprioritized under budget | not verified | **UNCHECKED — run centrally** |
| `rg -n 'harness-(claude\|codex\|pi)' crates/` (#280 acceptance 4) | not run | `packages/` does not exist, so vacuously 0 | low risk |

## Findings

1. **MEDIUM** — Boundary-gate negative controls for the three grep-based gates
   (`boundaries.yml:78-178`) are asserted **only by a prose comment**, with no committed repeatable
   fixture — unlike `check-workspace.sh` / `check-plugin.sh`, which have genuine `--self-test` fixtures
   (`check-workspace.sh:267-354`). A future edit narrowing a regex (say `^clap$` mistyped `^clapp$`) would
   pass silently forever with nothing in CI to catch it. Seed decision 8's premise is "enforced by CI, not
   by prose"; one third of that enforcement is currently prose. Confidence HIGH.
2. **LOW** — `crates/cli/README.md` is one line and satisfies
   `check-workspace.sh:rule_has_readme_and_description` because that rule is existence-only. Every other
   crate's README is 1.6-4.3 KB explaining its boundary and contract. Confidence HIGH.
3. **LOW** — `scripts/check-workspace.sh` and `scripts/check-plugin.sh` are **Python** scripts
   (`#!/usr/bin/env python3`) carrying `.sh` extensions. Harmless — executable bit set, shebang correct —
   but misleading for anyone grepping for bash. Confidence HIGH.
4. **LOW** — `crates/core/src/settings.rs::ProjectConfig` is defined and covered by a compile-time type
   assertion (`crates/core/tests/default.rs:24`) but has **zero runtime use** anywhere
   (`grep -rn ProjectConfig crates/` shows only the definition and that assertion). Expected while #282 is
   unstarted; track it so it does not become dead weight if #282 changes shape. Confidence MEDIUM.
5. **Informational, not a defect** — `shepherd-registry` and `shepherd-render` READMEs read as complete
   implementations at first pass but are explicitly framed as forward-looking, and both crates contain only
   capability-probe gate tests plus error types. Correctly scoped to #283 and #282 rather than #280. Flagged
   only because wave sizing depends on this landed-versus-planned distinction being visible.

**Files reviewed:** all 21 `.rs`, all 5 `Cargo.toml`, all 5 `README.md` under `crates/`;
`.github/workflows/{boundaries,rust,rust-wasm}.yml`; `scripts/{check-workspace,check-features,check-plugin,gate}.sh`;
`deny.toml`; workspace `Cargo.toml`; `rust-toolchain.toml`; `seed.md`; GH issues #280 (+comments), #281,
#282, #283, #239, #235, #266, #279; `gh run list`/`gh run view` for 2 CI runs.
