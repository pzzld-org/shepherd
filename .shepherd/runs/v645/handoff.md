# v6.4.5 handoff — for codex-shepherd

- **Date:** 2026-08-14 · **Handoff for:** codex-shepherd
- **Repo:** `FL03/shepherd` · **Branch:** `v6.4.5` · **PR:** #273 · **HEAD:** `31ad5f9`
- **State:** halted mid-sprint on usage exhaustion, tree clean, full gate green, everything pushed
- **Grade:** C (close-swarm completeness auditor)
- **Companion:** `.shepherd/runs/v645/carry-forward.md` (every unfixed defect, with evidence)
  and `dogfood.md` (80 numbered rows found against the framework while it ran)

Read this file, then `carry-forward.md` §0. Do not start anywhere else.

---

## 1. The one thing that matters

**The guard engine is written in Python and it must be in Rust.**

Rust exists in this workspace for one reason: compile once, target anything, stop rewriting the
system when the host language changes (next target: TypeScript). That is the whole premise of
v6.4.5, whose seed theme is *"the CLI stops being a rewrite target."*

The execution session built the guard predicate engine — the newest and most load-bearing
component in the repo — in **Python**, at `services/cli/shepherd_cli/predicates.py` +
`commands/guard.py`, ~1,400 lines. It then built three harness adapters relaying to it and a
socket broker to make the relay fast enough to call.

```
$ git diff c719ef3..HEAD -- crates/
(empty)
```

Zero Rust across the entire session. Consequences:

| | |
|---|---|
| #266 (retire Python/bash) | **moved backward** — 132 `.py` under `services/cli`, 102 poetry refs |
| #239 (`--impl=rust` green, zero skips) | still `0 cases implemented, exit 1` |
| wasm / TypeScript reuse | impossible — a Python engine cannot compile to wasm |
| a single guard decision | crosses 4 language boundaries (JS → bash → poetry → Python) |

### What to build

A workflow brief specifying this in full was authored and killed mid-flight. It is preserved at:

```
~/.claude/projects/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/
  workflows/scripts/v645-w15-guard-in-rust-wf_45e00295-457.js
```

Summary of it:

1. **`crates/core/src/guard/`** — the evaluator. Pure: predicates in, verdict out. Compiles
   under the `alloc` floor with only `parse` (TOML) + `json`. **No `clap`, no `anyhow`, no
   `std::process`, no branching on `Harness`** — `crates/core/src/lib.rs` documents that
   boundary and an `engine-boundary` CI job enforces it. Filesystem loading goes behind a
   `std` gate, exactly as `RunState::load` is.
   **`cargo check -p shepherd-core --target wasm32-unknown-unknown` must stay green with the
   guard module linked.** That target is the entire reason Rust was chosen; if it breaks, the
   port has failed even if the tests pass.
2. **`crates/cli/src/cmd/guard.rs`** — `eval` / `test` / `serve`. This crate has exactly one
   subcommand today (`Init`); `cmd/init.rs` is the only prior art for the shape. The crate
   names `shepherd` (the umbrella), never `shepherd-core` — a workspace invariant enforces it,
   so the guard module needs re-exporting through the umbrella.
3. **Conformance** — register the Rust impl so `--impl=rust --suite=guard-cli` runs byte-clean
   against `--impl=python`. `conformance/runner.py` already supports two impls by design;
   `NORMALIZATION.md` pins what may vary (timestamps, uuids, abs paths, locale). Anything else
   differing means Rust is wrong.
4. **Only then** delete the Python engine. It is the oracle until the corpus is byte-clean —
   the same relationship `models_run.py` already has with `crates/core/src/run.rs`.

### The contract the Rust engine must satisfy

Read `services/cli/shepherd_cli/predicates.py` and `commands/guard.py` in full first. Where
Rust and Python disagree, **Rust is wrong until proven otherwise**; a genuine Python bug is a
finding to report, never a licence to diverge quietly.

