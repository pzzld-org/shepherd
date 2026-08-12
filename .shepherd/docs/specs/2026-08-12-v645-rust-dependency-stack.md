# v6.4.5 — Rust dependency stack (locked)

**Status:** locked for the v6.4.5 arc · **Date:** 2026-08-12 · **Seed:** `.shepherd/runs/v645/seed.md`

Every entry below was checked against current documentation through Context7 rather than recalled. Adding a crate outside this list is a critic-RED escalation, not a sprint-time judgment call.

## The stack

| Concern | Decision | Rationale |
|---|---|---|
| Arg parsing | **`clap`** (derive + builder) | `override_help` and `override_usage` reproduce exact legacy strings; see §1 |
| SQLite | **`rusqlite`**, `features = ["bundled"]` | Sync, zero system deps, FTS5/JSON1 free; see §2 |
| Migrations | **hand-ported runner**, no crate | `rusqlite_migration` forks the ledger; see §3 |
| Async runtime | **none** | Nothing in the hot path is concurrent I/O; see §4 |
| HTTP | **none** | GitHub access stays on the `gh` CLI; see §5 |
| Templating | `minijinja` | Closest Jinja2 semantics, `StrictUndefined` equivalent |
| Serialization | `serde`, `serde_json`, `toml`, `serde_yaml` | `serde_yaml` used only for the `## Stage Graph` block in `plan.md` |
| Hashing | `sha2` | `template_sha256`, `vars_sha256`, `output_sha256` lineage |
| Testing | `cargo-nextest`, `insta` | Snapshot assertions replace the absent golden corpus |

## 1. clap, and a correction to the seed's risk model

The port-hostility survey ranked the 29 "bash-parity variadic" modules as the single hardest item, on the reasoning that no modern arg parser will agree to emit an exact predetermined string. **That reasoning is wrong.** `clap` supports it directly:

- `Command::override_help(...)` — "Overrides the clap generated help message for both `-h` and `--help`." Per-command, so subcommands keep generated help unless individually overridden. That granularity matches the per-module shape of the problem exactly.
- `Command::override_usage(...)` — replaces the auto-generated usage string, disabling context-aware generation.

So the 29 modules become `override_help` with the captured legacy string, not 29 hand-rolled `argv` loops. This lowers the verb-surface risk materially. The seed's XL sizing stands as a deliberate conservatism, not as a claim that the mechanism is unavailable.

**One real constraint remains.** `clap::Error::exit` prints to stderr and exits `2`, or prints to stdout and exits `0`. Shepherd's verbs use a wider code set (`4` render failure, `5` already-exists, `6` layout drift). The CLI must therefore use `try_parse()` and map errors onto shepherd's own codes rather than letting clap terminate the process. Exit-code parity is a conformance case, not an implementation detail.

## 2. rusqlite over sqlx

Both compile the same C library: sqlx's `sqlite` feature statically links via `libsqlite3-sys`'s `bundled` feature, which is what `rusqlite`'s `bundled` does. The difference is the runtime, and it is decisive.

> SQLx supports both the Tokio and async-std runtimes... The use of nearly any async function in the API will panic without at least one runtime feature enabled. The SQLite driver is runtime-agnostic, but `SqlitePool` requires runtime support for timeouts and spawning internal management tasks.

The measurable outcome this arc is chasing is startup latency: the Python CLI costs roughly 75ms and hooks fire per tool call. Paying async runtime initialization to read one row and exit moves that number the wrong way. `sqlx`'s compile-time query checking also needs a live `DATABASE_URL` or a committed offline cache at build time, which adds CI surface for a schema that is already frozen SQL.

`features = ["bundled"]` is sufficient and complete. Verified at `libsqlite3-sys/build.rs:156-163`: the bundled path passes `-DSQLITE_ENABLE_FTS5`, `-DSQLITE_ENABLE_JSON1`, and `-DSQLITE_DEFAULT_FOREIGN_KEYS=1` unconditionally. There is **no `fts5` cargo feature** on `rusqlite`; asserting one is a build-time error.

`busy_timeout(Duration)` is a first-class method, covering the existing `PRAGMA busy_timeout=5000`. `transaction_state` and parts of `DbConfig` require `modern_sqlite`, which `bundled` already implies.

## 3. Reject rusqlite_migration

The crate is well-regarded and wrong for this schema:

> ...fast database opening by using the SQLite `user_version` integer at a fixed offset in the file to track migration state, avoiding the overhead of additional tables.

Shepherd tracks applied migrations in a **`schema_versions` table**, and both the bash and Python runners read it. Switching to `user_version` would fork the migration ledger mid-parity-window, break the cross-harness shared registry, and silently invalidate the conformance check that compares `schema_versions` rows between implementations. Port the existing runner; the 20 migration `.sql` files stay verbatim.

## 4. No async runtime

`tokio` earns its place when a process multiplexes concurrent I/O over a long life. Neither condition holds. The CLI reads or writes a local SQLite file and exits, and lane fan-out is process spawning, which `std::process` plus threads covers. Adding `tokio` would impose runtime startup on the guard path this arc exists to make fast.

Revisit only if a long-lived daemon is introduced, which is explicitly a v6.5.x non-goal.

## 5. No HTTP client

`[cli].gh = true` and the standing MCP-over-CLI principle mean GitHub access goes through the `gh` binary, which already owns auth, pagination, and rate limiting. Pulling in `reqwest` means reimplementing all three plus a TLS decision, to replace a dependency already installed and authenticated on every machine that runs shepherd.

If a future need is proven, the shape is `reqwest` with `blocking` and `rustls-tls`, never the async client, for the reason in §4.

## Consequences for the arc

1. The registry sprint carries no ORM and no async migration; it is `rusqlite` plus the ported table-based runner.
2. The verb-surface sprint gains `override_help` as its parity mechanism and loses the hand-rolled-argv assumption.
3. Exit-code mapping is an explicit conformance suite, since clap's defaults do not match shepherd's codes.
4. The dependency tree stays small enough that cross-compiling the npm platform matrix is a build concern, not a linking one.
