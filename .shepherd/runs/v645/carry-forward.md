# v6.4.5 — carry-forward ledger

Everything discovered this sprint that is **not fixed** at close. Written at the point the
sprint was halted on usage exhaustion, so it is a handoff, not a summary.

Sources: `.shepherd/runs/v645/dogfood.md` (79 rows), the five close-swarm reports in
`reports/close-*.md`, and the W10–W15 central-verify reports.

---

## 0. THE ONE THAT MATTERS — the engine is in the wrong language

**Severity: CRITICAL. Nothing else on this list outranks it.**

Rust exists in this workspace for exactly one reason: compile once, target anything, stop
rewriting the system when the host language changes (next target: TypeScript). That is the
stated premise of v6.4.5, whose theme is *"the CLI stops being a rewrite target."*

This sprint built its newest, most load-bearing component — the guard predicate engine — in
**Python**, under `services/cli/shepherd_cli/predicates.py` + `commands/guard.py`, ~1,400
lines. It then built three harness adapters that all relay to it, and a socket broker to make
the relay fast enough to use.

Measured: `git diff c719ef3..HEAD -- crates/` is **empty**. Zero Rust was written across the
entire execution session. The 66 crate files / +6,175 lines in this sprint's range predate it.

Consequences, all of them downstream of that one choice:
- Seed deliverable **#266** (retire Python/bash) moved BACKWARD: 132 tracked `.py` files
  remain under `services/cli`, 102 `poetry`/`venv-ensure` references remain repo-wide, and
  the sprint *added* to the surface it was chartered to remove.
- Seed deliverable **#239** (`conformance/run.sh --impl=rust` green, zero skips) is still
  `0 cases implemented, exit 1`.
- The guard engine cannot compile to wasm, so it cannot be reused from TypeScript without
  being written a third time — the precise outcome Rust was adopted to prevent.
- Every adapter now depends on a Python CLI resolved through a bash wrapper resolving a
  poetry venv. A single guard decision crosses four language boundaries.

**The work, specified.** W15 was authored and dispatched to do exactly this before the sprint
was halted; its brief is preserved at
`~/.claude/projects/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/workflows/scripts/v645-w15-guard-in-rust-wf_45e00295-457.js`
and is the starting point, not a sketch:

1. `crates/core/src/guard/` — the evaluator, pure, under the `alloc` floor with `parse` +
   `json` capabilities only. No `clap`, no `anyhow`, no `std::process`, no `Harness` branch
   (the `engine-boundary` CI job enforces this). Filesystem loading goes behind a `std` gate,
   exactly as `RunState::load` is. **`cargo check -p shepherd-core --target
   wasm32-unknown-unknown` must stay green with the guard module linked** — that target is
   the whole point.
2. `crates/cli/src/cmd/guard.rs` — `eval` / `test` / `serve`. This crate has exactly one
   subcommand today (`Init`); `cmd/init.rs` is the only prior art for the shape. The crate
   names `shepherd` (umbrella), never `shepherd-core` — a workspace invariant enforces it.
3. Conformance: register the Rust impl so `--impl=rust --suite=guard-cli` runs byte-clean
   against `--impl=python`. `conformance/runner.py` already supports two impls by design.
4. Only after the corpus is byte-clean does the Python engine get deleted. It is the oracle
   until then — the same relationship `models_run.py` already has with `crates/core/src/run.rs`.

The `[[example]]` corpus (17 cases, 8 allow / 9 deny, in `content/predicates/*.toml`) is the
conformance spec that makes this port mechanical rather than exploratory. That much the sprint
did produce.

---

## 1. Live security and data-integrity defects

