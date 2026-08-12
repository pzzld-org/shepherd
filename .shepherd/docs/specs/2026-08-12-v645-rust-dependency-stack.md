# v6.4.5 — Rust dependency stack (locked)

**Status:** locked for the v6.4.5 arc · **Date:** 2026-08-12 · **Seed:** `.shepherd/runs/v645/seed.md`

Every entry below was checked against current documentation through Context7 rather than recalled. Adding a crate outside this list is a critic-RED escalation, not a sprint-time judgment call.

## The stack

| Concern | Decision | Rationale |
|---|---|---|
| Arg parsing | **`clap` 4** (derive + builder) | `override_help` and `override_usage` reproduce exact legacy strings; see §1 |
| SQLite | **`rusqlite` 0.40**, `features = ["bundled"]` | Sync, zero system deps, FTS5/JSON1 free; see §2 |
| Migrations | **hand-ported runner**, no crate | `rusqlite_migration` forks the ledger; see §3 |
| Async runtime | **none** | Removed from the scaffold; see §5 |
| HTTP | **none** | GitHub access stays on the `gh` CLI; see §6 |
| **Config layering** | **`config` 0.15**, `default-features = false, features = ["toml"]` | Collapses the duplicated precedence chain to one implementation; see §4 |
| **Config schema** | **`schemars` 1** | Generates the known-key universe that the validator checks against; see §4 |
| TOML writing | `toml` 1 | `config` reads but does not serialize; `config init` writes |
| Templating | `minijinja` 2 | Closest Jinja2 semantics, `StrictUndefined` equivalent |
| Serialization | `serde`, `serde_json` | `serde_yaml` only if the `## Stage Graph` block stays YAML |
| Hashing | `sha2` 0.11 | `template_sha256`, `vars_sha256`, `output_sha256` lineage |
| Errors | `anyhow`, `thiserror` 2 | Library errors typed, binary errors contextual |
| Identifiers | `uuid` 1, `features = ["serde", "v7"]` | `project.json` carries a UUIDv7 project id |
| Time | `chrono` 0.4, `features = ["clock", "serde", "std"]` | `run.json` `updated_at` must round-trip int, float and ISO8601 |
| Diagnostics | `tracing`, `tracing-subscriber` | Structured logs into `.shepherd/logs/` |
| Testing | `cargo-nextest`, `insta` | Snapshot assertions replace the absent golden corpus |

**Dependency floor: 101 packages.** The scaffold resolved 201. Removing `sqlx`/`tokio` took it to 128; restricting `config` to `features = ["toml"]` took it to 101, since its defaults pull `json`, `yaml`, `ini`, `ron`, `json5`, `convert-case`, and `async` — and `async` drags in `async-trait` against the no-runtime decision while `ini` alone pulls `rust-ini` → `ordered-multimap` → `dlv-list` → `const-random` → `getrandom`. shepherd.toml is the only format shepherd has ever read. Treat 101 as a ceiling to defend, not a floor to grow from.

The two transitive names that look like residue and are not: `lazy_static` (via `sharded-slab` ← `tracing-subscriber`) and `wasm-bindgen` (via `js-sys` ← `sqlite-wasm-rs` ← `rusqlite`, a wasm32-only target dep never compiled natively).

**Workspace layout is `cli/` at the repository root**, not `crates/cli`. Members are declared in the root `Cargo.toml` with `resolver = "3"`, edition 2024, `rust-version = "1.96.0"`.

## 1. clap, and a correction to the seed's risk model

The port-hostility survey ranked the 29 "bash-parity variadic" modules as the single hardest item, on the reasoning that no modern arg parser will agree to emit an exact predetermined string. **That reasoning is wrong.** `clap` supports it directly:

- `Command::override_help(...)` — "Overrides the clap generated help message for both `-h` and `--help`." Per-command, so subcommands keep generated help unless individually overridden. That granularity matches the per-module shape of the problem exactly.
- `Command::override_usage(...)` — replaces the auto-generated usage string, disabling context-aware generation.

