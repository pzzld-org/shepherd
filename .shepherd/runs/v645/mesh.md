# v645 — Planter mesh report

**Run:** `v645` (patch arc, `v6.4.5`) · **Planted:** 2026-08-12 · **Seed:** `.shepherd/runs/v645/seed.md`

Three read-only discovery lanes ran under the plant-mode bounded-discovery allowance: GitHub and git state, Python CLI port surface, and Rust-to-npm distribution validation. Raw evidence for the first lane is at `reports/discovery-mesh-gh.md`, which `.gitignore` excludes as run-scoped ephemera. **This file is the tracked record; treat it as authoritative rather than as a summary.**

## Row results

| # | Source | Result |
|---|---|---|
| 1 | GH issues, full sweep | 22 open. Class (a) CLI/Python-port: #239, #266, #235. Class (b) harness portability: #279, #278, #277. **Class (c) monorepo/packaging: zero issues** — the arc's core deliverable has no existing anchor. 19/22 (86%) carry no milestone |
| 2 | GH PRs | PR #273 open against milestone 58 |
| 3 | Milestones | 58 = v6.4.5, open, effectively empty. 59 = v6.5.0 holds #279 |
| 4 | git log | Branch `v6.4.5` exists on origin, tree clean, no `v6.4.5-dev.*` branches. Sprint numbering therefore starts at N=0 |
| 5 | Sentry | skipped — `[mcp].sentry = false` |
| 6 | Datastore | skipped — `[mcp].supabase = false` |
| 7 | Deploy | skipped — `[cli].fly = false` |
| 8 | Prior close | **absent** — no `close.md` exists anywhere under `.shepherd/runs/`, including `v641-dev0` |
| 9 | Prior handoff | **absent** — same |
| 10 | CLAUDE.md / README | README claims 6.4.4, `plugin.json` already reads 6.4.5, no v6.4.5 CHANGELOG entry yet |
| 11 | Carry-forward ledger | **structurally absent** — `.shepherd/ctx/` has never existed in git history |
| 12 | Knowledge silo | **structurally absent** — same directory |

## Findings that shaped the seed

**The registry was never bootstrapped in this checkout.** `.shepherd/ctx/` and `.shepherd/shepherd.db` do not exist, so rows 11 and 12 are empty by construction rather than clean. The discovery lane's own `shctx discovery insert` calls failed 8/8 with `registry DB not found`. Bootstrap is release-gate check C.1.

**The compatibility surface is the schema, not CLI stdout.** All 32 hook and guard scripts read SQLite directly; grep for executed `shctx <verb>` calls in `hooks/scripts/*.sh` returns zero. Every `shctx` string found there is inside a human-facing message or a comment. This inverted the seed's conformance design: the oracle pins `sqlite_master`, `run.json` bytes, and template digests, not help text.

**The port surface is roughly 5x my pre-mesh estimate.** 42,560 implementation lines across 68 files, 32,945 test lines across 55 files, 43 top-level command groups, approximately 147 leaf verbs (ESTIMATE, plus or minus 10), 1,583 pytest functions. Schema: 20 migrations, 39 tables, 25 views, 40 indexes, 7 triggers, 2 FTS5 external-content virtual tables with 6 sync triggers, 25 `json_valid()` CHECK constraints.

**There is no golden corpus.** Test fixtures are built programmatically in `conftest.py` and are ephemeral. The 1,583 pytest assertions are the only specification of current behavior, and they are Python-shaped. Nothing language-neutral pins the CLI today, which is why the conformance oracle is sequenced before any port code rather than beside it.

**Two implementations already answer to two names.** `shctx` on PATH execs the legacy bash layer; `shepherd` execs the Python CLI. Their verb sets have diverged: `run` (16 verbs), `home`, `teammate`, and `render` exist only in Python, and `mem delete`, `config migrate`, `config validate`, and `adapt reflect` are Python-only additions to bash-era groups.

