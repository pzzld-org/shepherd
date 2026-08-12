---
title: v6.4.5 Seed — one compiled canonical CLI, one harness-agnostic monorepo
branch: v6.4.5
base: main
kind: patch-seed
status: ready-for-engineer
date: 2026-08-12
revised: 2026-08-12
author: planter @ plant-v645-2026-08-12
prior_close_report: none — no close.md exists anywhere under .shepherd/runs/ (mesh ROW 8)
prior_handoff: none — no handoff.md exists anywhere under .shepherd/runs/ (mesh ROW 9)
planter_mesh: .shepherd/runs/v645/mesh.md
milestone: 58
sprint_dependencies: []
sprint_size: XL
file_scope:
  exclusive:
    - Cargo.toml
    - cli
    - packages (NEW — npm platform packages + TS harness adapters)
    - content (NEW — harness-neutral role and skill sources)
    - conformance (NEW — language-neutral golden corpus)
    - services/cli
  additive:
    - .shepherd/shepherd.toml
    - skills/context/schema
    - hooks
    - docs
    - CHANGELOG.md
---

# v6.4.5 — the CLI stops being a rewrite target

## A. Patch theme

Shepherd's engine is rewritten once, in Rust, and published as a single compiled binary plus npm platform packages. The three harnesses become thin adapters over one core inside one monorepo. Python and the legacy bash verb layer are retired behind a byte-parity gate, not beside it. After this arc, adding a harness is writing an adapter; it is never porting the engine again.

## 2. Why this patch

- **The packaging layer is the top source of hard outages.** `#266` shipped as CRITICAL in v6.4.4: an unprovisioned venv made every command die with `ModuleNotFoundError: typer`, blocking `/shepherd:spawn` boot-prompt render. A static binary removes that failure class structurally rather than healing it.
- **The launcher already resolves the wrong implementation.** `#235` globs `cache/fl03/shepherd/*` and silently pins a stale binary under a different publisher dir. Today `shctx` execs the legacy bash layer while `shepherd` execs Python (mesh ROW 1) — two diverging command surfaces under one project.
- **The port work is already being done twice.** `FL03/codex-shepherd` v1.0.2 dogfooding filed `#278` and `#277` against shared-state and run-scoping contracts; a Pi implementation would make it three copies of nine role contracts (`docs/pi-shepherd.md`, `docs/shepherd-monorepo.md`).
- **The prior CLI arc never finished.** `#239` still tracks "retire the bash layer"; `v641-dev0`'s own plan deferred deletion of 45 scripts plus 50 bash tests as "a mechanical follow-up" that never landed (mesh ROW 4).
- **Tests are the only spec and they are Python-shaped.** 1,583 pytest functions assert exact stdout, exit codes, and mutation-freedom, with no stored golden corpus (mesh, CLI inventory). Nothing language-neutral pins current behavior, so any rewrite is currently unverifiable.

## 2-bis. Priors / lessons carried forward

| Prior id | Lesson (concern) | Guard this patch applies |
|---|---|---|
| none (registry absent) | `.shepherd/ctx/` and `shepherd.db` were never bootstrapped in this checkout, so ROW 11/12 are structurally empty and `shctx discovery insert` failed 8/8 during the mesh | Registry bootstrap is the first release-gate check (§C.1); the arc may not close with an unprovisioned silo |

## 5. Engineering decisions (locked)

Changing one of these is a critic-RED escalation, not a sprint-time judgment call.

1. **Rust owns the engine; TypeScript owns Pi's hot path.** `crates/` holds core, registry, render, and CLI. Claude and Codex adapters exec the binary. Pi's per-`tool_call` guards stay TypeScript. No napi-rs and no `.node` addon in this arc: the jiti in-process load path is unverified and Prisma walked back that exact architecture in 7.0.0.
2. **Guard predicates are data, not duplicated code.** Both the Rust engine and the TS guard layer interpret one declarative predicate spec under `content/`. A predicate expressed as code in two languages is a defect.
3. **The registry schema is the cross-harness contract, not CLI stdout.** All 32 guard scripts read SQLite directly and zero of them shell out to the CLI. Schema and row shapes are the compatibility surface.
4. **`rusqlite` with `features = ["bundled"]` only.** Probe-verified against 0.40.2 (SQLite 3.53.2): FTS5 present, external-content tables with `unicode61 remove_diacritics 2` work, `json_valid` CHECKs enforce. There is no `fts5` cargo feature. `ENABLE_JSON1` is ABSENT from `compile_options` yet `json_valid` works, since JSON went core at SQLite 3.38 — assert the behavior, never that flag.
5. **No canon flip before the parity gate is green.** Python stays canonical until conformance passes byte-clean. There is no dual-maintenance window.
6. **The 20 migration files port verbatim.** Migration SQL is the portable artifact; only the runner is rewritten. `rusqlite_migration` is rejected: it tracks state in `user_version`, while this schema uses a `schema_versions` table both existing runners read.
7. **The dependency stack is closed.** `clap`, `rusqlite`, `config` (toml feature only), `schemars`, `toml`, `nom`, `minijinja`, `serde`, `sha2`, `anyhow`, `thiserror`, `uuid`, `chrono`, `tracing`. 101 resolved packages, down from the scaffold's 201. No `sqlx`, no `tokio`, no `reqwest`; GitHub stays on the `gh` CLI. `config` owns the six-tier precedence chain so `_lib.sh:shctx_config_files()` is deleted rather than ported; `schemars` generates the key universe the validator checks against. Rationale and probe results in `.shepherd/docs/specs/2026-08-12-v645-rust-dependency-stack.md`. Adding a crate is a critic-RED escalation.