So the 29 modules become `override_help` with the captured legacy string, not 29 hand-rolled `argv` loops. This lowers the verb-surface risk materially. The seed's XL sizing stands as a deliberate conservatism, not as a claim that the mechanism is unavailable.

**One real constraint remains.** `clap::Error::exit` prints to stderr and exits `2`, or prints to stdout and exits `0`. Shepherd's verbs use a wider code set (`4` render failure, `5` already-exists, `6` layout drift). The CLI must therefore use `try_parse()` and map errors onto shepherd's own codes rather than letting clap terminate the process. Exit-code parity is a conformance case, not an implementation detail.

## 2. rusqlite over sqlx

Both compile the same C library: sqlx's `sqlite` feature statically links via `libsqlite3-sys`'s `bundled` feature, which is what `rusqlite`'s `bundled` does. The difference is the runtime, and it is decisive.

> SQLx supports both the Tokio and async-std runtimes... The use of nearly any async function in the API will panic without at least one runtime feature enabled. The SQLite driver is runtime-agnostic, but `SqlitePool` requires runtime support for timeouts and spawning internal management tasks.

**Correction to an earlier draft of this document.** It argued that `tokio` would meaningfully damage the startup budget. That was overstated: a `current_thread` runtime initializes in well under a millisecond, nowhere near the ~75ms the Python CLI costs. The startup argument is not why `rusqlite` wins, and pretending otherwise would have made this decision look better-founded than it was.

The real reasons are narrower and hold up. The registry is a local file opened by 32 guard scripts, not a network pool, so connection pooling and async I/O buy nothing at this boundary. Choosing `sqlx` makes `tokio` mandatory rather than optional, since nearly any async function panics without a runtime feature. And `sqlx`'s compile-time query checking needs a live `DATABASE_URL` or a committed offline cache at build time, which adds CI surface and a re-verification step every time schema SQL changes, for a schema that is already frozen.

Operator decision, 2026-08-12: `rusqlite`, drop `sqlx` and `tokio`. Both were present in the initial workspace scaffold (`sqlx 0.9` enabled with `derive, macros` only, so no driver and no runtime were ever wired) and have been removed from `Cargo.toml` and `cli/Cargo.toml`.

`features = ["bundled"]` is sufficient and complete. Verified at `libsqlite3-sys/build.rs:156-163`: the bundled path passes `-DSQLITE_ENABLE_FTS5`, `-DSQLITE_ENABLE_JSON1`, and `-DSQLITE_DEFAULT_FOREIGN_KEYS=1` unconditionally. There is **no `fts5` cargo feature** on `rusqlite`; asserting one is a build-time error.

`busy_timeout(Duration)` is a first-class method, covering the existing `PRAGMA busy_timeout=5000`. `transaction_state` and parts of `DbConfig` require `modern_sqlite`, which `bundled` already implies.

### Verified by runtime probe, not inference

Built against `rusqlite 0.40.2` with `bundled` and executed 2026-08-12. Bundled SQLite is **3.53.2**:

| Check | Result |
|---|---|
| `ENABLE_FTS5` in `PRAGMA compile_options` | PRESENT |
| `ENABLE_JSON1` in `PRAGMA compile_options` | **ABSENT** |
| `DEFAULT_FOREIGN_KEYS` in `PRAGMA compile_options` | PRESENT |
| FTS5 external-content table, `tokenize='unicode61 remove_diacritics 2'`, `MATCH` query | 1 hit, works |
| `CHECK(json_valid(...))` rejecting a non-JSON insert | ENFORCED |
| `Connection::busy_timeout(5s)` | OK |

**The `ENABLE_JSON1` row is a trap and is recorded so nobody re-derives it.** The flag is absent from `compile_options` while `json_valid()` works correctly, because SQLite folded the JSON functions into core at 3.38.0 (2022) and the build flag became a no-op. An acceptance check asserting `ENABLE_JSON1` appears in `compile_options` will fail against a perfectly good build. Assert the **behavior** (`json_valid` rejects) rather than the flag. Only `ENABLE_FTS5` is meaningful to assert by flag.

## 3. Reject rusqlite_migration

The crate is well-regarded and wrong for this schema:

