# CODER REPORT — W2-S1: minijinja environment parity

- **Lane:** W2-S1 — minijinja environment parity
- **Skills loaded:** `code-style` (rust.md), `rust`. `context7-mcp` was also invoked per
  the role's "library API uncertainty" rule, but no MCP tool for it was present in this
  session's toolset (only `Bash`/`Edit`/`Read`/`Skill`/`Write`) — could not actually query
  live docs.rs. Fell back to the plan's own pre-confirmed API table plus trained knowledge
  of minijinja's public surface; every point not in that table is called out below as an
  assumption needing compile-time confirmation.
- **Files touched:**
  - `crates/render/src/env.rs` (new)
  - `crates/render/src/filters.rs` (new)
  - `crates/render/src/lib.rs` (modified — added `pub mod env;` unconditionally and
    `#[cfg(feature = "json")] pub mod filters;`; no re-exports added, no other lines
    touched)
- **LOC delta (via `scripts/loc-count.py HEAD .`, the canonical deterministic counter —
  excludes `#[cfg(test)]` bodies per the ONE-LOC rule):**
  - `env.rs`: +67
  - `filters.rs`: +128
  - `lib.rs`: +5
  - **TOTAL: +200 / -0 (net 200)**, vs. `estimated_loc: 190` in the plan — 10 over
    (~5%), after one deliberate trim pass on the module-doc prose. Not escalated as
    `LOC-BUDGET-GOVERNANCE`: this is a normal estimate variance on production code (no
    mandated deliverable was cut to get here — the corpus/negative-control tests that
    make up the bulk of the *file* size are `#[cfg(test)]`-gated and cost 0 toward this
    number). Flagging the number transparently per instruction; not adjudicating it.

## The core design decision (read this first)

The brief instructs: *"Delegate the sort to crates/core's canonical sorted-JSON writer
(`to_canonical_json`, landed in W1-S1) so the workspace has exactly one sort
implementation — do not add a second JSON serializer."* I verified this literally and it
is **not achievable as stated**, for two independent, checkable reasons (both confirmed
by reading `crates/core/src/run.rs` and `crates/core/src/run/canonical.rs`, read-only,
before writing anything):

1. The backing function, `crate::run::canonical::to_canonical_string`, is `pub(crate)`
   inside `shepherd_core` — not reachable from `crates/render` at all, and `crates/core/**`
   is `must_not_touch` for this step regardless, so it cannot be made public either.
2. Even if it were public, its byte format is a *different, deliberate* serialization:
   `RunState::to_canonical_json` reproduces `models_run.py:627`'s
   `json.dump(payload, indent=2, sort_keys=True)` — 2-space indent, `ensure_ascii=True`.
   `render.py:138`'s `_sorted_tojson` is
   `json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)` —
   single-line, space-after-separator, non-ASCII passed through raw. Calling the
   `run.json` writer here would produce the *wrong* bytes even if it compiled.

Resolution: what is actually shared — and what "one sort implementation" is really
about — is that **neither crate implements the recursive sort as code**. Both rely on
the same zero-code mechanism: `serde_json::Map<String, Value>` without the
`preserve_order` feature is a `BTreeMap`, so routing a value through
`serde_json::to_value` sorts every nesting level for free (this is explicitly documented
in `crates/core/src/run/canonical.rs`'s own module docs, and confirmed for this
workspace: root `Cargo.toml:67` pins `serde_json = { default-features = false, ... }`
and `crates/render/Cargo.toml`'s `json` feature list never turns `preserve_order` on).
`crates/render/src/filters.rs` writes only the small, new text-formatting step
(compact separators, `ensure_ascii=False`), which `serde_json`'s own `Serializer` has no
built-in hook for — the sort itself is not reimplemented. This reasoning is written
into `filters.rs`'s module docs verbatim so the decision is reviewable in place, not
just in this report.

I judged this the correct call rather than a `BRIEF-AMENDMENT REQUEST`/halt because the
literal instruction was infeasible without touching `must_not_touch` territory, the
underlying *intent* (no duplicate sort algorithm) is fully honored, and blocking the
whole step on it would have been strictly worse than documenting the deviation for
review. Flagging it prominently here per the report's "anything you could not satisfy"
requirement.

## Second structural decision: `json`-feature gating

`filters.rs`'s implementation is unconditionally dependent on `serde_json`, but
`serde_json` is this crate's **optional** `json` cargo feature (`crates/render/Cargo.toml`:
`json = ["alloc", "dep:serde", "dep:serde_json", ...]`), not part of `default = ["std"]`.
`.github/workflows/rust.yml` runs clippy (`--all-targets -D warnings`) and nextest across
exactly two feature legs, `[default, full]` (`full` = `default + json + tracing`) — so a
`default`-only build of this crate must compile with **zero** reference to `serde_json`.

