# Wave 2 — models vertical + exact key provenance — CONDUCTOR-VERIFIED PASS

Every gate re-broken by the conductor. None accepted from the coder's report.

## Acceptance — deliverable 8

`shepherd models show --md` renders portable tiers; `--harness <h> --md` renders the harness-native
table. Measured on the rebuilt binary:

| role | portable | claude | codex | pi |
|---|---|---|---|---|
| root | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| planter | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| engineer | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| conductor | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| critic | `standard` | `sonnet` | `standard` | `sonnet` |
| discovery | `standard` | `sonnet` | `standard` | `sonnet` |
| coder | `standard` | `sonnet` | `standard` | `sonnet` |
| auditor | `standard` | `sonnet` | `standard` | `sonnet` |
| worker | `standard` | `sonnet` | `standard` | `sonnet` |

The operator's table exactly, for all three harnesses.

`economy` is expressible without being a default. With `[models] discovery = "economy"`:
```
claude  haiku
codex   economy
pi      haiku
source: config
```

## Acceptance — deliverable 6 closed

```
$ grep -c "toml::" crates/cli/src/cmd/wave_a_models.rs
0        # was 2
```
Lane scoreboard: `loader.rs` 0 (was 15), `wave_a_models.rs` 0 (was 2), `guard/parser.rs` 22 and
correctly untouched.

## GATE — explicit-default-value provenance

The test that discriminates the exact design from the approximation root banned. Falsified by
swapping `explicit_models` to the default-comparison:

RED:
```
test models_show_explicit_default_value_still_reports_source_config ... FAILED
an explicitly configured role must report source: config even when its value equals the default
test result: FAILED. 0 passed; 1 failed
```
GREEN after restore: `ok. 1 passed`.

Implementation is real provenance, not comparison: `LoadedConfig::explicit_keys`
(`crates/core/src/loader.rs:78`) collected by `collect_dotted_keys` (`:190`), carried on
`ExecutionContext::explicit_keys` (`crates/cli/src/context.rs:312`), consumed by `explicit_models`.

Behavioural confirmation:

| config | rendered source |
|---|---|
| `discovery = "standard"` (equals default) | `config` |
| `coder` absent | `default` |

## GATE — root exclusion from the codex `[agent_types]` table

Root explicitly required this pin. Falsified by flipping `content/roles/shepherd.md` to
`reasoning-high` and running the prebuilt test binary directly (so `build.rs` could not mask the
result with its own panic):

RED:
```
test codex_agent_types_never_names_root ... FAILED
root (role id `shepherd`) must never appear in the codex [agent_types] table:
shepherd = "worker"
```
GREEN after restore.

That output is the concrete harm plan §7 predicted: root enrolled as a spawnable codex agent of
type `worker`. With role guard rules now live (7d5492e, 587fcfa) that is an enforcement change,
not a cosmetic one. The test compiles from the LIVE `content/` tree rather than a frozen fixture,
so it cannot rot into a snapshot.

## Full suite

```
cargo clippy --workspace --all-targets --locked -- -D warnings   # clean
cargo test -p shepherd-core --features="std parse json config"   # 5/4/15/66/24/7/6, 0 failed
cargo test -p shepherd-cli --test wave_a_models_cli              # 9 passed
cargo test -p shepherd-compiler                                  # 5/7/4, 0 failed
cargo test -p shepherd-cli --test migrate_layout                 # 9 passed  (acceptance)
cargo test -p shepherd-registry                                  # 12/4/16/8, 0 failed (acceptance)
python3 scripts/generate-compiler-package-content.py --check     # ok: 23 byte-exact sources
```

`cargo fmt --all -- --check` lists only `wave_c_bootstrap.rs` and `wave_c_bootstrap_cli.rs`, both
the identity lane's and deliberately untouched.

## Containment

10 files, +747/-153. `content/roles/shepherd.md` untouched. `crates/cli/src/cmd/{dispatch,
wave_c_bootstrap,wave_f_knowledge}.rs` are the identity lane's and were not touched.

## CONDUCTOR ERROR — recorded because it nearly caused a wrong REDO

The first provenance check rendered `source: "default"` for a role explicitly set to its default,
which is exactly the banned behaviour. The conclusion was wrong: the CLI binary was STALE relative
to the coder's in-flight edits. After `cargo build -p shepherd-cli` the same command rendered
`source: "config"`.

**Rule: rebuild before any behavioural check while coders are in flight.** A stale artifact
attributes a build state to a coder's work. This is the same class as reading one `git status`
sample as a fact about a lane. Both happened tonight.

## Verdict

**PASS.**
