---
title: Central verification audit — W2-S1/W2-S2 (shepherd-render env/filters/manifest)
date: 2026-08-13
auditor: shepherd:auditor
sprint: v645
concern: regression (centralized build-and-test verification, #256 rule 2)
mode: close (single-role central verify, not fanned out)
methodology: superpowers:systematic-debugging (falsify, don't confirm) — every claim below
  is backed by a command actually run in this primary checkout and its verbatim output, not
  by reading the diff or trusting the coder reports' self-described test outcomes.
deliverable: 9 (status: delivered)
---

## Scope reviewed

Uncommitted new files in `/Users/jo3/src/fl03/shepherd` (branch `v6.4.5`, no worktree —
this is the primary checkout, as instructed):

- `crates/render/src/env.rs` (new, +67 LOC) — W2-S1
- `crates/render/src/filters.rs` (new, +128 LOC) — W2-S1
- `crates/render/src/manifest.rs` (new, +116 LOC) — W2-S2
- `crates/render/src/lib.rs` (modified, +10 LOC total across both steps) — wiring only

`git status --short` confirmed these are the only changed/untracked paths under `crates/`
before any command below ran. `df-guard.sh --min=12` passed (13Gi available) before the
first cargo invocation. `CARGO_TARGET_DIR=target/.central` used throughout, serial, no
workspace-wide build ever run, `cargo fix` never invoked.

## Findings summary

CRITICAL=0, HIGH=1, MEDIUM=1, LOW=1

## VERDICT per step

- **W2-S1 (`env.rs`, `filters.rs`): REDO.** Blocking test failure inside the step's own
  file scope (`filters.rs`), on both feature legs CI actually runs.
- **W2-S2 (`manifest.rs`): PASS on its own merits**, but the crate-level gate CI actually
  runs (`cargo test -p shepherd-render --features full`) fails as one binary, so W2-GATE
  cannot go green until W2-S1's REDO lands. Nothing in `manifest.rs` itself needs changing.

## Findings

### FINDING 1 (HIGH) — `filters::tests::negative_control_builtin_tojson_diverges` fails; minijinja's builtin `tojson` is unreachable in this crate under any feature combination

**Hypothesis:** the negative-control test assumes a plain `minijinja::Environment::new()`
(built with this crate's declared minijinja Cargo features) still carries minijinja's
builtin `tojson` filter to diverge against. If minijinja's builtin `tojson` is gated on a
cargo feature this crate never turns on, the test cannot merely "pass trivially" (the
parity-test failure mode the plan explicitly warns about) — it will hard-error instead,
and the identical gap silently breaks the "default features gracefully degrade to the
unsorted/escaped builtin" claim both coder reports and `env.rs`'s own module docs make.

**Falsification — commands run, verbatim output:**

```
$ CARGO_TARGET_DIR=target/.central cargo check -p shepherd-render
   Finished `dev` profile [optimized + debuginfo] target(s) in 6.07s
$ CARGO_TARGET_DIR=target/.central cargo test -p shepherd-render
running 1 test
test env::tests::matches_python_settings ... ok
test result: ok. 1 passed; 0 failed ...
     Running tests/default.rs ...
test provenance_hashing_is_sha256_over_raw_bytes ... ok
test rendering_is_reproducible ... ok
test result: ok. 2 passed; 0 failed ...
```

Bare `default` (no `--features`) is clean — exit 0, exactly as both coder reports predict
(`filters`/`manifest` modules are `#[cfg(feature = "json"/"std"+"json")]`, absent under
default, so only `env::tests::matches_python_settings` runs). This matches CI's first leg.

```
$ CARGO_TARGET_DIR=target/.central cargo test -p shepherd-render --features full
ACTUAL_EXIT: 101
running 7 tests
test env::tests::matches_python_settings ... ok
test filters::tests::sorted_tojson_key_order ... ok
test manifest::tests::digests_reproduce ... ok
test manifest::tests::vars_digest_is_order_independent ... ok
test manifest::tests::undefined_variable_is_hard_error ... ok
test env::tests::end_to_end_matches_python_corpus ... ok
test filters::tests::negative_control_builtin_tojson_diverges ... FAILED

---- filters::tests::negative_control_builtin_tojson_diverges stdout ----
thread 'filters::tests::negative_control_builtin_tojson_diverges' panicked at
crates/render/src/filters.rs:178:14:
template renders: Error { kind: UnknownFilter, detail: "filter tojson is unknown",
name: "<string>", line: 1 }

test result: FAILED. 6 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
error: test failed, to rerun pass `-p shepherd-render --lib`
```

(I initially piped this through `tail` and read a stale `$?` from `tail`, not `cargo
test` — caught and corrected by redirecting to a file and reading cargo's own exit
code directly: `ACTUAL_EXIT: 101`. Re-ran `--features json` alone — same crate features
without `tracing` — identical failure, identical exit 101, ruling out a `tracing`-feature
interaction.)

**Root cause, traced to source, not guessed:**

`crates/render/Cargo.toml`:
```
minijinja = { features = [
  "builtins",
  "macros",
  "multi_template",
  "serde",
], workspace = true }
```
minijinja's own `Cargo.toml` (`~/.cargo/registry/.../minijinja-2.24.0/Cargo.toml`):
```
builtins = []
json = ["serde_json"]
```
and its `src/filters.rs:1135`: `#[cfg(feature = "json")] pub fn tojson(...)`. minijinja's
`builtins` feature is an empty flag that only *enables the registration slot* for the
built-in filter table; the `tojson` filter body itself is compiled only under minijinja's
own `json` feature — a feature namespace entirely separate from `shepherd-render`'s own
`json` cargo feature (`crates/render/Cargo.toml`'s `json = ["alloc", "dep:serde",
"dep:serde_json", "shepherd-core/json"]` never lists `minijinja/json`). **This crate
never turns minijinja's `json` feature on, under any feature combination of its own** —
so `minijinja::Environment::new()`, anywhere in this crate, at any feature leg, has zero
`tojson` filter compiled in, builtin or otherwise.

**Consequences beyond the failing test itself:**

1. `env.rs:56-61`'s own module-doc comment ("without \[the `json` feature\], `env` keeps
   the builtin — HTML-escaped and unsorted — a documented degradation of the minimal
   build") is **factually false** for this dependency configuration. Under bare `default`
   shepherd-render features, `env::build()`'s `#[cfg(feature = "json")]
   env.add_filter("tojson", ...)` line compiles out entirely, and there is no builtin to
   fall back to either — the returned `Environment` has **no `tojson` filter at all**.
   Both coder reports (W2-S1 §"Second structural decision", W2-S2 inherited note) repeat
   the identical false claim.
2. This is not just a documentation defect: it is a real behavioral gap. Per the plan's
   own "Live blast radius" note (§W2-S1 `[CONTEXT-INVENTORY]`), `boot-prompt.md.j2`
   (`peer_teammate_names | tojson`) and `seed.md.j2` (`sprint_dependencies | tojson`,
   `parallel_with | tojson`) use this filter. Any caller that renders either template
   through `env::build()` under bare `default` features gets a hard render error
   (`ErrorKind::UnknownFilter`) instead of the silently-wrong-but-working degraded output
   the documentation promises. Checked current blast radius: `shepherd-sdk` is the only
   in-tree consumer of `shepherd-render` today, and its `json` feature already forwards to
   `shepherd-render?/json` (`crates/sdk/Cargo.toml:74`), so nothing in the workspace
   currently triggers this at runtime — but the crate's own test suite triggers it right
   now, and the next default-feature caller (W2-S3+, `crates/cli`) will too, silently,
   unless this is fixed first.
3. Directly answers the audit brief's checklist item: "does the negative-control test
   exist, and does it actually fail when the override is removed?" — It exists, but it
   does not "fail when the override is removed" in the way it was designed to (proving
   divergence in *output bytes*); it errors out before any comparison happens, because
   there is nothing to diverge against. The test's *intended* falsifiability (per Action
   4: "a parity test that cannot fail is not a parity test") is itself unverifiable as
   currently written, and worse, it currently blocks the whole crate's `full`/`json`
   feature-leg CI gate, which `.github/workflows/rust.yml` runs on every PR per both
   coder reports' own citation.

**Confidence: HIGH** — reproduced twice independently (`--features full`, `--features
json`), root cause traced to exact source lines in both this crate's `Cargo.toml` and
minijinja's own `Cargo.toml`/`filters.rs`, and the panic message is unambiguous
(`UnknownFilter`, not e.g. an assertion mismatch that could be argued about).

**Not blocking, but should ride along with the redo:** the fix most consistent with the
documented intent is adding `minijinja/json` to `crates/render/Cargo.toml`'s `json`
feature list (this restores the builtin the negative-control test needs to diverge
against) — but that is an implementation decision for the redo, not something I changed
or am prescribing as the only option; e.g. the module docs could instead be corrected to
describe the actual (fail-hard, not degrade) behavior, in which case the negative-control
test would need to assert an `Err` on the un-overridden env instead of comparing output
bytes. Either resolves the defect; I did not judge between them since that is coder work.

### FINDING 2 (MEDIUM) — literal plan instruction "delegate to `crates/core`'s canonical sorted-JSON writer" was not followed; verified as genuinely infeasible, but the result is two independently hand-written recursive JSON-tree writers

**Hypothesis:** the coder's claim that `RunState::to_canonical_json`'s backing function
cannot be reused is either (a) an excuse for taking a shortcut, or (b) a verified,
structural constraint. If (b), the deviation is legitimate but still produces literal
code duplication the `[DO-NOT-DUPLICATE]` grep target doesn't catch, because the grep
target (`sha256|sorted_tojson|tojson`) was written to catch a second *hasher* or a second
*tojson symbol*, not a second recursive-serializer *shape*.

**Falsification:**

```
$ grep -n "pub(crate) fn to_canonical_string" crates/core/src/run/canonical.rs
crates/core/src/run/canonical.rs:45:pub(crate) fn to_canonical_string<T>(value: &T) -> serde_json::Result<String>
```
Confirmed `pub(crate)` — genuinely unreachable from `crates/render`, independent of the
`must_not_touch` rule on `crates/core/**` (which would forbid *widening* its visibility
too). Read `crates/core/src/run/canonical.rs` in full: its `write_value`/`write_array`/
`write_object`/`write_json_string` produce 2-space-indented, multi-line,
`ensure_ascii=True` output (`models_run.py:627`'s `json.dump(indent=2, sort_keys=True)`
format) — genuinely byte-different from `render.py:138`'s single-line,
`separators=(", ", ": ")`, `ensure_ascii=False` format that `filters.rs` must produce.
Both claims in the coder report are **independently verified true**, not an excuse.

However: `crates/render/src/filters.rs`'s `write_value`/`write_array`/`write_object`/
`write_json_string` (lines 68-127) are structurally a near-verbatim copy of
`crates/core/src/run/canonical.rs`'s functions of the identical names — same
match-on-`serde_json::Value` shape, same BTreeMap-sort argument, differing only in the
indent/newline/separator/ascii-escape constants. The *sort mechanism* is correctly shared
(zero code, `serde_json::Map` without `preserve_order`, confirmed via `rg -n
preserve_order crates/*/Cargo.toml` — never turned on anywhere in the workspace) — but the
*tree-walking writer* is duplicated as hand-written code across two crates, just
parameterized differently by hand each time. This is real, and a shared
`fn write_json_tree(value, style: JsonStyle, out: &mut String)` helper (living wherever a
future crate boundary allows both callers to reach it) would eliminate it — but neither
step's `[FILE-SCOPE]` permits creating that shared home today (`crates/core/**` is
`must_not_touch` for both W2-S1 and W2-S2).

```
$ rg -n 'sorted_tojson|tojson' crates/render/
# exactly one production symbol: fn sorted_tojson (filters.rs:56), one registration
# site (env.rs:63) — the LITERAL grep target the audit brief specified passes.
$ rg -n 'sha256' crates/
# sha2 confirmed the only hasher crate across crates/render and crates/registry;
# no second hashing crate found.
```

The two literal DO-NOT-DUPLICATE greps specified in the dispatch brief both pass exactly
as asked. This finding is about a duplication class the grep target does not (and was not
designed to) catch — the intent behind `[DO-NOT-DUPLICATE]` ("no second JSON serializer")
is honored for the *sort*, not fully for the *serializer code shape*.

**Confidence: MEDIUM** — the infeasibility claim is HIGH-confidence verified; the
"this is worth deduplicating" judgment is a design opinion, not a provable defect, and the
`[FILE-SCOPE]` constraints genuinely block the obvious fix within either step as scoped.
Not blocking this wave; worth a follow-up issue for whoever owns `crates/core`'s next
touch, so a shared writer utility can be extracted without violating either step's
`must_not_touch`.

### FINDING 3 (LOW) — minor scope-citation inaccuracy in W2-S2's report, no functional effect

W2-S2's coder report justifies not implementing process exit code 4 by citing
`crates/cli/** is must_not_touch here, matching W2-S1's own scoping of the identical
boundary`. Re-read the plan's actual `file_scope.must_not_touch` for W2-S2: `crates/core/**`,
`crates/registry/**` — `crates/cli/**` is **not** listed for W2-S2 (it *is* listed for
W2-S1). `file_scope.exclusive` for W2-S2 is only `crates/render/src/manifest.rs`, so the
coder could not have written to `crates/cli/**` regardless of the `must_not_touch`
wording — no functional consequence, and the render layer correctly cannot call
`std::process::exit` from a library crate documented as "a pure function of (template
bytes, variables)" (`lib.rs:19-24`) either way. Flagging only because the report's stated
justification misquotes its own step's scope declaration.

**Confidence: LOW** — a documentation/citation nit inside a report, not the code itself;
recorded in Open questions territory, not asserted as an actionable finding.

## Verifications (hypotheses disproved — the design held up under test)

1. **All five environment settings apply before the first template load.** Read
   `env::build()` end-to-end: `set_undefined_behavior`, `set_trim_blocks`,
   `set_lstrip_blocks`, `set_keep_trailing_newline`, `set_auto_escape_callback`, and the
   gated `add_filter` all run inside `build()`, which never calls `template_from_str`/
   `add_template` itself. `env::tests::matches_python_settings` (passed, see above)
   exercises `trim_blocks`+`lstrip_blocks`, `keep_trailing_newline`, `autoescape=false`,
   and `UndefinedBehavior::Strict` against expected strings the coder states were captured
   from a live `render.py::build_env` run — I did not re-run the Python oracle myself to
   independently confirm the expected strings, so this is corroborated-by-passing-test,
   not independently re-derived against Python.
2. **`tojson` is hand-written, key-sorted, no HTML escaping** — confirmed by reading
   `filters.rs`'s `write_json_string` (only `"`/`\`/control-char escapes; no `<`/`>`/`&`/
   `'` translation) and by the passing `filters::tests::sorted_tojson_key_order`, which
   exercises exactly the HTML-sensitive-character + nested-unsorted-map case and passed.
3. **The three digests reproduce across two renders in one test.**
   `manifest::tests::digests_reproduce` (passed, full-feature run above) renders the same
   template + vars twice and asserts full `RenderManifest` equality, including each field
   individually — this passed cleanly.
4. **`vars_sha256` canonicalization is order-independent.**
   `manifest::tests::vars_digest_is_order_independent` (passed) parses reversed-key-order
   JSON literals and asserts identical digests.
5. **Exit 4 preservation, at the layer this crate owns.** Neither step implements
   `std::process::exit(4)` (correctly — it's a library, and both `crates/cli` and
   `services/cli` are outside `[FILE-SCOPE]`/exist-but-not-landed respectively). Both
   `env::tests::matches_python_settings`'s undefined-variable assertion and
   `manifest::tests::undefined_variable_is_hard_error` (both passed) confirm the
   distinguishable `ErrorKind::UndefinedError` propagates unsoftened through
   `Error::Template`, which is the render-layer half of the exit-4 contract.
6. **LOC-delta claims.** `python3 scripts/loc-count.py HEAD crates/render` →
   `+67/-0 src/env.rs`, `+128/-0 src/filters.rs`, `+116/-0 src/manifest.rs`,
   `+10/-0 crates/render/src/lib.rs` (git-diff `lib.rs` delta is the sum of both steps'
   `+5` claims), `TOTAL: +321/-0` — matches both coder reports' individually-claimed
   numbers and W2-S2's own stated combined-working-tree total exactly.

## Open questions

- Whether the intended fix for FINDING 1 is "turn on `minijinja/json`" (restores the
  builtin the test needs) or "correct the documentation + change the negative control to
  assert an `Err`, since fail-hard-not-degrade may in fact be the better contract" — a
  design call for the redo, not something I resolved on the auditor's read-only mandate.
- Cross-language byte parity for `vars_sha256` against a **live** Python
  `_canonical_vars_digest` run was not independently re-verified by me (W2-S2's own report
  flags this as not done for the identical reason); `serde_json::to_vec`'s compact-writer
  behavior (no space after separators, no `preserve_order`, no >`0x7F` escaping) is
  well-established library behavior and not independently in question, but the actual
  byte-for-byte cross-language match remains asserted by design reasoning plus a
  self-consistency test, not a captured oracle diff, matching what W2-S1 did for the
  5-template corpus but W2-S2 explicitly did not do for `vars_sha256`.
- `clippy --all-targets -D warnings` (the third leg of `.github/workflows/rust.yml`,
  alongside `check`/`test`) was not run — out of the two-command scope this dispatch
  specified ("Build and test ONLY... Run them ONE AT A TIME"). Given FINDING 1 already
  fails `cargo test`, clippy's status is moot until that redo lands; noted so it isn't
  silently assumed clean.

## Pattern delta

First central-verification pass recorded against this concern shape in this run;
no 3-sprint trend data available. `Systemic risk: none` (single occurrence).

## Grade

Not applicable — this is a centralized build-verification pass (#256 rule 2), not a
close-mode concern audit; no letter grade assigned. Per-step verdicts above are the
authoritative record for the wave gate.

## Grade rationale

N/A (see above). The blocking classification (W2-S1: REDO) rests entirely on a
reproduced, non-flaky `cargo test` exit-101 failure inside W2-S1's own file scope
(`filters.rs`), on both feature legs `.github/workflows/rust.yml` actually runs
(`json` and `full`). W2-S2's own three tests are all green and its design reasoning
(canonicalization via `serde_json::to_vec`, hashing raw bytes for the other two digests,
propagating `UndefinedError` unsoftened) is verified sound; it is blocked only
transitively, by sharing one test binary with W2-S1's regression.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 9 (status: delivered)
- Concern: regression (centralized W2 build/test verification)
- Mode: close (single central-verify pass, not fanned out — #256 rule 2)
- Files reviewed: 4 (env.rs, filters.rs, manifest.rs, lib.rs)
- Findings: CRITICAL=0, HIGH=1, MEDIUM=1, LOW=1
- Verifications (disproved): 6
- Open questions: 3
- GH issues filed: none (read-only; recommend one for FINDING 2's cross-crate writer
  duplication once a coder step touches crates/core again)
- Grade: n/a (centralized verify pass, not close-mode concern audit)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W2-central-verify.md
- Hot-fix-lane recommendations: 1 (W2-S1 redo: fix or re-scope
  filters::tests::negative_control_builtin_tojson_diverges + the false "degrades to
  builtin" doc claim in env.rs; see FINDING 1)
- Sprint-pattern entry: written (audit_findings row id 41, concern=regression, severity=high)
- Agent ID + timestamp: shepherd:auditor (W2-central-verify) @ 2026-08-13T20:35:08Z
```

## VERDICT

**REDO — W2-S1** (`crates/render/src/env.rs`, `crates/render/src/filters.rs`).
Blocking: `cargo test -p shepherd-render --features full` and `--features json` both exit
101, `filters::tests::negative_control_builtin_tojson_diverges` panics with
`ErrorKind::UnknownFilter` — see FINDING 1. This is not a hypothetical or a resource-
discipline unknown; it was compiled and run twice in this checkout, both times failing
identically. A PASS on this step would be a PASS on code that does not build clean under
the CI feature matrix it targets.

**PASS — W2-S2** (`crates/render/src/manifest.rs`), on the step's own merits: all three
of its tests pass, its design claims were independently verified against source (not
just re-asserted), and the plan's `[ACCEPTANCE]` reproducibility property holds. It is
gated from landing standalone only because it shares a test binary with W2-S1's failing
test — once W2-S1's redo lands, re-run `cargo test -p shepherd-render --features full`
once more centrally to confirm the whole crate goes green; do not re-grade `manifest.rs`
itself, nothing in it needs to change.