| # | Severity | Defect | State |
|---|---|---|---|
| [#295](https://github.com/FL03/shepherd/issues/295) | CRITICAL | `cmd_teammate.sh` `status`/`retire` interpolate an unescaped teammate name into SQL. Proven exploitable: mass UPDATE, WHERE-bypass read. The same file defines a **correct** `esc()` at line 24 and uses it correctly at line 215. | Sweep partially landed (`test_sql_escaping.sh` 20/20) but **was killed mid-wave and never audited**. Treat as UNVERIFIED. |
| [#291](https://github.com/FL03/shepherd/issues/291) | CRITICAL | `cmd_init.sh` interpolates the repo dirname unescaped. Proven arbitrary-SQL execution — an apostrophe in a directory name is the whole exploit. | Same partial sweep. UNVERIFIED. |
| [#297](https://github.com/FL03/shepherd/issues/297) | HIGH | `cmd_report.sh` interpolates 5 CLI flags with **zero** escaping. UNION-based exfiltration from any registry table, proven. | Same partial sweep. UNVERIFIED. |
| [#296](https://github.com/FL03/shepherd/issues/296) | HIGH | The broken `${v//'/''}` idiom that #285 recorded as "duplicated 3 times" actually recurs in **20 sites across 8 files**. Four sprints have now hand-rolled a broken variant next to a working one. | Partial. No gate exists yet to prevent a ninth copy. |
| [#294](https://github.com/FL03/shepherd/issues/294) | CRITICAL | `run.json` has no write serialization. Two barrier-synchronized OS processes each registering a lane: **one lane silently vanished**. `/shepherd:spawn` registers lanes concurrently by design. | `models_run.py` was modified mid-wave then halted. UNVERIFIED, possibly incomplete. |

**Every row in this table was killed mid-remediation.** The wave (W14) that was fixing them
was stopped before its auditor ran. Re-verify from the issues' own exploit payloads before
trusting any of it.

---

## 2. Gates that do not gate

The dominant defect class of this sprint: **ten** gates that could not fail, one that could
not pass, one wired to nothing. The mechanism is identical every time — *the test manufactures
the precondition the runtime never supplies.*

| id | Gate | Why it could not fail | State |
|---|---|---|---|
| DF-17 | `lint_agent_capabilities.sh` | pins tokens in file text, asserts nothing at runtime | **UNFIXED** (see §3) |
| DF-19 | `test_v644_wiring.sh` | grepped prose, so #270 read "fixed" while measuring broken 5/5 | fixed |
| DF-59 | `conformance/run.sh --impl=rust` | exited 0 on "0 cases implemented" | fixed (exits 1) |
| DF-62/63 | wave gates | exited 0 on a ledger missing a lane | fixed |
| DF-71 | `teammate_git_guard.sh` | SQL matched 0 rows; suite green via a seeded fixture | fixed |
| DF-72 | `shepherd lint` | found 0 files from a subdir and exited 0 | fixed |
| DF-75 | Codex guard | `SHEPHERD_ROLE` set by nothing; suite green because tests set it themselves | fixed |
| DF-77 | `coder_git_guard.sh` | role resolution 0/63; had **never denied anything** | fixed in tree, see DF-80 |
| [#284](https://github.com/FL03/shepherd/issues/284) | `dispatch_guard.sh` | failed OPEN on malformed JSON, all 8 checks at once | fixed |
| DF-79 | Claude guard relay | denied **100%** of live calls; suite green because every integration fixture built a sandbox with an EMPTY dispatch dir | fixed |
| [#289](https://github.com/FL03/shepherd/issues/289) | `test_v644_wiring.sh` leg C | asserts against the **installed** plugin, so it cannot pass until after the release that ships its fix — it cannot gate that release | **UNFIXED** |
| [#290](https://github.com/FL03/shepherd/issues/290) | `packages/scripts/check-deps.mjs` | **invoked by nothing.** Sat unrun until a close auditor typed it by hand; it is RED at HEAD | **UNFIXED** |

**#290 is red because of a conductor instruction.** W12's brief told the coder to reuse the
guard-serve client rather than copy it. It complied by importing across adapters — satisfying
the anti-duplication rule and breaking adapter-independence. Nothing surfaced the conflict
because the gate runs nowhere. Fix the layout (move the shared broker to an allowlisted
package), **do not weaken the rule**, and wire the gate into something that blocks.

---

## 3. Doctrine and mechanism gaps

**DF-64 / DF-65 — CRITICAL, labelled FIX-THIS-RUN, never built.** `lint_agent_capabilities.sh`
still greps `agents/*.md` for `tools:` tokens. Measured reality it cannot see:
`agents/engineer.md:7` grants `Workflow`, `Glob`, `Grep`; the spawned engineer saw none of the
three. Frontmatter `tools:` does not survive to runtime. The reader half exists; the
**self-report half does not** — nothing instructs a dispatched role to record what it can
actually see. Constraints for whoever builds it: probe the visible tool list, never
`ToolSearch` (it resolves deferred tools only — a null is a false negative by construction);
never read the env var to infer a capability (DF-66 is that mistake one level down).

**DF-77 FIX 3 — the correlation key is unsolved.** `tool_use_id` provably cannot work (minted
fresh per call, so a later call's id never matches its dispatching `Agent()` call's).
`session_id` provably cannot work (shared identically across a whole dispatch tree). `agent_id`
is the evidenced candidate — Codex uses it successfully — but a live capture attempt inside a
dispatch harness failed. Until this lands, Claude-side role resolution returns `unknown` for
essentially every call and both the relay and `coder_git_guard.sh` can only warn.

**DF-78 — a step may change a shared helper and nothing resolves that helper's consumers.**
W11-S1 correctly de-escalated `current_role()`; nine scripts call it;
`conductor_write_guard.sh` went inert (24/24 → 16/24). Two steps named the exact file and the
exact one-line diff in `out_of_scope_writes` and neither could act, because
`file_scope.exclusive` is authored per-step with no consumer analysis behind it. **I then made
the same error twice more** — W13 and W14 were dispatched with overlapping scope on
`packages/harness-claude/**`. Mechanical fix: grep the callers of every symbol a step modifies
in a shared file, diff against the wave's declared scopes, refuse to dispatch on a non-empty
remainder.

**DF-80 — none of this sprint's hook fixes have ever run.** `shctx` resolves to
`~/.claude/plugins/cache/shepherd/shepherd/6.4.4/`. The hooks firing in a live session are the
*installed* plugin, not this tree. All 64 dispatch records — including ones written hours after
the DF-77 writer fix committed — still carry `agent_role: "unknown"` and the pre-fix schema. A
dogfood sprint structurally cannot observe its own hook fixes taking effect, so **"fixed" and
"fixed and live" are different states this run has no instrument to distinguish.** The release
note must say this plainly, and close-time needs a check that separates the two.

**DF-79 carry — an unreconciled contradiction.** The Claude relay now WARNS on an unresolved
role across Write/Edit/Bash/Agent/Workflow; `conductor_write_guard.sh` DENIES Edit/Write on the
identical signal. Low impact only because the relay is unwired. One of them is wrong.

**Two dispatch directories** (operator-found, W15 halted before the fix landed).
`.shepherd/dispatch/v6.4.5/` holds 64 records; `.shepherd/runs/v645/dispatch/` exists and is
**empty**. Two identifiers for one concept — git branch `v6.4.5` vs run slug `v645`.
`_lib.sh:614` globs across sprint dirs precisely because the reader cannot rely on the writer's
key, and a run directory is therefore not self-contained: it cannot be archived, pruned, or
handed to another harness with its dispatch history intact. `{run_dir}/dispatch/` is the
correct single location.

**[#288](https://github.com/FL03/shepherd/issues/288) — `plan lane-drift` can't tell a ledger
entry from drift.** 17 of its 19 hits are conductors ledgering `DONE` into their own lane plan,
which `v645-pc-1.md` explicitly authorizes. The two genuine ones (l1-engine acceptance caveats
that never reached `vars.json`; l3-surface running with no lane plan at all) are buried under
the noise. Separate the contract from the ledger.

**[#292](https://github.com/FL03/shepherd/issues/292)** `refresh-github.sh` escapes title/body
but not labels/milestone — one apostrophe in a label aborts the whole sync.
**[#293](https://github.com/FL03/shepherd/issues/293)** `install-shctx-launcher.sh` crashes with
a raw bash unbound-variable trace instead of its own diagnostic when no install resolves.

---

## 4. Seed deliverables, measured against their own acceptance lines

| GH | Deliverable | Acceptance | Result |
|---|---|---|---|
| #280 | monorepo skeleton | 5 members, `check-features --targets`, npm dep gate | **PARTIAL** — Rust half clean; the npm dep gate is red and unwired (#290) |
| #281 | conformance oracle | `--impl=python` exit 0, non-zero cases, checksum | **PASS** — 15/15 |
| #282 | Rust core engine | `--impl=rust --suite=run-state` byte-clean | **FAIL** — 0 cases |
| #283 | Rust registry | `sqlite_master` identical, FTS5 present | **PASS** — 10/10 |
| #239 | canonical verb parity | `--impl=rust` green, zero skips | **FAIL** — 0 cases |
| #235 | distribution/launcher | one binary across 4 platforms | **FAIL** — untouched |
| #266 | Python/bash retirement | 0 poetry refs, no `.py` under `services/cli` | **FAIL — moved backward** |

**SUBTRACT: genuine violation, not a soft one.** The seed's own `sprint_metadata` sets
`expected_loc_delta: -40000`, `subtract_floor: 45000`, and states: *"Net-positive
pre-authorized ONLY between first Rust surface and W4 retirement. A close that ends positive is
a genuine SUBTRACT-VIOLATION, not covered."* Measured `git diff v6.4.4..HEAD --shortstat`:
**465 files, +48,675 / −699**. Over the ceiling, with the retirement not landed.

**Grade: C** (close-swarm completeness auditor). Two of seven deliverables pass cleanly, one is
half-landed, four fail outright, plus a SUBTRACT-VIOLATION and a CRITICAL dogfood row whose
FIX-THIS-RUN disposition was never honored.

---

## 5. What actually shipped and works

Recorded so the handoff is fair, not to offset §0.

- A guard predicate engine with a 17-case conformance corpus that makes the Rust port
  mechanical. **In the wrong language, and that corpus is its main value.**
- `coder_git_guard.sh` denies for the first time ever (in tree; see DF-80).
- codex-shepherd's guard genuinely enforces — traced end to end through the real hook with
  `SHEPHERD_ROLE` unset. Its wire format was also wrong (flat vs nested `hookSpecificOutput`)
  and is fixed; a correct deny would previously have been silently dropped.
- Predicate interpreters in `packages/`: **1**, down from 3.
- `hooks/tests/run.sh`: 80/84 → **86/87**.
- `shepherd run claim` (#286) — unblocks the live `FL03/axiom` `v039-dev1` recovery.
- `shepherd guard serve`: 0.034 ms/request vs 450–535 ms. The measurement also found that
  `bin/shepherd` re-resolves the venv via `poetry env info` on **every** invocation
  (270–315 ms) and `commands/__init__.py` eagerly imports `teammate`, dragging Tortoise ORM
  into every CLI call (~116 ms) — both fixed, both taxing every command in the plugin.

---

## 6. Start here

1. **§0.** Port the guard engine to Rust. The brief is written and the corpus exists.
2. **§1.** Re-verify the SQL sweep and the `run.json` lock from the issues' own exploits — that
   wave died before its audit.
3. **#290.** Move the shared broker to an allowlisted package and wire the gate into CI.
4. **DF-77 FIX 3.** Until the correlation key lands, Claude-side enforcement is warn-only.