**29 of 43 command modules deliberately bypass their own framework.** They register no Typer subcommands and hand-parse `sys.argv` to reproduce the retired bash layer's usage text and exit codes byte-for-byte. Neither `clap` nor `commander` wants to be told to print an exact string. This is the single most port-hostile item and the reason the verb-surface sprint is sized XL.

## Architecture validation

**Rust core, npm platform packages: proven.** The `optionalDependencies` pattern is shipping today in esbuild 0.28.2 (25 platform packages), `@biomejs/biome` 2.5.8 (8), lightningcss 1.33.0 (9), and turbo 2.6.1 (6). Known failure modes are documented and mitigable: npm lockfile/platform omission (npm/cli#8320, still open), musl needing separate packages, and `--no-optional` needing a download fallback.

**napi-rs into Pi: unverified, and deliberately not taken.** No first-party source confirms loading a `.node` addon through jiti, which is exactly how Pi loads extensions. Biome, the closest structural precedent for one Rust core with two consumption modes, uses WASM rather than napi for its in-process Node path. Prisma shipped Rust engines plus napi from 2.20 through 6.x and removed the architecture entirely in 7.0.0. The seed therefore keeps Pi's hot-path guards in TypeScript over a shared declarative predicate spec, and defers napi to a spike in v6.5.x.

**SQLite from Rust: settled at the source, against both lanes.** One lane claimed `rusqlite` has an `fts5` cargo feature; the other claimed FTS5 requires `LIBSQLITE3_FLAGS=-DSQLITE_ENABLE_FTS5`. Both are wrong. `rusqlite`'s `Cargo.toml` contains no `fts5` feature at all, and `libsqlite3-sys/build.rs:156-163` passes `-DSQLITE_ENABLE_FTS5`, `-DSQLITE_ENABLE_JSON1`, and `-DSQLITE_DEFAULT_FOREIGN_KEYS=1` unconditionally on the bundled path. `features = ["bundled"]` is sufficient and is now locked as engineering decision 4.

**Pi capability boundary: documented, not runtime-probed.** `pi --help` on 0.84.1 describes `--tools` as a "Comma-separated allowlist of tool names to enable" that "applies to built-in, extension, and custom tools", and a separate `--no-builtin-tools` flag exists. A headless probe was attempted and terminated without producing output, so this remains open question 4 in the seed.

**Toolchain readiness.** Rust 1.99.0-nightly with `cargo-nextest`, `cargo-release`, `cargo-component`, `cargo-sqlx`, and the `wasm32-wasip2` target already installed locally. Node 26.7.0. Pi 0.84.1 installed at `/opt/homebrew/bin/pi`.

## Anomalies

1. Eight issues (#261, #262, #263, #266, #267, #268, #269, #270) are marked Fixed in the v6.4.3/v6.4.4 CHANGELOG but remain open in the tracker. Seed open question 1.
2. 86% of open issues carry no milestone, including two production-affecting CLI bugs.
3. No `close.md` or `handoff.md` artifact exists anywhere, including for the run whose own plan defines that schema.
4. README and `plugin.json` disagree on the current version.
5. Two stale docstrings (`__main__.py`, `test_shim_passthrough.py`) claim only `teammate` is ported and must not be read as a scoping signal.
6. `v641-dev0`'s plan deferred deletion of 45 bash scripts and 50 bash tests as "a mechanical follow-up" that never happened.

## Operator decisions taken during planting

| Decision | Choice | Consequence |
|---|---|---|
| Canonical CLI language and Pi binding | Rust core, TypeScript guard layer for Pi | No `.node` addon and no cross-compiled Node binding in this arc |
| Arc scope | Monorepo, CLI, and the Pi adapter together | #279 is pulled from milestone 59 into this arc |

## Residual

`shctx discovery insert` rows were not written; this file and `reports/discovery-mesh-gh.md` are the durable record until the registry is bootstrapped at Phase 0.