```
shepherd guard eval   one JSON object on stdin, one on stdout. Exit 0 when a verdict was
                      REACHED (allow, deny, or unresolved alike). Non-zero = ENGINE failure,
                      never a verdict.
shepherd guard test   replay every [[example]] in content/predicates/*.toml, assert decision
                      AND halt_code. Print "N/M examples passed".
                      EXIT NON-ZERO ON ZERO EXAMPLES LOADED — see §4.
shepherd guard serve  long-lived, line-delimited JSON over stdio, predicates parsed once,
                      {"ready":true} sentinel on start. A malformed line gets an error
                      response and the server STAYS UP.
```

Request — two shapes, discriminated by the presence of `predicate`:

```jsonc
// (a) normalized
{"harness":"...","role":"coder","predicate":"write-boundary","action":"fs.write","context":{...}}
// (b) raw tool call — the engine does the tool -> (predicate, action, context) mapping
{"harness":"claude|codex|pi","role":"coder"|null,"tool_name":"Bash","tool_input":{...}}
```

Response — exactly one of three:

```jsonc
{"decision":"allow"}
{"decision":"deny","predicate":"...","rule":"...","halt_code":"...","reason":"..."}
{"decision":"unresolved","reason":"...","missing":["role"]}
```

`unresolved` is load-bearing: a guard that cannot identify the acting role must neither
silently allow nor blanket-deny. Each adapter picks its own posture for it, loudly.

Shape (b) needs the git-subcommand tokenizer (`READONLY_GIT_VERBS` allowlist + the
option-takes-an-argument set that stops `git -C x commit` misparsing `x` as the subcommand).
Port it from the Python, which ported it from `hooks/scripts/coder_git_guard.sh`. **Do not
write a fourth copy from scratch.**

Halt codes are harvested at load from the TOML's own `[[example]].halt_code` fields. Never
invent one; a rule with no example-attested halt code emits none.

**The good news:** `content/predicates/*.toml` carries 17 `[[example]]` cases (8 allow, 9 deny)
that are the conformance spec. That corpus makes this port mechanical rather than exploratory,
and it is honestly the most valuable thing this sprint produced.

---

## 2. Unfixed, in priority order

### CRITICAL — security and data integrity