## B. Sprint topology

Recommended shape only. The engineer's Stage Graph is binding.

| Sprint | Theme | Size | Depends on | Parallel-safe with |
|---|---|---|---|---|
| dev.0 | Workspace scaffold done; registry bootstrap, conformance oracle frozen from Python | L | — | — |
| dev.1 | Rust core: run state, canonical `run.json`, config schema, Stage Graph | XL | dev.0 | dev.2 |
| dev.2 | Rust registry: 20 migrations, 39 tables, 25 views, 7 triggers, FTS5 | L | dev.0 | dev.1 |
| dev.3 | Verb surface: ~147 leaf commands to parity, plus render and templates | XL | dev.1, dev.2 | — |
| dev.4 | Distribution: platform packages, launcher, Python and bash retirement | M | dev.3 | dev.5 |
| dev.5 | `content/` compiler and the three harness adapters, Pi included | L | dev.1 | dev.4 |

## 4. Phase 0 mesh mandate

| # | Source | Query | Pass condition |
|---|--------|-------|----------------|
| 1 | GH issues (FULL sweep) | `gh issue list --state open --limit 500` | classify per `[ledger.classify_into]`; reconcile the 8 CHANGELOG-fixed-but-open issues |
| 2 | GH PRs | open plus merged since v6.4.4 | activity since the tag |
| 3 | GH milestones | milestone 58 | every arc deliverable carries a real issue number |
| 4 | git log | `git log v6.4.4..HEAD --oneline` | what already landed on this branch |
| 5 | Registry bootstrap | `shctx doctor` | `.shepherd/ctx/` and `shepherd.db` exist, or file the gap |
| 6 | Python CLI surface | `shepherd --help` walked to every leaf | live leaf-verb count, current vs the ~147 estimate |
| 7 | Guard read paths | `grep -l sqlite3 hooks/scripts/*.sh` | every table a guard reads is in the conformance corpus |
| 8 | Schema inventory | `skills/context/schema/**` | 20 migrations, 39 tables, 25 views, 7 triggers still current |
| 9 | Template lineage | `render.py` manifest fields | `template_sha256`, `vars_sha256`, `output_sha256` reproduce byte-identically |
| 10 | Prior close and handoff | `.shepherd/runs/*/close.md` | confirmed absent, or newly present since planting |
| 11 | Carry-forward ledger | `.shepherd/ctx/carry-forward.md` | bootstrapped, or the gap is a filed deliverable |
| 12 | Cross-harness docs | `docs/pi-shepherd.md`, `docs/shepherd-monorepo.md` | vault specs still match the locked decisions above |

## 6. Deliverables (issue-anchored)

### Monorepo skeleton and workspace layout  [CRITICAL]
- **GH:** #280
- **Priority:** CRITICAL
- **Spec:** `crates/{core,registry,render,cli}` plus `packages/{harness-claude,harness-codex,harness-pi}`; root holds glue only
- **Acceptance:** `cargo metadata --no-deps` lists 4 members and `cargo check --workspace` exits 0

### Conformance oracle frozen from the Python CLI  [CRITICAL]
- **GH:** #281
- **Priority:** CRITICAL
- **Spec:** capture stdout, exit code, `run.json` bytes, rendered templates, and `sqlite_master` per case; no implementation may merge before its cases exist
- **Acceptance:** `conformance/run.sh --impl=python` exits 0 with a non-zero case count and a committed corpus checksum

### Rust core engine  [CRITICAL]
- **GH:** #282
- **Priority:** CRITICAL
- **Spec:** unknown-key round-trip preserved; recursively sorted canonical JSON; atomic write via temp, fsync, rename
- **Acceptance:** `conformance/run.sh --impl=rust --suite=run-state` byte-clean against the python oracle

### Rust registry and migration runner  [CRITICAL]
- **GH:** #283
- **Priority:** CRITICAL
- **Spec:** migration SQL copied verbatim; 6 FTS5 sync triggers reproduced; `unicode61 remove_diacritics 2` tokenizer preserved
- **Acceptance:** order-normalized `sqlite_master` dump identical between implementations; `PRAGMA compile_options` includes `ENABLE_FTS5`

### Canonical verb surface to parity  [CRITICAL]
- **GH:** #239
- **Priority:** CRITICAL
- **Spec:** every leaf verb reproduced, including the 29 hand-parsed bash-parity modules; supersedes #239's remaining bash-retirement scope
- **Acceptance:** `conformance/run.sh --impl=rust` green on every case, zero skips