Consequence: `pub mod filters;` is gated `#[cfg(feature = "json")]` in `lib.rs`, and
`env::build()`'s single `env.add_filter("tojson", crate::filters::sorted_tojson)` call is
gated the same way. Under bare `default`, `build()` still compiles and returns a working
`Environment` — it simply keeps minijinja's builtin `tojson` (HTML-escaped, unsorted).
This is a documented, intentional degradation of the minimal build (no default-feature
caller renders `sprint_dependencies`/`peer_teammate_names` today), not a defect.

**Actionable consequence for verification:** `cargo test -p shepherd-render
filters::tests::sorted_tojson_key_order`, run exactly as written in `[ACCEPTANCE]` with no
`--features` flag, will compile cleanly under `default` but find **zero** matching tests
(the whole module is absent) — not a failure, but not a real check either. Run it with
`--features json` (or `--features full`, matching CI's second leg) to actually exercise
it. `env::tests::matches_python_settings` needs no such flag; it runs under bare
`default` as literally written.

## Exact minijinja API surface used

| Call | Where | Confidence |
|---|---|---|
| `minijinja::Environment::new()` | `env.rs` | High — canonical constructor |
| `Environment::set_undefined_behavior(UndefinedBehavior::Strict)` | `env.rs` | Confirmed by plan's own table |
| `Environment::set_trim_blocks(bool)` / `set_lstrip_blocks(bool)` / `set_keep_trailing_newline(bool)` | `env.rs` | Confirmed by plan's own table |
| `Environment::set_auto_escape_callback(impl Fn(&str) -> AutoEscape)` + `minijinja::AutoEscape::None` | `env.rs` | **Assumption** — the plan's table left autoescape's exact setter unconfirmed ("must be set explicitly", status "—"). This is the one call in this step I could not verify against docs.rs (no MCP tool available). High personal confidence in the name/shape from prior exposure to minijinja, but this is the single highest-risk line in the diff. |
| `Environment::add_filter(&str, fn(Value) -> Result<String, Error>)` | `env.rs` | High — canonical single-arg filter signature |
| `Environment::template_from_str(&self, &str) -> Result<Template, Error>` | `env.rs`, `filters.rs` tests | Confirmed by name in the plan's own D2 note; **assumed `&self` not `&mut self`** — every call site binds `env`/`build()`'s result as non-`mut`. If this is wrong it is a one-token fix (`let mut env`) at each of 4 call sites. |
| `Template::render<S: Serialize>(&self, ctx: S) -> Result<String, Error>` | throughout | High — standard pattern; used with `()`, `minijinja::context!{...}`, and `&serde_json::Value` (all `Serialize`) |
| `minijinja::context!{ key => expr }` macro | `env.rs` test only | High — `macros` feature is enabled in `Cargo.toml` |
| `minijinja::Error::new(ErrorKind, impl Into<String or Cow<'static,str>>)` | `filters.rs` | High — standard constructor shape |
| `minijinja::ErrorKind::UndefinedError`, `minijinja::ErrorKind::InvalidOperation` | `env.rs`, `filters.rs` | High — both are long-standing variants |
| `Error::kind(&self) -> ErrorKind` | `env.rs` test | High |
| `minijinja::Value: serde::Serialize` (via the `serde` cargo feature, already enabled) | `filters.rs` (`serde_json::to_value(&value)`) | High — required for the whole filter design; enabled unconditionally in `Cargo.toml` |

I deliberately avoided `minijinja::Value::from_serialize` and mixing `serde_json::Value`
directly into `context!{}` in test code — both are things I was *less* certain of the
exact call shape for — in favor of routing every test's context through
`&serde_json::Value` (`Serialize` bound only) and exercising `sorted_tojson` exclusively
through `crate::env::build()` + `template_from_str(...).render(...)`, which also makes
the filter tests integration-style (a broken `add_filter` registration fails them too,
not just a broken sort/format).

## Table-test against the frozen corpus (Action 5)

`conformance/cases/render/**` does not exist in this checkout (I read-checked; the step
landing it is not this one). Rather than block on that or hand-transcribe ~9KB of
template output into Rust string literals (a real, checked transcription-risk — see
below), `env::tests::end_to_end_matches_python_corpus` (`#[cfg(feature = "json")]`)
renders all 5 real templates (via `include_str!` reaching into
`services/cli/shepherd_cli/templates/*.j2`, permitted by `file_scope.may_read`) with
representative variable sets and asserts each output's sha256 against a digest I
captured from the **real** `render.py::build_env` + `Template.render` (Python/Jinja2),
run just before writing the Rust — the actual capture commands are reproducible
(`python3 -c "... from shepherd_cli.render import build_env ..."`, using each template's
real variable names). I then **programmatically diffed** every embedded `vars_json`
literal and every embedded sha256 in the finished `env.rs` against a fresh regeneration
of the same Python run, byte-for-byte — this caught the class of error I could not catch
by inspection (a single mistyped character in a hand-copied ~500-char JSON literal).
Both the vars and the digests matched exactly on that automated diff.

Caveat, stated in the test's own doc comment too: every case here compiles via
`template_from_str` (the in-memory path). 4 of the 5 real templates actually render
through a name+loader lookup in production, and the plan's own D2 note says explicitly
not to assume the two paths are byte-identical. This test proves parity for the
`template_from_str` path only — the loader path is untested because this module has no
loader (out of `[FILE-SCOPE]`/produced-interface for this step).

## Negative control (mandated by the spec)

`filters::tests::negative_control_builtin_tojson_diverges` renders the same value through
a plain, un-overridden `minijinja::Environment::new()` (builtin `tojson` active via the
`builtins` feature) and asserts its output differs from `crate::env::build()`'s
registered filter's output — proving the override is load-bearing rather than
coincidentally matching.

## Acceptance predicates

```
cargo test -p shepherd-render env::tests::matches_python_settings
```
Written, not executed (resource discipline — no cargo). Asserts, against expected
strings captured from the real Jinja2 `build_env` on the identical source: trim_blocks +
lstrip_blocks (`"  {% if true %}\nA\n{% endif %}\nB\n"` → `"A\nB\n"`),
keep_trailing_newline (`"line\n"` → `"line\n"`), autoescape=false
(`"R&D <tag> 'quote'"` unchanged), and `UndefinedBehavior::Strict` (an undefined
`{{ missing }}` fails with `ErrorKind::UndefinedError`, matching Jinja2's own
`UndefinedError: 'missing' is undefined` on the same source — verified against a live
`jinja2`/`render.py` run, not assumed).

```
cargo test -p shepherd-render filters::tests::sorted_tojson_key_order
```
Written, not executed. Requires `--features json` (see gating section above) — run
without it, this passes trivially by finding 0 matching tests, which is not a real
check. Expected string verified byte-for-byte against a live `_sorted_tojson` run.

```
conformance/run.sh --impl=rust --suite=render
```
Not achievable from this step in isolation: there is no `--impl=rust` binary yet
(`crates/cli`'s verb surface is W2-S3..S16, not landed) and no `render` suite/corpus
under `conformance/cases/` in this checkout. This is a `W2-GATE`-level predicate, not a
per-step one; `env::tests::end_to_end_matches_python_corpus` is this step's best-effort
substitute proof of the same property, scoped to what this step actually produces.

## Assumptions requiring compile-time confirmation (priority order)

1. `Environment::set_auto_escape_callback` — exact method name/signature (highest risk;
   the plan itself left this unconfirmed).
2. `Environment::template_from_str(&self, ...)` takes `&self`, not `&mut self` (affects
   4 call sites uniformly; one-line fix each if wrong).
3. `minijinja::Error::new(ErrorKind, impl Into<...>)`'s exact bound accepts a `String`
   from `format!`.
4. `add_filter`'s generic bounds accept `fn(Value) -> Result<String, minijinja::Error>`
   directly (I did not wrap it in a closure at the call site).
5. `Sha256::digest(bytes).iter()` yields `&u8` (I dereference explicitly with `*byte`
   rather than relying on a `LowerHex`-on-reference blanket impl I was not certain
   exists).

## Things I could not fully satisfy

- Byte-parity for the loader-rendering path (4 of 5 templates in production) is
  untested by this step, as explained above — no loader exists in `[FILE-SCOPE]` yet.
- `conformance/run.sh --impl=rust --suite=render` cannot be exercised end-to-end from
  this step alone (missing corpus + missing rust CLI binary, both later steps' scope).
- Process exit code 4 on undefined variable is **not** implemented here (correctly, per
  `[NON-GOALS]`-adjacent reasoning: exit codes are a `crates/cli` concern, `must_not_touch`
  for this step). What this step owns and proves is that the render layer surfaces
  `ErrorKind::UndefinedError` distinguishably, which a CLI layer can map to exit 4 later.

## Halts encountered

None. The `crates/core::to_canonical_json` reuse instruction was infeasible as literally
stated (see above) and is documented as a deliberate, reviewable deviation rather than a
halt, since the underlying intent (no duplicate sort implementation) is preserved and
blocking would have cost the whole step for a resolvable documentation gap.

## Summary

Implemented `crates/render/src/env.rs` (`pub fn build() -> minijinja::Environment<'static>`)
and `crates/render/src/filters.rs` (`pub fn sorted_tojson(Value) -> Result<String,
minijinja::Error>`), wired into `lib.rs` with `filters` gated behind the crate's `json`
feature. All five Python `build_env` settings are applied before any template load, the
`tojson` override is hand-written (not the escaping/unsorted builtin) and delegates its
recursive-sort *mechanism* to the same zero-code `serde_json::Map`-ordering property
`crates/core` relies on, and every test literal (5-template corpus digests + the
key-order fixture) was programmatically verified byte-for-byte against a live
Python/Jinja2 oracle rather than hand-transcribed on trust.

- Reporter: coder-W2-S1 @ 2026-08-13T00:00:00Z