> ...fast database opening by using the SQLite `user_version` integer at a fixed offset in the file to track migration state, avoiding the overhead of additional tables.

Shepherd tracks applied migrations in a **`schema_versions` table**, and both the bash and Python runners read it. Switching to `user_version` would fork the migration ledger mid-parity-window, break the cross-harness shared registry, and silently invalidate the conformance check that compares `schema_versions` rows between implementations. Port the existing runner; the 20 migration `.sql` files stay verbatim.

## 4. config + schemars for configuration

**Adopted.** `config` 0.15 is the layering engine and `schemars` supplies the key universe. Together they retire the single worst duplication in the current codebase.

### What `config` fixes

Config precedence is implemented **twice today** and required to stay byte-identical by hand: `hooks/scripts/_lib.sh:shctx_config_files()` in bash and `config.py::_config_search_paths` in Python. That is two owners of one truth, which is the exact bug class the v6.4.4 release was spent collapsing. `config`'s builder makes the chain declarative and single-sourced:

```rust
Config::builder()
    .add_source(File::from_str(BUNDLED_DEFAULTS, FileFormat::Toml))
    .add_source(File::new(&user_toml,    FileFormat::Toml).required(false))
    .add_source(File::new(&project_toml, FileFormat::Toml).required(false))
    .add_source(File::new(&harness_toml, FileFormat::Toml).required(false))
    .add_source(File::new(&local_toml,   FileFormat::Toml).required(false))
    .add_source(Environment::with_prefix("SHEPHERD").separator("__"))
    .build()?
```

`required(false)` matches the existing semantics exactly: an absent tier is skipped, not an error. Last source wins, which is the documented precedence order.

### What `config` does not give us

Shepherd's `config validate` reports **every** unknown key with a did-you-mean suggestion, attributed to the tier it came from. `config` merges all sources into one tree before deserializing, and `#[serde(deny_unknown_fields)]` aborts on the first offender rather than collecting. So the validator stays custom. It is now custom over generated data rather than over 29 hand-written model classes:

1. `schemars::schema_for!(Settings)` yields the authoritative known-key set. No hand-maintained key list can drift from the struct.
2. Build one `Config` **per tier** to walk each file's keys separately, which preserves the per-tier attribution the merged view loses.
3. Levenshtein against the schema key set produces the suggestion.

`ConfigError::FileParse { uri, cause }` and `ConfigError::Type { key, expected, .. }` carry origin information, so parse and type errors already name their file without extra work. Only the unknown-key sweep needs the per-tier pass.

### Consequences

- `toml` is a separate dependency because `config` reads but does not serialize, and `config init` writes a file.
- The bash `shctx_config_files()` implementation is deleted, not ported. Its behavior becomes conformance cases.
- Adding a config key means adding a struct field. The schema, the validator, and the key universe follow automatically.

## 5. No async runtime

`tokio` earns its place when a process multiplexes concurrent I/O over a long life. Neither condition holds. The CLI reads or writes a local SQLite file and exits, and lane fan-out is process spawning, which `std::process` plus threads covers. Adding `tokio` would impose runtime startup on the guard path this arc exists to make fast.

Revisit only if a long-lived daemon is introduced, which is explicitly a v6.5.x non-goal.

## 6. No HTTP client

`[cli].gh = true` and the standing MCP-over-CLI principle mean GitHub access goes through the `gh` binary, which already owns auth, pagination, and rate limiting. Pulling in `reqwest` means reimplementing all three plus a TLS decision, to replace a dependency already installed and authenticated on every machine that runs shepherd.

If a future need is proven, the shape is `reqwest` with `blocking` and `rustls-tls`, never the async client, for the reason in §4.

## Consequences for the arc

1. The registry sprint carries no ORM and no async migration; it is `rusqlite` plus the ported table-based runner.
2. The verb-surface sprint gains `override_help` as its parity mechanism and loses the hand-rolled-argv assumption.
3. Exit-code mapping is an explicit conformance suite, since clap's defaults do not match shepherd's codes.
4. The dependency tree stays small enough that cross-compiling the npm platform matrix is a build concern, not a linking one.