### Distribution and launcher consolidation  [HIGH]
- **GH:** #235
- **Priority:** HIGH
- **Spec:** npm platform packages under `optionalDependencies`, single launcher, one name for one implementation; lockfile generated on glibc CI
- **Acceptance:** clean install on macOS arm64, linux gnu, linux musl, and windows resolves one binary; `--no-optional` install still resolves

### Python and bash retirement  [HIGH]
- **GH:** #266
- **Priority:** HIGH
- **Spec:** delete `services/cli/`, the 40 `cmd_*.sh` verb scripts, and the venv bootstrap once conformance is green; migrate the 50 bash test assertions rather than dropping them
- **Acceptance:** `rg -n 'shepherd-venv-ensure|poetry' --glob '!CHANGELOG.md'` returns 0 hits; no `.py` under `services/cli`

### Harness adapters and the content compiler  [HIGH]
- **GH:** #279
- **Priority:** HIGH
- **Spec:** role and skill bodies authored once in `content/`, emitted per harness; Pi adapter carries the TS guard layer over the shared predicate spec; absorbs #277 and #278 run-scoping contracts
- **Acceptance:** each adapter's emitted role set diffs clean against `content/` and every guard predicate has an allow and a deny case

## C. Release-gate criteria

1. `shctx doctor` reports a bootstrapped registry and knowledge silo.
2. `conformance/run.sh` green on both implementations, zero skips, corpus checksum committed.
3. Gate tests under 2 seconds; guard predicates table-tested with allow and deny per code.
4. A `run.json` written by the Rust binary is read and advanced by the Claude adapter without migration.
5. Install probe passes on all four target triples plus `--no-optional`.
6. Every deliverable's GH issue is closed with its acceptance command output pasted in.
7. CHANGELOG v6.4.5 entry written; README and `plugin.json` versions agree.

## D. Cross-sprint dependencies

`dev.0 → [dev.1 || dev.2] → dev.3 → [dev.4 || dev.5]`

## E. Carry-forward ledger snapshot

| GH# | Item | Severity | First seen | Patches crossed | Disposition |
|---|---|---|---|---|---|
| #239 | Retire the legacy bash verb layer | HIGH | v6.4.1 | 4 | LAND — superseded by the canonical verb surface |
| #266 | CLI venv unprovisioned on upgrade | CRITICAL | v6.4.4 | 1 | LAND — removed structurally by the compiled binary |
| #235 | Launcher pins a stale binary | HIGH | v6.4.x | 2 | LAND — CHRONIC, crossed the threshold |
| #277 | Run-local support directories | MEDIUM | v6.4.4 | 1 | LAND — absorbed by the adapter contract |
| #278 | Run-scoped graph state mandatory | MEDIUM | v6.4.4 | 1 | LAND — absorbed by the adapter contract |

## F. Patch-level non-goals

- **No napi-rs, no WASM engine build.** Deferred to v6.5.x behind a timeboxed spike; the TS guard layer makes it an optimization, never a prerequisite.
- **No new orchestration features.** The flock, Stage Graph semantics, and dispatch law ship unchanged; a behavior change during a rewrite is unverifiable against the oracle.
- **No MCP dependency.** Probed when present, never required.
- **No seventh flock role.** Closed at six plus two orchestration tiers.

## 11. Open questions for critic

1. Are the 8 CHANGELOG-fixed-but-open issues genuinely fixed? The arc cites `#266` and `#235` as live pain; if they are closed in code, the citations need restating.
2. Does the `shctx` name survive as an alias of the new binary, or retire with the bash layer? Agent-authored prose across `skills/**` invokes it by name.
3. Is 6 sprints honest for ~42,500 implementation lines and 1,583 test assertions, or does the verb surface deserve its own arc?
4. Pi's `--tools` is documented as a replacing allowlist over built-in tools; that is read from `pi --help` on 0.84.1, not confirmed by a runtime probe. Does the adapter's capability claim need the probe first?

## 12. References

- Mesh report: `.shepherd/runs/v645/mesh.md` — the tracked, durable record. Raw lane evidence sits at `runs/v645/reports/discovery-mesh-gh.md`, which `.gitignore` excludes by design, so mesh.md is authoritative for anyone cloning
- Pi implementation spec — `obsidian://adv-uri?vault=pzzld&filepath=src%2Fprojects%2Fshepherd%2Fdocs%2Fpi-shepherd.md`
- Monorepo architecture — `obsidian://adv-uri?vault=pzzld&filepath=src%2Fprojects%2Fshepherd%2Fdocs%2Fshepherd-monorepo.md`
- Project home — `obsidian://adv-uri?vault=pzzld&filepath=src%2Fprojects%2Fshepherd%2FREADME.md`
- Port precedent: `FL03/codex-shepherd` v1.0.2 `docs/parity.md`; tracking: FL03/shepherd#279, milestone 58
- Dependency stack, locked and Context7-checked: `.shepherd/docs/specs/2026-08-12-v645-rust-dependency-stack.md`
- `skills/shepherd/references/seed-template.md`, `agents/planter.md`, `CHANGELOG.md` v6.4.4
