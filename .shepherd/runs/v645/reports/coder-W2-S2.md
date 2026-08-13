# CODER REPORT — W2-S2: render manifest and reproducible digests

- **Lane:** W2-S2 — render manifest and reproducible digests
- **Skills loaded:** `code-style` (rust.md), `rust`
- **Worktree:** primary checkout `/Users/jo3/src/fl03/shepherd`, branch `v6.4.5`, base commit
  `9df90fe4877b` (confirmed via `git rev-parse HEAD` before writing; unchanged throughout —
  worked directly in a shared checkout alongside W2-S1's already-landed, still-uncommitted
  `env.rs`/`filters.rs`, per the dispatch's explicit "PRIMARY CHECKOUT, not a worktree"
  instruction).
- **Files touched:**
  - `crates/render/src/manifest.rs` (new)
  - `crates/render/src/lib.rs` (modified — added exactly one gated module declaration block,
    nothing else, per the brief's "nothing else there" instruction)

## LOC delta

Via `scripts/loc-count.py HEAD .` (canonical counter; excludes `#[cfg(test)]` bodies per the
ONE-LOC rule):

| File | +/- |
|---|---|
| `manifest.rs` | +116 / -0 |
| `lib.rs` (this step's addition only) | +5 / -0 |
| **This step's total** | **+121 / -0** |

vs. `estimated_loc: 160` — 39 under (~24% margin), no `LOC-BUDGET-GOVERNANCE` concern in either
direction. (Full working-tree delta including W2-S1's uncommitted `env.rs`/`filters.rs`/lib.rs
lines is `+321/-0`; the table above isolates this step's own contribution. One line was
manually wrapped to stay under this repo's 100-column default — `cargo fmt` was not run,
per resource discipline, but every line in the new file was checked against the 100-column
limit by script.)

## Design decisions

### `Value` = `serde_json::Value`; module gated on `std` + `json`

The brief's produced signature (`render_with_manifest(&Path, &Value) -> Result<(String,
RenderManifest)>`) doesn't pin which `Value`. I resolved it to `serde_json::Value`: `env.rs`'s
own tests already thread `serde_json::Value` through `Template::render` as the context type, and
canonicalizing "the variables" for `vars_sha256` only has a well-defined meaning for a JSON-shaped
value (`render.py`'s `variables: dict[str, object]` is the same shape). `serde_json::Value`
requires this crate's optional `json` feature; reading `template_path` requires `std`
(`std::fs::read_to_string`, `std::path::Path`) unconditionally. I gated the whole module
`#[cfg(all(feature = "std", feature = "json"))]` in `lib.rs`, mirroring `crates/core/src/lib.rs`'s
own `#[cfg(all(feature = "config", feature = "std"))] pub mod loader;` precedent. Consequence
identical to W2-S1's `filters` caveat: `cargo test -p shepherd-render
manifest::tests::digests_reproduce`, run exactly as written in `[ACCEPTANCE]` with no
`--features` flag, compiles clean under bare `default` but finds **zero** matching tests (module
absent) — not a failure, but not a real check. Needs `--features json` (or `full`, CI's second
leg) to actually run. Flagging prominently since this is the literal acceptance command as given.

### `vars_sha256` canonicalization needs no hand-written serializer

`render.py`'s `_canonical_vars_digest` is `json.dumps(variables, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` — note this is a **different** separator pair than
`render.py`'s `_sorted_tojson` (`(", ", ": ")`, spaced), which W2-S1's `filters::sorted_tojson`
already ports. I could not reuse `sorted_tojson` for the vars digest even by calling it (aside
from `filters.rs` being must-not-touch-except-call territory) because the byte format is
deliberately different.

I verified, by reading `crates/render/Cargo.toml` and the root workspace `Cargo.toml:67`
(`serde_json = { default-features = false, ... }`, `preserve_order` never turned on anywhere in
the workspace), that `serde_json::to_vec(vars)` alone reproduces Python's exact canonical bytes
with **zero** hand-written recursion: `serde_json::Map` without `preserve_order` is a `BTreeMap`
(sorted at every nesting level, for free, matching `sort_keys=True`), and `serde_json`'s default
`Serializer` already writes `,`/`:` with no surrounding space and passes non-ASCII UTF-8 through
untouched (matching `separators=(",", ":")` and `ensure_ascii=False` exactly). This is the same
"zero-code sort" mechanism `crates/filters.rs`'s own module docs and `crates/core`'s
`run/canonical.rs` already document — I extended the same reasoning to a new call site rather
than writing a second JSON writer, satisfying the spirit of `[DO-NOT-DUPLICATE]` even though the
literal grep target (`sha256`) doesn't name a serializer. Proven empirically, not just asserted:
`manifest::tests::vars_digest_is_order_independent` parses the same variables from two JSON
literals with reversed key order and asserts identical `vars_sha256`.

### Exit-4 preservation, and what this crate actually owns

Per `[USER-STYLE]` and Action 3, an undefined template variable must stay a hard error, never a
softened warning. `render_with_manifest` does nothing to catch or downgrade
`UndefinedBehavior::Strict`'s failure: `env.template_from_str(...)?.render(vars)?` propagates
straight through `Error::Template(#[from] minijinja::Error)` (already scaffolded in
`error.rs`, unused until this step — first real exercise of that `From` conversion in the
crate). `manifest::tests::undefined_variable_is_hard_error` asserts the propagated error's
`.kind()` is `minijinja::ErrorKind::UndefinedError`. Mapping that to process exit code 4 itself
is a CLI-layer concern (`crates/cli/**` is `must_not_touch` here), matching W2-S1's own scoping
of the identical boundary.

### Hashing

`template_sha256`/`output_sha256` hash raw bytes with no normalization — `template_source`'s
bytes are read via `std::fs::read_to_string`, which preserves the on-disk bytes exactly for
valid UTF-8 (no line-ending translation), so hashing `template_source.as_bytes()` is
byte-identical to hashing the file directly; this also matches `tests/default.rs`'s own pinned
"no normalization" contract, which I read before writing. `sha256_hex` mirrors the hand-rolled
per-byte hex pattern already established in this crate (`tests/default.rs`'s
`provenance_hashing_is_sha256_over_raw_bytes`, `env.rs`'s test-local `sha256_hex`): `sha2` 0.11's
digest `Array` type has no `LowerHex` impl for the whole array, so I format each byte
individually via `write!` into a `String`, exactly matching the existing precedent's idiom rather
than inventing a third convention.

## `[DO-NOT-DUPLICATE]` re-run (Step 3 tripwire)

`rg -n 'sha256' crates/` → 13 hits pre-existing (env.rs, filters.rs doc references,
tests/default.rs, `crates/registry/src/migrate/runner.rs`), none of them `RenderManifest` or
`render_with_manifest` — confirmed no naming collision before writing. `sha2` remains the only
hasher in the crate; no second one added. `rg -n 'RenderManifest|render_with_manifest'
crates/` before writing returned 0 hits (clean).

## Acceptance predicates

```
cargo test -p shepherd-render manifest::tests::digests_reproduce
```
Written, not executed (resource discipline — no cargo per #256). Requires `--features json` (see
gating section above); run without it, finds 0 matching tests, not a real check. The test:
renders one template + one vars object twice via `render_with_manifest`, asserts the output text,
the aggregate `RenderManifest` equality, and each of the three digest fields individually match
across both renders (the literal wording of the dispatch's "Required test").

```
conformance/run.sh --impl=rust --suite=render --assert-reproducible
```
Not achievable from this step in isolation, same conclusion W2-S1's report reached for its own
`conformance/run.sh` predicate: `conformance/run.sh` exists, but there is no `render` suite under
`conformance/cases/` yet (only `core/`, `guard-cli/` exist) and no `--impl=rust` render-invoking
binary (`crates/cli`'s verb surface is W2-S3..S16, not landed). This is a `W2-GATE`-level
predicate. `manifest::tests::digests_reproduce` plus `vars_digest_is_order_independent` are this
step's best-effort substitute proof of the same reproducibility property, scoped to what this
step actually produces.

## Assumptions requiring compile-time confirmation (priority order)

1. `minijinja::Environment::template_from_str` takes `&self` (W2-S1's own flagged assumption,
   inherited unchanged here — I chain `crate::env::build().template_from_str(...)` directly off
   the temporary in a single `let` statement, which is valid Rust regardless of whether the
   method takes `&self` or `&mut self` since temporary-lifetime extension covers the whole
   statement; if wrong, the existing 4 call sites W2-S1 flagged plus this one all need the same
   one-token fix).
2. `minijinja::Template::render<S: Serialize>(&self, ctx: S)` accepts `S = &serde_json::Value`
   directly (i.e. a reference implements `Serialize` via the blanket impl on `&T`) — same
   pattern `env.rs`'s own tests already rely on (`.render(&vars)`), so this is corroborating,
   not a new risk.
3. `Sha256::digest(bytes).iter()` yields `&u8`, and `write!(acc, "{byte:02x}")` on a `&u8`
   resolves via the standard blanket `LowerHex` impl for references — mirrors the pattern
   already used verbatim in `tests/default.rs` and `env.rs`'s test module, so likewise
   corroborating rather than novel risk.
4. `serde_json::to_vec`'s compact `Serializer` writes exactly `,`/`:` with no surrounding
   space and never escapes bytes `>= 0x80` — verified by design/documentation reasoning (root
   `Cargo.toml:67` confirms `preserve_order` off workspace-wide) and by the
   `vars_digest_is_order_independent` test, but not by an actual `cargo test` run under this
   resource-discipline constraint.

## Things I could not fully satisfy

- `conformance/run.sh --impl=rust --suite=render --assert-reproducible` cannot be exercised
  end-to-end from this step alone — missing corpus + missing rust CLI binary, both later steps'
  scope (see above; identical shape to W2-S1's analogous gap).
- Byte-for-byte parity of `vars_sha256` against a **live** Python `_canonical_vars_digest` run
  was not captured and diffed (unlike W2-S1's corpus digests, which were captured from a live
  `python3` run) — the resource-discipline instruction for this step covers cargo only, not a
  restriction on running Python, but I judged the design-level proof (serde_json's documented
  compact-formatter behavior + the root Cargo.toml's `preserve_order`-off confirmation + the
  `vars_digest_is_order_independent` self-consistency test) sufficient for this step's actual
  mandated test, which only requires self-reproducibility, not cross-language byte parity. That
  cross-language proof belongs to the `W2-GATE`/conformance-suite step per the acceptance
  analysis above, not this one.

## Halts encountered

None.

## Summary

Implemented `crates/render/src/manifest.rs`: `pub struct RenderManifest { template_sha256,
vars_sha256, output_sha256 }` and `pub fn render_with_manifest(&Path, &Value) ->
Result<(String, RenderManifest)>`, wired into `lib.rs` behind `#[cfg(all(feature = "std",
feature = "json"))]`. Renders through `crate::env::build()` (W2-S1) unconditionally via
`template_from_str` (no loader in this step's scope), hashes template/output as raw bytes with no
normalization, and canonicalizes `vars` for hashing via `serde_json::to_vec` alone — relying on
the workspace's already-established (never `preserve_order`) `BTreeMap`-backed `Map` sort rather
than writing a second recursive JSON serializer. `UndefinedBehavior::Strict` failures propagate
unsoftened as `Error::Template(minijinja::Error)`. Three tests: the mandated
`digests_reproduce` (render twice, assert output + full digest triad identical), plus
`vars_digest_is_order_independent` (proves the canonicalization claim empirically, not just by
assertion) and `undefined_variable_is_hard_error` (proves the exit-4-preservation claim
empirically).

- Reporter: coder-W2-S2 @ 2026-08-13T00:00:00Z