| GH | Defect | State |
|---|---|---|
| [#295](https://github.com/FL03/shepherd/issues/295) | `cmd_teammate.sh` `status`/`retire` interpolate an unescaped teammate name into SQL. Proven: mass UPDATE, WHERE-bypass read. The same file defines a **correct** `esc()` at line 24 and uses it correctly at line 215. | **UNVERIFIED** |
| [#291](https://github.com/FL03/shepherd/issues/291) | `cmd_init.sh` interpolates the repo dirname unescaped. Proven arbitrary-SQL execution — an apostrophe in a directory name is the exploit. | **UNVERIFIED** |
| [#297](https://github.com/FL03/shepherd/issues/297) | `cmd_report.sh` interpolates 5 CLI flags with **zero** escaping. UNION exfiltration from any registry table, proven. | **UNVERIFIED** |
| [#296](https://github.com/FL03/shepherd/issues/296) | The broken `${v//'/''}` idiom #285 called "duplicated 3 times" recurs in **20 sites across 8 files**. | partial, no gate prevents a 9th copy |
| [#294](https://github.com/FL03/shepherd/issues/294) | `run.json` has no write serialization. Two barrier-synchronized OS processes each registering a lane: **one lane silently vanished**. `/shepherd:spawn` registers lanes concurrently by design. | `models_run.py` mid-edit when halted |

**Every row above was killed mid-remediation.** The wave fixing them (W14) was stopped before
its auditor ran. `hooks/tests/test_sql_escaping.sh` reports 20/20 but **nothing verified that
independently**. Re-run each issue's own exploit payload before trusting any of it.

### HIGH

- **[#290](https://github.com/FL03/shepherd/issues/290)** — `packages/scripts/check-deps.mjs`
  is RED at HEAD *and invoked by nothing*. It sat unrun until a close auditor typed it by hand.
  It is red because a conductor instruction told a coder to reuse the guard-serve client rather
  than copy it; the coder complied by importing across adapters, satisfying anti-duplication and
  breaking adapter-independence. **Fix the layout** (move the shared broker to an allowlisted
  package — `@fl03/compiler` or a `@fl03/cli-*` platform package; read the gate's own rules to
  see which), **do not weaken the rule**, and wire the gate into something that blocks.
- **DF-64 / DF-65** — CRITICAL, labelled FIX-THIS-RUN, never built.
  `hooks/tests/lint_agent_capabilities.sh` still greps `agents/*.md` for `tools:` tokens.
  Measured reality it cannot see: `agents/engineer.md:7` grants `Workflow`/`Glob`/`Grep`; the
  spawned engineer saw none of the three. Frontmatter `tools:` does not survive to runtime. The
  reader half exists; the **self-report half does not** — nothing tells a dispatched role to
  record what it can actually see. Constraints: probe the visible tool list, **never
  `ToolSearch`** (it resolves deferred tools only, so a null is a false negative by
  construction); **never read the env var** to infer a capability (DF-66 is that mistake one
  level down).
- **DF-77 FIX 3 — the correlation key is unsolved.** `tool_use_id` provably cannot work (minted
  fresh per call, so a later call's id never matches its dispatching `Agent()` call's).
  `session_id` provably cannot work (shared identically across a whole dispatch tree).
  `agent_id` is the evidenced candidate — Codex already uses it successfully — but a live
  capture inside a dispatch harness failed. Until this lands, Claude-side role resolution
  returns `unknown` for essentially every call and enforcement is warn-only.
- **Two dispatch directories.** `.shepherd/dispatch/v6.4.5/` holds 64 records;
  `.shepherd/runs/v645/dispatch/` exists and is **empty**. One concept, two identifiers — git
  branch (`v6.4.5`) vs run slug (`v645`). `hooks/scripts/_lib.sh:614` globs across sprint dirs
  precisely because the reader cannot rely on the writer's key, so a run directory is not
  self-contained: it cannot be archived, pruned, or handed to another harness with its dispatch
  history intact. `{run_dir}/dispatch/` is the correct single home. W15 was fixing this when
  halted; its brief is in the same preserved script.

### MEDIUM

- **[#288](https://github.com/FL03/shepherd/issues/288)** — `plan lane-drift` cannot tell an
  authorized ledger entry from real drift. 17 of 19 hits are conductors ledgering `DONE` into
  their own lane plan, which `.shepherd/dispatcher-patches/v645-pc-1.md` explicitly authorizes.
  The two genuine ones are buried. Separate the contract from the ledger.
- **[#289](https://github.com/FL03/shepherd/issues/289)** — `test_v644_wiring.sh` leg C asserts
  against the **installed** plugin, so it cannot pass until after the release that ships its
  fix. It cannot gate that release.
- **[#292](https://github.com/FL03/shepherd/issues/292)** `refresh-github.sh` escapes
  title/body but not labels/milestone — one apostrophe in a label aborts the whole sync.
- **[#293](https://github.com/FL03/shepherd/issues/293)** `install-shctx-launcher.sh` crashes
  with a raw bash unbound-variable trace instead of its own diagnostic.
- **`scripts/check-workspace.sh` needs a 10th invariant**: no `tests.rs` under any `src/`. It
  already enforces nine of exactly this shape, self-test scaffolding included. See §5.

---

## 3. Two things that will bite you

**DF-80 — nothing this sprint fixed in a hook has ever executed.**

```
$ command -v shctx
/Users/jo3/.local/bin/shctx      -> ~/.claude/plugins/cache/shepherd/shepherd/6.4.4/
```

Hooks firing in a live session run the **installed** plugin, not this tree. All 64 dispatch
records — including ones written hours after the DF-77 writer fix committed — still carry
`agent_role: "unknown"` and the pre-fix schema. A dogfood sprint structurally cannot observe
its own hook fixes taking effect, so **"fixed" and "fixed and live" are different states this
run has no instrument to distinguish.** Assume nothing hook-layer is live until release +
reinstall. This is also the root of #289.

**DF-78 — changing a shared helper silently breaks its consumers.**

W11 correctly de-escalated `current_role()`; nine scripts call it;
`conductor_write_guard.sh` went inert (24/24 → 16/24) because its own header depended on the
old fallback. Two steps named the exact file and the exact one-line diff in
`out_of_scope_writes` and neither could act, because `file_scope.exclusive` is authored
per-step with no consumer analysis. The same error then recurred twice more (W13/W14
overlapping on `packages/harness-claude/**`).

Mechanical fix, cheap: grep the callers of every symbol a step modifies in a shared file, diff
against the wave's declared scopes, refuse to dispatch on a non-empty remainder.

---

## 4. The pattern to internalize before you touch anything

**Ten gates that could not fail**, one that could not pass, one wired to nothing. The mechanism
is identical every time: **the test manufactures the precondition the runtime never supplies.**

| id | Gate | Why it was inert |
|---|---|---|
| DF-17 | `lint_agent_capabilities.sh` | pins tokens in file text; asserts nothing at runtime — **still unfixed** |
| DF-19 | `test_v644_wiring.sh` | grepped prose, so #270 read "fixed" while measuring broken 5/5 |
| DF-59 | `conformance/run.sh --impl=rust` | exited 0 on "0 cases implemented" |
| DF-62/63 | wave gates | exited 0 on a ledger missing a lane |
| DF-71 | `teammate_git_guard.sh` | SQL matched 0 rows; suite green via a seeded fixture |
| DF-72 | `shepherd lint` | found 0 files from a subdir and exited 0 |
| DF-75 | Codex guard | `SHEPHERD_ROLE` set by nothing; suite green because the tests set it |
| DF-77 | `coder_git_guard.sh` | role resolution 0/63 — had **never denied anything** |
| #284 | `dispatch_guard.sh` | failed OPEN on malformed JSON, all 8 checks at once |
| DF-79 | Claude guard relay | denied **100%** of live calls; suite green because every fixture built a sandbox with an EMPTY dispatch dir |
| #289 | wiring test | asserts the installed plugin — cannot pass when it matters |
| #290 | `check-deps.mjs` | invoked by nothing |

**Rules that fall out of it, applied to every check you write:**

1. Two controls, never one. Positive: the known-broken form must be REJECTED (recover it from
   git history if it once shipped). Negative: the current form must PASS.
2. **Exit non-zero on an EMPTY input set.** "Scanned 0 files, all passed" is DF-59 and DF-72.
3. Drive the REAL entrypoint with a REAL payload before believing any unit test.
4. Watch for a fail path that **escalates** rather than merely opening. DF-77's fallback
   returned `conductor` — a tier with *more* git authority than the `coder` it failed to
   identify.
5. Prefer a mechanism the surrounding doctrine already makes mandatory. DF-77's tagger read a
   prompt header the dispatch law *forbids* being present, while `subagent_type` — mandatory
   and separately enforced — sat unread in the same payload.

---

## 5. Repo conventions worth knowing

- **Rust tests: two placements only.** Inline `#[cfg(test)] mod tests { … }` in the source file,
  or a real file under `crates/<crate>/tests/`. **Never a `tests.rs` inside `src/`.** Split by
  *access*: only tests touching private items stay inline. Wire feature-gated integration tests
  with `[[test]] name = "…" required-features = [...]` — already the pattern in 4 of 5 crates.
  Fixed this session (`31ad5f9`): 6 public-API tests moved to `crates/core/tests/run_state.rs`,
  4 `atomic_io` tests stayed inline because they reach the private `mod atomic;`.
- **Never re-indent or dedent Rust test code when moving it.** Golden-byte fixtures are raw
  string literals whose leading whitespace is significant. A blanket indent and a blanket
  dedent each silently corrupted `GOLDEN_WITH_UNKNOWN_KEYS` and broke a byte-for-byte oracle
  assertion. `rustfmt` will not catch it — it does not touch raw strings.
- **bash 3.2.57** on this box: no `${var,,}`, no `mapfile`, no `declare -A`.
- **Never read `$?` after a pipe.** `cmd | tail; echo $?` reads *tail's* status. This produced
  false PASS findings three separate times this sprint, including by the conductor.
- **`--no-verify` is banned** (CLAUDE.md). Fix the gate. `SHEPHERD_SKIP_GATE=1` exists for a
  genuinely broken WIP handoff and should be rare.
- **SQL:** use the one `esc()` (`sed "s/'/''/g"`) or parameterize. Four sprints have now
  hand-rolled a broken `${v//'/''}` next to a working one.

---

## 6. Verified tree state at handoff

```
bash hooks/tests/run.sh                      86/87   (was 80/84 at sprint start)
cargo test -p shepherd-core --features full  10/10   (4 inline + 6 integration)
scripts/gate.sh full                         green
node --test packages/harness-{claude,codex,pi}/test/*.test.mjs   8/8, 7/7, 9/9
bin/shepherd guard test                      17/17
conformance/run.sh --impl=python             15/15
conformance/run.sh --impl=rust               0 cases, exit 1   <- #239, openly unmet
node packages/scripts/check-deps.mjs         RED, exit 1       <- #290
cd services/cli && poetry run pytest -q      1893 pass / 25 fail
```

The 25 pytest failures reproduce byte-for-byte at the pre-sprint baseline: 22 are
`shepherd issues` bash-parity tests needing bash 4+ against this box's 3.2.57, plus a
config-path drift (2) and a version-match row (1). Environmental, pre-existing.

`hooks/tests/run.sh`'s single failure is `test_v644_wiring.sh`, honestly red on #288 and #289.

**SUBTRACT: a genuine violation, not a soft one.** The seed's own `sprint_metadata` sets
`expected_loc_delta: -40000`, `subtract_floor: 45000`, and states verbatim: *"Net-positive
pre-authorized ONLY between first Rust surface and W4 retirement. A close that ends positive is
a genuine SUBTRACT-VIOLATION, not covered."* Measured `git diff v6.4.4..HEAD --shortstat`:
**465 files, +48,675 / −699.**

### Seed deliverables

| GH | Acceptance | Result |
|---|---|---|
| #280 monorepo skeleton | 5 members, feature matrix, npm dep gate | **PARTIAL** — Rust half clean, dep gate red + unwired |
| #281 conformance oracle | `--impl=python` exit 0, checksum | **PASS** 15/15 |
| #282 Rust core engine | `--impl=rust --suite=run-state` byte-clean | **FAIL** 0 cases |
| #283 Rust registry | `sqlite_master` identical, FTS5 | **PASS** 10/10 |
| #239 verb parity | `--impl=rust` green, zero skips | **FAIL** 0 cases |
| #235 distribution/launcher | one binary, 4 platforms | **FAIL** untouched |
| #266 Python/bash retirement | 0 poetry refs, no `.py` in `services/cli` | **FAIL — moved backward** |

---

## 7. What did ship and works

Recorded so the handoff is fair, not to offset §1.

- `coder_git_guard.sh` denies for the first time ever — in tree; see DF-80.
- **codex-shepherd's guard genuinely enforces.** Traced end to end through the real hook with
  `SHEPHERD_ROLE` unset. Its wire format was also wrong (flat vs nested `hookSpecificOutput`,
  corroborated three independent ways) and is fixed — a correct deny was previously being
  silently dropped.
- Predicate interpreters in `packages/`: **1**, down from 3.
- `shepherd run claim` ([#286](https://github.com/FL03/shepherd/issues/286)) — unblocks the live
  `FL03/axiom` `v039-dev1` recovery, five lanes mid-flight.
- `shepherd guard serve`: 0.034 ms/request vs 450–535 ms. That measurement also found
  `bin/shepherd` re-resolving the venv via `poetry env info` on **every** invocation
  (270–315 ms) and `commands/__init__.py` eagerly importing `teammate`, dragging Tortoise ORM
  into every CLI call (~116 ms) — both fixed, both taxing every command in the plugin.
- 17-case guard conformance corpus — the spec that makes the Rust port mechanical.

---

## 8. Start here

1. **§1.** Port the guard engine to Rust. Brief written, corpus exists, wasm target is the bar.
2. **§2 CRITICAL.** Re-verify the SQL sweep and the `run.json` lock from each issue's own
   exploit payload — that wave died before its audit ran.
3. **#290.** Move the shared broker to an allowlisted package; wire the gate into CI.
4. **DF-77 FIX 3.** Until the correlation key lands, Claude-side enforcement is warn-only.
