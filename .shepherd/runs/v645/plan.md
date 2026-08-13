---
title: v6.4.5 Sprint Plan — one compiled engine, three harness adapters
run: v645
runId: v645
branch: v6.4.5
base: main
seed: .shepherd/runs/v645/seed.md
mesh: .shepherd/runs/v645/mesh.md
dogfood: .shepherd/runs/v645/dogfood.md
journal: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/journal.jsonl
author: shepherd-engineer-v645 (self-contained @engineer teammate)
date: 2026-08-12
sprint_tshirt: XL
waves: 5
lanes: 5
milestone: 58
fanout: in-context
fanout_downgrade_reason: workflow-absent-from-tool-list
intro_wave: 5 lanes (2 @discovery + 3 intro-@auditor), parallel_max=5 per config
status: draft-pre-critic
---

# v6.4.5 Implementation Plan

**Goal:** Replace the Python/bash CLI with one compiled Rust engine published as a
single binary plus npm platform packages, and turn Claude Code, Codex and Pi into thin
adapters over that one core — so adding a fourth harness is writing an adapter, never
porting the engine again.

**Architecture:** `crates/{core,registry,render,sdk,cli}` with `sdk` as the published
`shepherd` umbrella every consumer routes through. `content/` is a new single-source
tree that *compiles out* into the committed root layout (`agents/`, `commands/`,
`skills/`, `hooks/`) plus per-harness targets. `conformance/` freezes current Python
behavior as a language-neutral oracle **before** any port code merges; Python stays
canonical until that gate is byte-clean.

**Tech stack:** Rust 2024 / MSRV 1.94, `clap`, `rusqlite` (bundled), `config`,
`schemars`, `nom`, `minijinja`, `serde`, `sha2`, `strum`, `anyhow`, `thiserror`, `uuid`,
`chrono`, `tracing`. TypeScript for Pi's per-`tool_call` guard layer only. npm platform
packages under `optionalDependencies`. SQLite is the cross-harness contract.

---

## Global Constraints

Every step's requirements implicitly include this section.

1. **The seed's 12 locked decisions bind.** Changing one is a critic-RED escalation, not
   a sprint-time judgment call. In particular: no napi-rs, no `.node` addon, no new
   crate without escalation, no canon flip before the parity gate is green.
2. **Dependency stack is CLOSED** (decision 7). Three pre-existing deviations, all
   **project-wins**, all surfaced here rather than papered over — the critic caught the
   second and third after I flagged only the first, which was itself an inconsistency in
   my own stated discipline:
   - `code-style/rust.md` prescribes `hashbrown` over `std::HashMap` and `tokio` for
     async; **decision 7 forbids both.** A coder "fixing" this toward the personal ledger
     introduces a decision-7 violation.
   - **`tracing-subscriber` is a 15th crate**, present at `crates/cli/Cargo.toml:62`,
     while decision 7 enumerates 14. It is **architecturally necessary and sanctioned**:
     the binary is the only place a subscriber may be installed, per the crate's own
     comment at `:60`. Pre-existing and already landed — **not** an unauthorized addition
     by any step in this plan, and named here so it does not read as one.
   - **`resolver = "3"`** at `Cargo.toml:11` vs `code-style/rust.md`'s `resolver = "2"`.
     Intentional and correct for edition 2024; pre-existing; no step touches it. Same
     project-wins treatment as `hashbrown`/`tokio`.

   None of the three authorizes adding a *new* crate. Adding one remains critic-RED.
3. **Rust idioms** (`code-style/rust.md`): edition 2024, MSRV 1.94,
   `version.workspace = true`, `workspace.dependencies` as the single version source,
   `resolver = "2"`, named-file module pattern, never `{traits,types,utils,impls}/mod.rs`,
   `thiserror` in libraries and `anyhow` only in binaries, no hollow wrappers, no
   `TODO`/`FIXME` (use `todo!("see #N")`).
4. **The plugin root layout is an interface contract**
   (`.shepherd/docs/specs/2026-08-12-v645-plugin-layout-contract.md`). `agents/`,
   `commands/`, `skills/`, `hooks/` MUST stay at the repository root. `content/` emits
   *into* them; emitted artifacts stay committed so `source: github` installs need no
   build step. Moving a component dir is what broke the plugin on 2026-08-12 while
   `claude plugin validate` still reported success.
5. **Resource cap — this box, measured 2026-08-12:** 16 GB RAM, 10 cores, disk 90% full
   (44 GB free), `target/` already 2.5 GB, **swap 3.86 GB used of 5.12 GB (1.26 GB
   free)**. This is the exact shape of the #256 incident.
   - **At most 2 lanes may invoke cargo concurrently.** Those two set
     `CARGO_TARGET_DIR=target/.lanes/<lane-slug>`; distinct target dirs do not share
     cargo's exclusive lock and so may run in parallel.
   - **The wave gate is ONE central run** against the shared warm `target/`, executed by
     the wave's owner — never fanned out. Fanning out verification is the defect
     (`SKILL.md §Fan-out counterweight` rule 2).
   - Every cargo invocation is preceded by `scripts/df-guard.sh --min=12`.
   - Lane target dirs are deleted on the wave's final PASS.
   - **Measured justification:** a full `cargo check --workspace` on the warm cache
     completes in 0.65 s and `scripts/check-features.sh` clears 23 combinations with
     **zero swap movement**. Verification here is nearly free; *cold per-lane target
     dirs* are the expensive thing. That is why per-lane dirs are rationed to 2 rather
     than issued to all 5.
6. **Coders run zero gates and zero git.** They write files and report them; the
   conductor stages after wave-review PASS (`flock.md §@coder`).
7. **`bin/shepherd lint` is RED at plan time** and is the configured `[gates].lint`.
   Until W0-S1 lands, every wave gate fails on pre-existing debt. W0-S1 is therefore
   the first step of the sprint and blocks every other wave gate.

---

## Verified baseline (engineer-run, central)

Run by the engineer directly rather than fanned out, per constraint 5. These are
measurements, not claims inherited from the seed.

| Check | Result | Bears on |
|---|---|---|
| `cargo metadata --no-deps` | **5 members** at 6.4.5 | #280 acceptance ✓ |
| `cargo check --workspace` | **exit 0**, 0.65 s warm | #280 acceptance ✓ |
| `scripts/check-features.sh` | **23/23 combinations resolve** | #280 acceptance ✓ |
| `scripts/check-plugin.sh` | **6/6 contract rules hold** | layout contract ✓ |
| `gates.check` (jq) | PASS | wave gate |
| `gates.extra.hook_tests` | PASS | wave gate |
| **`bin/shepherd lint`** | **FAIL** — 6 legacy run dirs lack `run.json` | **W0-S1** |
| `scripts/check-features.sh --targets` | NOT RUN — needs an LLVM with a wasm backend | W1 acceptance |

**Landed Rust:** `core` 666, `registry` 241, `render` 163, `sdk` 137, `cli` 156 =
**1,363 lines** against ~42,560 lines of Python to reproduce. That ratio is the sprint's
central risk and drives "Open questions for critic" Q1.

---

## Phase 0 — corrections to the seed and mesh

Verified against live state. Each correction changes a number a coder would otherwise
port wrongly. None is a `SEED DRIFT — substantive`; all are mechanical.

| # | Source claim | Verified | Consequence |
|---|---|---|---|
| C1 | mesh + decision 6: "20 migration files" | **21, and the +1 is a trap.** `schema/migrations/` holds 20 (`0002`–`0021`); `schema/0001_init.sql` sits at the schema-dir **top level, outside `migrations/`**, and is applied by a separate path (`shctx init`). Both existing runners glob `migrations/[0-9][0-9][0-9][0-9]_*.sql` = 20. Live `schema_versions` has 21 rows | **A Rust runner that globs `migrations/*.sql` silently skips the baseline schema.** Decision 6 must say 21 and name `0001_init.sql` explicitly (source: A3) |
| C2 | mesh: "39 tables" | **45 rows** in `sqlite_master WHERE type='table'`, comprising **35 base + 2 FTS5 virtual + 8 FTS5 shadow** = **37 addressable** | State the decomposition, not a single number — an earlier draft said "45" and A3 said "36"; both were describing different subsets of the same tree. The oracle's counting query must say which it means (critic LOW) |
| C3 | mesh: "25 views" | **14** live | Over-provisioning by 11 if planned off the mesh |
| C4 | mesh: "40 indexes" | **34 named** (`type='index' AND sql IS NOT NULL`); 68 rows total including SQLite auto-indexes | An earlier draft said 68 without the qualifier. Auto-indexes are not portable artifacts — assert the 34 named |
| C5 | mesh: "25 `json_valid()` CHECKs" | **19 tables carrying 24 `json_valid` CHECK constraints** | Two different numbers, and an oracle query that counts one while asserting the other fails against correctly-ported code (critic LOW) |
| C5-bis | — | The mesh's numbers are **`grep -c "CREATE …"` counts across migration *history***, so they include rename-dance transients (`mem_entries_new`, `locks_history_new`, `focus_new`, `mailbox_new`) and the dropped `mailbox` | **Never size the registry off statement counts.** Size off live `sqlite_master` |
| C6 | mesh: "7 triggers", "2 FTS5 + 6 sync triggers" | **confirmed exactly** — 6 FTS5 sync + `trg_watch_paths_updated_at` | No change |
| C7 | seed decision 4: tokenizer `unicode61 remove_diacritics 2` | **confirmed verbatim** on both `index_fts_symbols` and `index_fts_artifacts` | No change |
| C8 | decision 6: `schema_versions`, not `user_version` | **confirmed** — 21 rows; `PRAGMA user_version` = 0, unused | Rejection of `rusqlite_migration` stands |
| C9 | mesh + seed: "**all 32** guard scripts read SQLite directly" | **10 of 32** touch `sqlite3` directly | Narrows the direct-SQL surface — but see **C11**, which is the finding that matters |
| C10 | implied: the whole schema is uniformly the compatibility surface | Tiered, not uniform: **(a) 8 guard-frozen objects** — `deliverables`, `focus`, `mem_entries`, `spawn_leads`, `sprint_metrics`, `teammates`, `v_teammates_live`, **`worktrees`**; **(b)** ~42 objects once the bash tests W4-S2 migrates are counted; **(c)** 51 live objects (37 addressable tables + 14 views) reproduced by W1-S2 | **A coder may NOT treat "not in tier (a)" as "refactorable."** Two of this plan's own drafts got tier (a) wrong — see the methodology note below |

> **Methodology note, because the error is instructive and repeatable.** My first derivation
> of tier (a) grepped `FROM <table>` and `JOIN <table>` across `hooks/scripts/*.sh` and
> returned **7** objects. That pattern **structurally cannot find write targets**, and
> `worktree_lifecycle.sh:89` does `INSERT INTO worktrees (…)` while `:54` checks the table
> exists and `:10` documents reading it at `status='active'`. The critic caught the gap;
> re-derived as reads **UNION** writes (`INSERT INTO` / `UPDATE` / `DELETE FROM`), tier (a)
> is **8**. A registry port that treated `worktrees` as reshapeable would silently break
> worktree lifecycle tracking at exactly the moment decision 3 matters most. **Any future
> re-derivation of this surface must union reads and writes.**
| **C11** | **locked decision 3: "all 32 guard scripts read SQLite directly and ZERO shell out to the CLI"** | **FALSE. 5 functional shellouts across 4 scripts, all feeding guard decisions:** `dups_write_guard.sh:65` (`dups check --stdin --as --json` drives BLOCK/WARN), `seed_preflight_check.sh:64` (`seed verify` gates SEED-GATE), `teammate_idle.sh:57-58` (`teammate heartbeat --note=idle`) and `:88` (`deliverable stalled --since-mins=10`), `user_prompt_submit.sh:102` (`status`). **Three of those four scripts are NOT in the direct-SQL set** — they touch DB state *exclusively* through the CLI | **CRITIC-RED escalation — see §Open questions Q6.** My own earlier grep "confirmed" decision 3 because it excluded `msg+=`/`warn+=` lines too aggressively and missed executed calls. A3 is right and I was wrong. The compatibility surface is schema **plus** five exact CLI behaviors, which **under-scopes #281 as currently specified** |
| C12 | seed §B: `dev.0..dev.5` topology | **RETIRED by operator directive** — one run, waves × steps | See §Sprint-theme absorption |

**Seed open question 4 — ANSWERED, closed.** Pi's `--tools` is a **replacing** allowlist
("Comma-separated allowlist of tool names to enable. Applies to built-in, extension, and
custom tools"), confirmed by direct probe of the installed 0.84.1 binary, not from docs.
`--no-builtin-tools` and `--no-tools` exist independently. The adapter's capability claim
does not need a further probe.

### SEED DRIFT — mechanical (#235), and a restatement of seed §2

**Classification: MECHANICAL, not substantive.** Per `agents/engineer.md` protocol step 2,
I am amending in place and continuing rather than stopping. The deliverable survives; only
its scope shrinks. I am explicitly *not* escalating this one to the operator, because the
issue, its milestone, and its acceptance all stand — the justification prose behind them
is what moved.

**What the seed says (§2, §6):** #235 "globs `cache/fl03/shepherd/*` and silently pins a
stale binary under a different publisher dir."

**What is true (D2, verified):** already fixed and shipped at **v6.4.3** in `d887ad4`,
documented `CHANGELOG.md:83`. `scripts/install-shctx-launcher.sh:142-175` scans
`cache/*/shepherd/*` publisher-agnostically and version-sorts with `sort -V` plus a
pure-bash `version_gt()` fallback. **19 regression tests** at
`scripts/tests/test_shctx_launcher.sh` cover the exact `fl03/6.3.3` vs `pzzld/6.3.9` case
from the issue. Grep for the offending pattern across `hooks/`, `scripts/`,
`plugin.json`, `README.md` returns **zero hits outside comments describing the historical
bug**.

**The residual gap is real but different and smaller: nothing invokes that installer
automatically.** Not in `hooks/hooks.json`, not in `plugin.json`, not in
`session_open.sh`; `README.md:274` still points at the legacy `skills/context/scripts/`
path. #235's own Ask — "ship the launcher in the plugin installer" — is precisely this,
and it is genuinely open. **W4-S1 is rescoped from "rewrite launcher resolution" to
"auto-wire the existing installer,"** and its acceptance changes accordingly.

**Seed §2 restated.** The seed opens by citing #266 and #235 as *live production pain*.
Both are **fixed in code**: #266's `venv_provisioned()` self-heal landed, and #235's
resolver landed at v6.4.3. Leaving §2 as written would have this arc justify itself with
two examples that no longer hold. The honest justification, on this run's evidence:

1. **Distribution and wiring, not logic, is what is still broken.** The launcher works
   and nothing installs it; the venv self-heals and the venv still exists to fail.
2. **Two implementations still answer to two names** (DF-05) — `shctx` (bash) and
   `shepherd` (Python 6.4.4 cache) against a 6.4.5 Rust tree. Measured concretely this
   run: `shepherd plan lane-drift` exists and works, `shctx plan lane-drift` does not.
3. **Verification is string-shaped, not behavior-shaped** (DF-19, and A1's boundary-gate
   finding) — the repo repeatedly greps for prose describing a fix instead of exercising
   it, which is how #270 was graded fixed while being 5/5 broken.
4. **The port work is being done three times** — unchanged and still the strongest
   justification in the seed.

**New finding, no seed anchor — Codex has no slash-command surface at all.** The
installed `codex-shepherd@1.0.2` bundle ships exactly `hooks/`, `scripts/`, `skills/`,
`.codex-plugin/plugin.json`, `shepherd.codex.toml`; `plugin.json` declares one component
path (`"skills": "./skills/"`). `~/.codex/prompts` and `~/.codex/commands` do not exist.
So the content compiler must emit a command surface for **Claude and Pi only** — emitting
a Codex command target is a defect, not a gap. Full evidence:
`.shepherd/runs/v645/reports/discovery-d1-harness.md`.

---

## Dogfood dispositions

Root logged DF-01..DF-11. The engineer verified each testable claim rather than writing
steps against defects that may not exist. **Two are refuted — that is two fewer steps.**

| # | Verified verdict | Disposition |
|---|---|---|
| DF-01 | **CONFIRMED** — a clean clone cannot spawn; nothing scaffolds the DB | W0-S2 |
| DF-02 | **CONFIRMED + extended** — `Agent(name:)` IS the teammate spawn; additionally a teammate **cannot** spawn teammates (flat roster), so sub-flock dispatch MUST omit `name`. Measured: the engineer's first 5-lane dispatch was refused outright | W0-S5 |
| DF-03 | **CONFIRMED** — `shctx models resolve engineer` → `opus[1m]`; the `Agent` `model` enum is `sonnet\|opus\|haiku\|fable` | W0-S4 |
| DF-04 | **CONFIRMED** — `[mcp].github = true` is a promise nothing checks | W0-S6 |
| DF-05 | **CONFIRMED** — two names, two implementations | Closed structurally by W4 (launcher consolidation) |
| DF-06 | **PARTLY REFUTED** — `shctx --version` exits **1**, not 0. The real gap is that no `--version` exists at all, which blocks adapter version detection | W0-S3 (narrowed) |
| DF-07 | **REFUTED — not a defect.** Measured: 3 fail → exit **1**; 4 warn → exit **2**; both implementations correct. `doctor.py:1704` derives the code and `:1745` raises it. Root independently re-verified before striking it. On the *cause*: reading `$?` off a trailing pipeline stage is the **most likely** explanation and root confirmed it matched their invocation — but the refutation rests on the measurement, not on the causal story, and a future reader should not treat the cause as established fact (critic LOW) | **No step. Close as measurement error** |
| DF-08 | **CONFIRMED** — doctor prescribes `shctx refresh --scope=issues`; accepted scopes are `symbols\|shapes\|github\|artifacts\|telemetry\|all`. Correct scope is `github` | W0-S3 |
| DF-09 | **CONFIRMED** — `refresh --scope=artifacts` exits 0 printing `ok`; doctor still reports `never refreshed`. Marker never stamped | W0-S3 |
| DF-10 | **OPEN — operator decides.** Docker MCP catalog carries `github-official` but it needs a PAT secret. Credential provisioning is not the engineer's call | Carried to §Open questions |
| DF-11 | **CONFIRMED, mechanism CORRECTED, and NOT NEW — it is GH #270.** Root diagnosed this as Dynamic Workflow `agent()` behavior. It is not: the engineer's `WORKFLOW-VEHICLE-PROBE` was negative, so all 5 lanes were in-context `Agent()` calls, each returning "Async agent launched successfully". **Async `Agent()` routes the completion notification to the task-tree owner, not the dispatcher, independent of vehicle.** Both resumed agents returned #270's documented signature verbatim — "had no active task; resumed from transcript". #270 measured 3/3; this run makes it **5/5** | W0-S5 (document); #270 stays open as NOT-FIXED |
| DF-E1 | **CONFIRMED, and NOT NEW — it is GH #263.** `Workflow`, `Glob` and `Grep` are absent from the engineer teammate's visible tool list despite `agents/engineer.md:7` granting all three. #263 already establishes the true rule: availability follows **backendType (own-session vs in-process)**, not tier or team membership, and **in-process teammates are denied**. My probe is a second confirmation. Note the live contradiction: `engineer.md:65-67` still asserts "the grant is LIVE" on a teammate substrate | W0-S5; reconcile `engineer.md` against #263 |
| DF-E2 | **NEW** — `skills/shepherd/SKILL.md:20` and `hooks/tests/test_engineer_self_contained.sh` target `.claude/shepherd.toml`, which does not exist; live config is `.shepherd/shepherd.toml` | W0-S6 |
| DF-E3 | **NEW** — `scripts/check-plugin.sh` is Python carrying a `.sh` extension. `gate.sh` invokes it correctly via shebang, so the gate works, but the name invites `bash scripts/check-plugin.sh`, which fails with a syntax error while looking like a real failure | W0-S1 |
| DF-16 | **HIGH — blocks BODY.** `shepherd render lane-plan.md.j2` cannot render a spec-conformant plan: the template reads `step.id`/`step.title` while `agents/engineer.md §Plan structure` mandates `step_id` and defines no `title`. Under `StrictUndefined` that is exit 4. It also silently drops `file_scope.must_not_touch` and `parallel_with`, so a conductor learns neither which paths it may not touch nor which lanes run beside it — a correctness gap in lane isolation, not cosmetics | **W0-S10**, with a render-a-fixture acceptance (a grep would not have caught it) |
| DF-17 | **CRITICAL.** Agent frontmatter `tools:` is not honored as written. `agents/engineer.md:7` grants `Workflow`, `Glob` and `Grep`; this session sees none of the three. #263 explains the `Workflow` half (backendType; in-process teammates denied) but **not** two ordinary read tools vanishing. `hooks/tests/lint_agent_capabilities.sh` pins tokens by grepping agent text, so every capability guarantee in every role file is unverified | **W0-S11** — runtime capability probe asserted against frontmatter |
| DF-19 | **HIGH.** `hooks/tests/test_v644_wiring.sh` "verifies" #268/#269/#270 with `need <file> <string>` — grep for a phrase in a doc. It asserts prose, not behavior, so it cannot detect that #270 is still broken (measured 5/5 this run) because the doctrine text describing the fix is present. Same anti-pattern as DF-17's lint. **This is the mechanism behind the CHANGELOG-versus-tracker divergence the seed opens with** | **W0-S12** — convert to behavior assertions |
| DF-E4 | **Measured, and it bears on root's stall detection.** The `[hooks].teammate_heartbeat` stamp DOES fire (`last_seen_at` advanced +1,659s over this session — an earlier "it never fires" reading was premature and is withdrawn). But it fires **intermittently, not per tool call**: at time of writing it last stamped **896s ago** despite continuous tool use, while `status` remained `idle` for the whole session and only `declared_state: in-progress` distinguished a working lead from a dead one. Any stall detector keyed on `status` or on a 5-minute `last_seen_at` threshold **will false-positive on a healthy lead** | Confirms root's DF-11 second point; **no step** — recorded so root does not kill a live lane during BODY |

---

## Open-issue ledger sweep (Phase-0 row 1, CRITICAL)

`gh issue list --state open --limit 500` → **26 open**, 10 on milestone 58 (every seed
deliverable anchored), **16 outside it**. Per `pipeline.md §CLOSE`, non-current-milestone
items are surfaced as drift risks and never silently absorbed.

**Four outside-milestone issues are not drift risks — they are this sprint's own
substrate, already filed, and my intro wave reproduced three of them live.**

| # | What it is | Evidence from THIS run | Disposition |
|---|---|---|---|
| **#270** | "Agent() completion never notifies the dispatching conductor — the only reliable signal is SendMessage's 'had no active task' reply" | **This is DF-11.** Root logged it as new; it was filed already. Previously measured 3/3; my wave makes it **5/5**, and both resumed agents returned the exact documented string. **Confirms NOT-FIXED** — which answers part of seed open question 1 with live evidence | **W0-S5** documents the mechanism; issue stays open |
| **#263** | "Workflow availability is decided by backendType (own session vs in-process), NOT tier or team membership — in-process teammates ARE denied; agent bodies must check the tool list, not predict from role" | **This is DF-E1.** My `WORKFLOW-VEHICLE-PROBE` returned negative as an in-process teammate — exactly what #263 predicts. The issue's diagnosis is correct and my run is a second confirmation | **W0-S5**; note that `engineer.md:65-67`'s "the grant is LIVE" text contradicts this filed, measured issue |
| **#269** | "`lanes/{lane}/vars.json` and `plan.md` are two sources of truth with no drift check (measured 5/5 lanes)" | **Threatens this plan's own §Lane projection.** Root materializes lanes via `shepherd render lane-plan.md.j2`; corrections made to prose silently miss the artifact dispatch renders from | **Drift risk — operator decides.** Not absorbed: fixing it is unseeded scope. Flagged so root does not lose lane-plan edits during BODY |
| **#275** / **#276** | "SUBTRACT grades sprints on LOC, which is a bad proxy — a sprint that ships a new crate is auto-capped at C+" | **Directly governs §Q1-bis.** #275 carries the operator's own objection verbatim: *"I HAVE NEVER ONCE CLAIMED THAT WE SHOULD END NET NEGATIVE E[VERY SPRINT]"* | **Drift risk — operator decides.** My Q1-bis recommendation should be read as *this arc's instance of an already-contested rule*, not a novel request |

**Adjacent, worth knowing, not absorbed:**

| # | Why it touches this arc |
|---|---|
| #181 | "template/compiler layer for dispatch call-sites, so `[models]` + `agentType` wiring is generated, not hand-audited" — conceptually adjacent to W4-S3's `content/` compiler and to W0-S4's model translation. Do NOT merge it in; note the overlap so the compiler does not accidentally re-implement `shctx graph compile` |
| #82 | workflow→conductor artifact-export contract |
| #261 | run artifacts under a worktree-replicated path — bears on lane worktrees in BODY |
| #262 | nothing joins plan steps against the verdict ledger |
| #267 | `/shepherd:spawn` Check 3 false-positives on the session's own team |
| #268 | no sanctioned path for root to re-gate a plan after a legitimate change — directly relevant if this plan returns from PLAN-GATE |
| #274 | handoff path conflicts with project `CONVENTIONS.md` |

**Remaining 5** (#47, #53, #125, #237 and one v5.1.8-milestoned item) are enhancement or
design-question class, none CRITICAL/HIGH, none touching this arc. No disposition needed
beyond this record.

**Seed open question 1 — ANSWERED, with one correction to A3.** A3 graded all eight
CHANGELOG-fixed-but-open issues (#261, #262, #263, #266, #267, #268, #269, #270)
GENUINELY-FIXED and safe to close. **Six of those eight verdicts stand** — A3 checked them
against real implementations (`verdicts.py`, `wave_verify_cmd`, `_cmd_amend`,
`_lane_drift`, `venv_provisioned()`, `team-preflight.sh`).

**#270 is NOT fixed, and behavioral evidence beats a string grep.** A3 graded it fixed by
finding the doctrine string `"had no active task"` in `agents/conductor.md` — which is the
*identical method* `test_v644_wiring.sh` uses, and therefore has the identical blind spot
(DF-19). This run measured the defect **5/5**: not one of my five sub-flock completions
reached me, and both resumed agents returned that exact documented string. The doctrine
describing the fix is present; the fix is not.

**#263's rule is documented but contradicted in the same repo** — `agents/engineer.md:65-67`
still asserts "the grant is LIVE" on a teammate substrate, which #263 itself refutes. Half
fixed.

**Disposition: close six, keep #270 and #263 open.** Note the shape of the error, because
it is the arc's own thesis in miniature: a verification method that greps for prose
describing a fix will grade every documented-but-broken thing as fixed. That is exactly
what W0-S12 exists to end.

## Sprint-theme absorption

Operator directive 1 retires the `dev.0..dev.5` fanout. Every seed §B theme is absorbed;
none is silently dropped.

| Seed sprint | Theme | Absorbed by |
|---|---|---|
| dev.0 | scaffold, npm workspace, registry bootstrap, conformance oracle frozen | **Wave 0** |
| dev.1 | Rust core: run state, canonical `run.json`, config schema, Stage Graph | **Wave 1** (L1) |
| dev.2 | Rust registry: migrations, tables, views, triggers, FTS5 | **Wave 1** (L2, parallel with L1) |
| dev.3 | Verb surface to parity, plus render and templates | **Waves 2 + 3** (split; see Q1) |
| dev.4 | Distribution: platform packages, launcher, Python and bash retirement | **Wave 4** |
| dev.5 | `content/` compiler and the three harness adapters | **Wave 4** (parallel with retirement) |

Seed dependency chain `dev.0 → [dev.1 || dev.2] → dev.3 → [dev.4 || dev.5]` is preserved
exactly as `W0 → W1(L1||L2) → W2 → W3 → W4(L4||L5)`.

---

---

## Wave 0 — foundation, dogfood remediation, and the oracle freeze

**Wave gate (`W0-GATE`):** `bin/shepherd lint` exits 0 **and**
`conformance/run.sh --impl=python` exits 0 with a non-zero case count and a committed
corpus checksum **and** `./scripts/check-plugin.sh` reports 6/6 **and**
`bash hooks/tests/run.sh` passes.

Sequencing note: **W0-S1 has no predecessors and every other wave gate depends on it.**
Until it lands, `[gates].lint` fails on debt unrelated to any wave.

### W0-S1 — make `lint` count instances, and stop a Python gate wearing a `.sh` name

> **Rescoped after root fixed the gate.** Root ran `shepherd run init` on the six legacy
> run dirs (snapshotted first, originals verified intact); `bin/shepherd lint` now exits
> **0**. The *data* repair is done and is NOT in this step. What remains are the two
> underlying defects the repair exposed.

- **step_id:** `W0-S1` · **predecessors:** none · **estimated_loc:** 60
- **file_scope.exclusive:** `services/cli/shepherd_cli/commands/lint.py`,
  `scripts/check-plugin.sh`
- **file_scope.may_read:** `scripts/gate.sh`, `.shepherd/shepherd.toml`
- **file_scope.must_not_touch:** `crates/**`, `.shepherd/runs/**`
- **interfaces — Consumes:** nothing. **Produces:** a `lint` whose violation count is
  trustworthy, and `scripts/check-plugin.py`.

**The two defects**

1. **`lint` counts violation *kinds*, not *instances*.** It reported six stale run dirs and
   printed `FAIL (1 violation(s))`. A gate whose count does not match its findings cannot
   be used to track progress, and silently understates severity.
2. **`scripts/check-plugin.sh` is Python.** `gate.sh` invokes it via shebang so the gate
   works, but the name invites `bash scripts/check-plugin.sh`, which dies on `import` with
   a syntax error that reads exactly like a real gate failure. I hit this myself during
   central verification and briefly recorded a defect that did not exist.

**[SKILLS]** `code-style`, `markdown`
**[CONTEXT-INVENTORY]** `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/run.json` is the
canonical `run.json` shape (keys: `base`, `branch`, `kind`, `lanes`, `plan`, `run`,
`schema_version`, `seed`, `status`, `updated_at` — alphabetically sorted, `schema_version: 1`).
`bin/shepherd run init --help` documents the scaffolder.
**[DO-NOT-DUPLICATE]** `rg -n 'def init' services/cli/shepherd_cli/commands/run.py`
(expected 1) — a run-dir scaffolder already exists; wire to it, never write a second one.
**[USER-STYLE]** No new abstraction. This is data repair plus a rename.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not delete the legacy run dirs. Do not alter `v645`. Do not change
what `lint` checks — only make the tree satisfy the existing check.
**[ACCEPTANCE]**
```bash
bin/shepherd lint; test $? -eq 0
test -f scripts/check-plugin.py && ! test -f scripts/check-plugin.sh
grep -c 'check-plugin.py' scripts/gate.sh   # expect 2
./scripts/check-plugin.py --self-test       # expect 6 rules provably failable
# the count matches the findings: seed 3 distinct violations, assert "3", not "1"
cargo run -q --bin lintfixture 2>/dev/null || true
bin/shepherd lint 2>&1 | grep -qE 'FAIL \(3 violation\(s\)\)'
```

**Actions**

1. Change `lint`'s counter to count instances, not kinds, and add a regression test that
   seeds three distinct violations and asserts the message reads `3`.
2. Rename `scripts/check-plugin.sh` → `scripts/check-plugin.py`.
3. Update both `scripts/gate.sh` references (lines 54–55) and any
   `.shepherd/shepherd.toml` gate string naming the old path.
4. Re-run `bin/shepherd lint` and `./scripts/check-plugin.py --self-test`.

### W0-S10 — the lane-plan template cannot render a spec-conformant plan (DF-16, HIGH)

- **step_id:** `W0-S10` · **predecessors:** none · **estimated_loc:** 90
- **file_scope.exclusive:** `services/cli/shepherd_cli/templates/lane-plan.md.j2`
- **file_scope.may_read:** `agents/engineer.md`, `agents/conductor.md`,
  `.shepherd/runs/v645/plan.md`
- **file_scope.must_not_touch:** `crates/**`, other templates
- **interfaces — Produces:** a lane-plan template that renders this plan's step schema.
  **Consumed by root at BODY** — without it there is no lane materialization at all.

**Why this blocks BODY.** Root smoke-tested `shepherd render lane-plan.md.j2` against this
plan. It **fails**: the template reads `step.id` and `step.title`, while
`agents/engineer.md §Plan structure` mandates **`step_id`** and defines no `title` at all.
Under `StrictUndefined` that is `ERROR: undefined template variable … 'dict object' has no
attribute 'id'`, exit 4. **A spec-conformant plan is unrenderable by the template that
exists to consume it.** Do **not** "fix" this by emitting `id`/`title` from the plan — the
doctrine is the contract and the template is what is wrong.

Worse, and this is a correctness gap rather than cosmetics: `grep 'must_not_touch\|parallel_with'`
against the template returns **nothing**. The boot prompt carries only the lane-plan PATH
(#230), so whatever the template omits **the conductor never sees** — today a conductor
learns neither which paths it is forbidden to touch nor which lanes run beside it. That is
precisely the information the file-disjointness contract rests on.

**[SKILLS]** `code-style`, `markdown`
**[CONTEXT-INVENTORY]** Template's current required set: `lane_id, run, objective_title,
objective, worktree_path, base_commit, git_custody, file_scope_exclusive,
file_scope_may_read, non_goals, do_not_duplicate, acceptance, interfaces_consumes,
interfaces_produces, steps`. Note `run` not `sprint_slug`, no `plan_path`, and the
`file_scope_*`/`interfaces_*` fields flattened with underscores rather than nested as the
plan schema has them.
**[DO-NOT-DUPLICATE]** `rg -n 'step\.id|step\.title' services/cli/shepherd_cli/templates/`
(expected 2 before, 0 after).
**[USER-STYLE]** The doctrine is the contract; the template conforms to it.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not change `agents/engineer.md`'s step schema. Do not add fields the
plan schema does not define.
**[ACCEPTANCE]** — must actually render, not grep:
```bash
# a spec-shaped fixture with step_id, file_scope.must_not_touch, parallel_with
shepherd render lane-plan.md.j2 --vars .shepherd/runs/v645/fixtures/lane-plan-spec.json \
  --out /tmp/lp.md; test $? -eq 0
grep -q 'must_not_touch' /tmp/lp.md
grep -q 'parallel_with'  /tmp/lp.md
grep -q 'W0-S10'         /tmp/lp.md      # step_id rendered, not step.id
```

**Actions**

1. Change `step.id` → `step_id` and drop `step.title` (or map it to the step's first
   action line, which is the only title-shaped content the schema has).
2. Add `file_scope.must_not_touch` and `parallel_with` to the rendered output.
3. Commit a spec-shaped fixture at `.shepherd/runs/v645/fixtures/lane-plan-spec.json` and
   pin the render with the acceptance above. A grep-only acceptance would not have caught
   this defect, which is why the acceptance renders.
4. Decide whether the `file_scope_*`/`interfaces_*` flattening is deliberate; if not, align
   the vocabulary so plan schema and template speak one language.

### W0-S11 — role capability guarantees are unverified at runtime (DF-17, CRITICAL)

- **step_id:** `W0-S11` · **predecessors:** none · **estimated_loc:** 130
- **file_scope.exclusive:** `hooks/tests/lint_agent_capabilities.sh`,
  `hooks/scripts/agent_invocation_tagger.sh`
- **file_scope.may_read:** `agents/*.md`, `skills/harness/SKILL.md`
- **file_scope.must_not_touch:** `crates/**`, `content/**`
- **interfaces — Produces:** a runtime capability probe asserted against frontmatter.

**Evidence.** `agents/engineer.md:7` grants `Agent, Bash, Edit, Glob, Grep, Read, Skill,
ToolSearch, Workflow, Write, SendMessage`. This engineer session can see **neither
`Workflow` nor `Glob` nor `Grep`**. Frontmatter `tools:` declarations are **not honored as
written on this substrate.** #263 explains the `Workflow` half (availability follows
backendType; in-process teammates are denied) — it does **not** explain two ordinary read
tools vanishing from a role that grants them.

`hooks/tests/lint_agent_capabilities.sh` pins `mcp__*` tokens by grepping agent text. That
is the same anti-pattern as DF-19: **it verifies that a string is present in a file, not
that a capability exists at runtime.** Every capability guarantee in every role file is
currently unverified.

**[SKILLS]** `code-style`, `shell`
**[CONTEXT-INVENTORY]** `skills/harness/SKILL.md §Tool presence` already states the visible
tool list is the only valid oracle; the lint does not use it.
**[DO-NOT-DUPLICATE]** `rg -n 'need .*tools:' hooks/tests/` — extend the existing lint, do
not add a parallel one.
**[USER-STYLE]** bash 3.2 compatible.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not remove `tools:` frontmatter — it remains the declared intent. Do not
attempt to *make* the platform honor it; that is not ours to fix.
**[ACCEPTANCE]**
```bash
bash hooks/tests/lint_agent_capabilities.sh            # still passes
# and now records an observed-vs-declared delta rather than only grepping text
bash hooks/tests/lint_agent_capabilities.sh --self-test # proves it can fail
rg -q 'observed|runtime' hooks/tests/lint_agent_capabilities.sh
```

**Actions**

1. Add a runtime capability record: each dispatched role reports its **observed** tool list
   once at boot, written to the run dir.
2. Change the lint to diff observed against declared and report the delta as a finding,
   rather than asserting token presence in prose.
3. Document in `skills/harness/SKILL.md` that `tools:` is declared intent, not a runtime
   guarantee, and that roles must probe.

### W0-S12 — convert string-presence "wiring tests" into behavior tests (DF-19, HIGH)

- **step_id:** `W0-S12` · **predecessors:** none · **estimated_loc:** 140
- **file_scope.exclusive:** `hooks/tests/test_v644_wiring.sh`
- **file_scope.may_read:** `agents/conductor.md`, `services/cli/shepherd_cli/commands/plan.py`
- **file_scope.must_not_touch:** `crates/**`, `agents/**`
- **interfaces — Produces:** wiring tests that exercise behavior. **This is the step that
  makes the CHANGELOG-vs-tracker divergence detectable**, which is what seed §2 opens with.

**Evidence.** `test_v644_wiring.sh` "verifies" #268, #269 and #270 entirely with
`need <file> <string>` — grep for a phrase in a doc:

```
need agents/conductor.md   "had no active task"        # claims "#270 fixed"
need agents/conductor.md   "shepherd plan lane-drift"  # claims "#269 fixed"
need services/cli/.../plan.py "lane-drift"             # claims "CLI implements it"
```

It **asserts prose, not behavior**. It cannot detect that #270 is still broken — which
this run measured **5/5** — because the doctrine text describing the fix is present, and
that is all it checks. It equally could not detect that `shctx plan lane-drift` is
unreachable through the bash surface, because it greps `plan.py` instead of invoking
anything.

**[SKILLS]** `code-style`, `shell`
**[CONTEXT-INVENTORY]** `shepherd plan lane-drift v645` works and exits 0;
`shctx plan lane-drift` errors with `unknown subcommand`. A behavior test would have
caught that; the string test did not.
**[DO-NOT-DUPLICATE]** `rg -c 'need ' hooks/tests/test_v644_wiring.sh` — replace the
assertions in place; do not add a second test file alongside.
**[USER-STYLE]** A test that cannot fail is not a test.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not delete coverage. Every string assertion becomes a behavior
assertion, or is explicitly marked unverifiable with the reason.
**[ACCEPTANCE]**
```bash
bash hooks/tests/test_v644_wiring.sh
rg -c 'need .*"' hooks/tests/test_v644_wiring.sh | grep -qx 0   # no string-only asserts
# each claim now invokes something
rg -q 'shepherd plan lane-drift .* ; test \$\? -eq 0' hooks/tests/test_v644_wiring.sh
```

**Actions**

1. Replace each `need <file> <string>` with an invocation asserting the documented behavior.
2. Where a behavior genuinely cannot be exercised in-process (#270's notification routing),
   mark it `UNVERIFIABLE-IN-TEST` with the reason, rather than greping prose and calling it
   verified.
3. Re-grade the affected issues against the new tests.

### W0-S13 — give the boundary gates real negative controls (A1 finding #1)

- **step_id:** `W0-S13` · **predecessors:** none · **estimated_loc:** 110
- **file_scope.exclusive:** `.github/workflows/boundaries.yml`
- **file_scope.may_read:** `scripts/check-workspace.sh`, `scripts/check-plugin.sh`,
  `crates/core/Cargo.toml`
- **file_scope.must_not_touch:** `crates/**` source, `scripts/**`
- **interfaces — Produces:** three boundary gates each provably able to fail.

**Evidence.** The three grep-based gates at `.github/workflows/boundaries.yml:78-178`
(forbidden-dependency, process/argv, config-I/O) claim negative-control verification in a
**prose comment only** — there is no committed fixture. `check-workspace.sh` and
`check-plugin.sh` both ship genuine `--self-test` fixtures; these do not. A typo narrowing
one of those regexes would pass silently forever.

Seed decision 8's entire premise is *"enforced by the `engine-boundary` CI job, not by
prose… a rule that only lives in a doc drifts."* **One third of that enforcement is
currently prose.**

**[SKILLS]** `code-style`, `shell`
**[CONTEXT-INVENTORY]** `scripts/check-workspace.sh --self-test` and
`./scripts/check-plugin.py --self-test` are the in-repo pattern to copy — each proves its
rules can fail against a deliberately-broken fixture.
**[DO-NOT-DUPLICATE]** `rg -n 'self-test' scripts/ .github/workflows/` — reuse the existing
self-test idiom, do not invent a third.
**[USER-STYLE]** A gate with no negative control may be silently passing.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not weaken any gate to make a fixture pass. Do not touch `crates/core`
source — the fixture is synthetic.
**[ACCEPTANCE]**
```bash
# each of the three gates fails against its deliberately-violating fixture
bash .github/scripts/boundary-selftest.sh; test $? -eq 0
# and the real tree still passes
rg -q 'negative control' .github/workflows/boundaries.yml
```

**Actions**

1. Add a synthetic fixture per gate that genuinely violates it (a forbidden dep, a
   `std::process` call, a `File::with_name` call).
2. Add `boundary-selftest.sh` asserting each gate rejects its fixture and accepts the real
   tree.
3. Wire it into `boundaries.yml` ahead of the real gates.

### W0-S2 — a clean clone can spawn (DF-01)

- **step_id:** `W0-S2` · **predecessors:** none · **estimated_loc:** 90
- **file_scope.exclusive:** `hooks/scripts/session_open.sh`, `commands/spawn.md`
- **file_scope.may_read:** `services/cli/shepherd_cli/commands/doctor.py`,
  `skills/context/schema/**`
- **file_scope.must_not_touch:** `crates/**`, `conformance/**`, `content/**`
- **interfaces — Consumes:** nothing. **Produces:** the guarantee that
  `shctx doctor` reports a bootstrapped registry on a fresh clone, which is
  release-gate criterion C.1.

**[SKILLS]** `code-style`, `shell`
**[CONTEXT-INVENTORY]** `commands/spawn.md:54` — Preflight Check 4 already does
scaffold-then-proceed for `shepherd.toml` via `shctx config init`. The DB has no
equivalent. Migration source is `skills/context/schema/` (`0001_init.sql` + 20 under
`migrations/` + 5 under `views/` = 21 applied versions).
**[DO-NOT-DUPLICATE]** `rg -n 'shctx config init' commands/spawn.md` (expected 1) — model
the DB check on the existing config check; do not invent a second preflight idiom.
**[USER-STYLE]** bash 3.2 compatible — no `${,,}`, no `mapfile`, no `declare -A`.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not change the migration SQL. Do not auto-run destructive repair — a
missing DB is scaffolded, a corrupt one is reported.
**[ACCEPTANCE]**
```bash
# in a scratch dir with no .shepherd/
cd "$(mktemp -d)" && git init -q && shctx doctor; test $? -ne 0   # fails closed today
# after the fix, preflight scaffolds and doctor reports a bootstrapped registry
```

**Actions**

1. Add a Preflight Check (numbered after 4) to `commands/spawn.md`: if the registry DB is
   absent, run `shctx init`, emit `[REGISTRY] scaffolded`, PROCEED. Non-blocking, exactly
   parallel to Check 4's wording.
2. Mirror it in `hooks/scripts/session_open.sh` so a session that never runs `/shepherd:spawn`
   still self-heals.
3. Verify against a scratch directory that a fresh tree bootstraps without hand-running
   `shctx init`.

### W0-S3 — the diagnostic tool stops prescribing commands that do not exist

- **step_id:** `W0-S3` · **predecessors:** none · **estimated_loc:** 70
- **file_scope.exclusive:** `services/cli/shepherd_cli/commands/doctor.py`
- **file_scope.may_read:** `services/cli/shepherd_cli/commands/refresh.py`,
  `services/cli/tests/test_doctor.py`
- **file_scope.must_not_touch:** `crates/**`, `hooks/**`
- **interfaces — Consumes:** nothing. **Produces:** `doctor` remediation strings that are
  runnable verbatim; consumed by W0-S2's acceptance and by release-gate C.1.

**[SKILLS]** `code-style`, `python`
**[CONTEXT-INVENTORY]** `shctx refresh --help` enumerates the ONLY accepted scopes:
`symbols|shapes|github|artifacts|telemetry|all`. `doctor.py:1704` already derives the exit
code correctly (`1` on fail, `2` on warn, else `0`) and `:1745` raises it — **do not touch
the exit-code logic; DF-07 is refuted and it is correct as written.**
**[DO-NOT-DUPLICATE]** `rg -n "scope=issues|scope=prs|scope=releases" services/cli/`
(expected: the doctor fix-strings only) — these three scopes do not exist anywhere in
`refresh`; they must become `github`.
**[USER-STYLE]** Truth over politeness: a fix-string that cannot be run is a lie in the
tool's own voice.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT "fix" the exit code (already correct). Do NOT add an `issues`
scope to `refresh` — the correct scope is the existing `github`.
**[ACCEPTANCE]**
```bash
# every remediation string doctor emits must be runnable
bin/shepherd doctor --format=json | python3 -c "
import json,sys,re
bad=[r for r in json.load(sys.stdin) if 'scope=issues' in str(r) or 'scope=prs' in str(r) or 'scope=releases' in str(r)]
assert not bad, bad; print('ok: no unrunnable remediation strings')"
shctx refresh --scope=github; test $? -eq 0
```

**Actions**

1. Replace `--scope=issues` / `--scope=prs` / `--scope=releases` in doctor's fix-strings
   with the real scope `github` (DF-08).
2. Fix the artifacts freshness marker so `refresh --scope=artifacts` stamps it and the
   warn clears (DF-09). Today it prints `ok`, exits 0, and doctor still reports
   `never refreshed` — a permanent, meaningless warn.
3. Add a `--version` subcommand to the `shctx` surface that prints the version and exits 0
   (DF-06, narrowed: it currently exits 1 with `unknown subcommand`, which is *correct*
   failure behavior but leaves adapters with no version probe).
4. Add a regression test asserting every emitted fix-string parses as a runnable
   `shctx`/`shepherd` invocation.

### W0-S4 — model slugs are translated by the engine, not by each dispatcher (DF-03)

- **step_id:** `W0-S4` · **predecessors:** none · **estimated_loc:** 110
- **file_scope.exclusive:** `services/cli/shepherd_cli/commands/models.py`
- **file_scope.may_read:** `services/cli/shepherd_cli/config_schema.py`,
  `services/cli/tests/test_models.py`, `.shepherd/shepherd.toml`
- **file_scope.must_not_touch:** `crates/**`, `agents/**`
- **interfaces — Produces:** `shctx models resolve <role> --harness=<claude|codex|pi>`
  emitting a slug the target harness's dispatch surface actually accepts. Consumed by
  W4's three adapters.

**[SKILLS]** `code-style`, `python`
**[CONTEXT-INVENTORY]** `config_schema.py:700` defaults `root = "opus[1m]"`.
`test_models.py:51` encodes `"opus[1m]" if role in _OPUS_ROLES else "sonnet"`. The Claude
`Agent` tool's `model` parameter is a **closed enum**: `sonnet|opus|haiku|fable` — `opus[1m]`
is rejected. Codex expresses the same intent as `[profiles]` with `model` +
`reasoning_effort` (`sol/max`, `terra/high`, `terra/medium`, per the installed
`shepherd.codex.toml`). Pi pins per role via a subprocess `--model` flag.
**[DO-NOT-DUPLICATE]** `rg -n 'opus\[1m\]' --include='*.py' services/cli` (expected 4) —
one translation table, not a rewrite at each call site.
**[USER-STYLE]** This is the harness-agnostic core's job: an untracked translation done
silently by every dispatcher is exactly the drift this arc exists to end.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not change which model a role gets. Do not remove `opus[1m]` as the
*intent* slug — translate it at the boundary.
**[ACCEPTANCE]**
```bash
shctx models resolve engineer --harness=claude | grep -qxE 'sonnet|opus|haiku|fable'
shctx models resolve engineer --harness=codex  | grep -q 'sol/max'
shctx models resolve discovery --harness=claude | grep -qx 'sonnet'
shctx models resolve engineer                   | grep -qx 'opus[1m]'   # intent preserved
```

**Actions**

1. Add a `--harness` parameter to `models resolve`, defaulting to the current behavior so
   nothing existing breaks.
2. Add one translation table: intent slug → per-harness concrete slug. Claude collapses
   `opus[1m]` → `opus`; Codex maps to a `[profiles]` name; Pi emits the bare model id.
3. Table-test every (role × harness) pair, asserting Claude output is always inside the
   closed enum.

### W0-S5 — dispatch doctrine matches the platform that actually ships (DF-02, DF-11, DF-E1)

- **step_id:** `W0-S5` · **predecessors:** none · **estimated_loc:** 130
- **file_scope.exclusive:** `commands/spawn.md`, `skills/harness/SKILL.md`
- **file_scope.may_read:** `agents/engineer.md`, `skills/shepherd/references/pipeline.md`,
  `skills/shepherd/SKILL.md`, `.shepherd/runs/v645/dogfood.md`
- **file_scope.must_not_touch:** `crates/**`, `services/cli/**`
- **interfaces — Consumes:** nothing. **Produces:** the corrected dispatch facts that
  W4's adapter contracts and `agents/*.md` compile against.

> **W0-S2 also lists `commands/spawn.md` as exclusive. These two steps are therefore
> NOT file-disjoint and MUST NOT be dispatched in the same parallel batch.** W0-S5
> declares `predecessors: [W0-S2]` in the Stage Graph for this reason. This is the one
> ordering constraint inside Wave 0.

**[SKILLS]** `code-style`, `markdown`
**[CONTEXT-INVENTORY]** `commands/spawn.md:250` and `:344` state teammates are created by
a "native teammate-spawn, NEVER the Agent/Task tool". Measured on CC 2.1.229: the `Agent`
tool carries `name` ("makes it addressable via SendMessage"), `team_name` is documented
"Deprecated; ignored", and a teammate passing `name` is refused with "Teammates cannot
spawn other teammates — the team roster is flat." `agents/engineer.md:7` grants
`Workflow`, `Glob`, `Grep`; none of the three is present in a live engineer teammate's
tool list.
**[DO-NOT-DUPLICATE]** `rg -n 'native teammate-spawn' commands/ skills/ agents/`
(expected 3) — correct each in place; do not add a fourth description of the mechanism.
**[USER-STYLE]** Truth over politeness — the doctrine currently describes a platform
shape that does not ship.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not change the tier model (root/conductor/flock). Do not retire
`WORKFLOW-VEHICLE-PROBE` — it remains the correct substrate test; only its expected
outcome changes.
**[ACCEPTANCE]**
```bash
# doctrine no longer claims Agent() is not the teammate spawn
rg -c 'NEVER the Agent/Task tool' commands/ skills/ agents/ ; test $? -eq 1
# the flat-roster fact is documented
rg -q 'roster is flat|cannot spawn other teammates' skills/harness/SKILL.md
# the async-Agent notification-routing fact is documented
rg -q 'task-tree owner' skills/harness/SKILL.md
```

**Actions**

1. Correct `commands/spawn.md:250,344`: `Agent(subagent_type, name)` **is** the teammate
   spawn on CC 2.1.229.
2. Document the flat-roster constraint: a teammate dispatching its own sub-flock MUST
   omit `name`, or the call is refused outright.
3. Document the notification-routing fact in `skills/harness/SKILL.md`: **async `Agent()`
   delivers the completion `<task-notification>` to the task-tree owner, not to the
   dispatching agent** — independent of vehicle. Record that `Workflow` was *absent*
   when this was measured, so it is not a Workflow behavior.
4. Record that `tools:` frontmatter is not authoritative on this substrate (DF-E1), and
   that `WORKFLOW-VEHICLE-PROBE` returning negative is an expected outcome for a
   teammate, not an anomaly.

### W0-S6 — declared capability becomes probed capability (DF-04, DF-E2)

- **step_id:** `W0-S6` · **predecessors:** none · **estimated_loc:** 80
- **file_scope.exclusive:** `hooks/scripts/_lib.sh`, `skills/shepherd/SKILL.md`
- **file_scope.may_read:** `.shepherd/shepherd.toml`,
  `hooks/tests/test_engineer_self_contained.sh`
- **file_scope.must_not_touch:** `crates/**`, `commands/**`
- **interfaces — Produces:** `shepherd_mcp_available <svc>` returning 0/1 by runtime
  probe; consumed by every `[mcp]`-gated path.

**[SKILLS]** `code-style`, `shell`
**[CONTEXT-INVENTORY]** `.shepherd/shepherd.toml` sets `[mcp].github = true`, but no
GitHub MCP is registered in this session. `SKILL.md §MCP-over-CLI` already specifies the
correct degrade (`[WARN] MCP <svc> unavailable — using <cli>`); nothing in the config path
performs it. Separately, `SKILL.md:20` and `hooks/tests/test_engineer_self_contained.sh`
both name `.claude/shepherd.toml`, which does not exist — the live config is
`.shepherd/shepherd.toml`.
**[DO-NOT-DUPLICATE]** `rg -n '\.claude/shepherd\.toml' --glob '!CHANGELOG.md'` — every
hit is a path that resolves to nothing; fix them all, add no new path.
**[USER-STYLE]** bash 3.2 compatible.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not remove the `[mcp]` config keys — they remain the operator's
*intent*; the probe decides *availability*.
**[ACCEPTANCE]**
```bash
rg -c '\.claude/shepherd\.toml' --glob '!CHANGELOG.md' . ; test $? -eq 1   # zero hits
bash -c 'source hooks/scripts/_lib.sh && type shepherd_mcp_available' | grep -q function
bash hooks/tests/test_engineer_self_contained.sh
```

**Actions**

1. Add `shepherd_mcp_available <svc>` to `_lib.sh`: true only when the config flag is on
   **and** a runtime probe resolves a tool for that service.
2. Emit the sanctioned `[WARN] MCP <svc> unavailable — using <cli>` from that helper so
   the degrade is automatic rather than remembered.
3. Correct every `.claude/shepherd.toml` reference to `.shepherd/shepherd.toml`,
   including in `hooks/tests/test_engineer_self_contained.sh`.

### W0-S7 — `packages/` npm workspace skeleton

- **step_id:** `W0-S7` · **predecessors:** none · **estimated_loc:** 200
- **file_scope.exclusive:** `packages/` (NEW), root `package.json` (NEW)
- **file_scope.may_read:** `Cargo.toml`, `scripts/install-shctx-launcher.sh`, `bin/shepherd`
- **file_scope.must_not_touch:** `crates/**`, `services/cli/**`, `content/**`
- **interfaces — Produces:** `packages/harness-claude`, `packages/harness-codex`,
  `packages/harness-pi`, `packages/compiler` — the workspace W4 fills in.

**[SKILLS]** `code-style`, `typescript`
**[CONTEXT-INVENTORY]** `cargo metadata --no-deps` reports 5 members at `6.4.5`; npm
package versions must track that single source. `scripts/install-shctx-launcher.sh:71`
documents the publisher-glob resolution the launcher must eventually replace.
**[DO-NOT-DUPLICATE]** `rg -n '"name": "@fl03' packages/ 2>/dev/null | wc -l` (expected 0
before this step) — no npm package exists yet; this creates the first.
**[USER-STYLE]** Vanilla. No bundler, no framework. `optionalDependencies` is the
shipping pattern (esbuild, biome, lightningcss, turbo all use it).
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT publish. Do NOT implement adapter logic — that is W4. Skeleton,
manifests, and the dependency-rule gate test only.
**[ACCEPTANCE]**
```bash
npm ls --workspaces --json >/dev/null 2>&1 || node -e "
const p=require('./package.json'); if(!p.workspaces) throw new Error('no workspaces');
console.log('workspaces:', p.workspaces.length)"
test -d packages/harness-claude && test -d packages/harness-codex && test -d packages/harness-pi
node packages/scripts/check-deps.mjs   # npm-side dependency-rule gate, self-testing
```

**Actions**

1. Create the root `package.json` declaring `workspaces: ["packages/*"]`, version pinned
   to the Cargo workspace version.
2. Scaffold `packages/harness-{claude,codex,pi}` and `packages/compiler` with manifests,
   `README.md`, and a failing placeholder test each.
3. Write `packages/scripts/check-deps.mjs`: the npm-side analogue of
   `scripts/check-features.sh` — no adapter may depend on another adapter; all must
   depend only on the compiler and the platform binary. Include a self-test proving each
   rule can fail (the layout-contract spec's discipline: a gate with no negative control
   may be silently passing).

### W0-S8 — `content/` single-source tree and the drift reconciliation

- **step_id:** `W0-S8` · **predecessors:** none · **estimated_loc:** 260
- **file_scope.exclusive:** `content/` (NEW)
- **file_scope.may_read:** `agents/*.md`, `commands/*.md`, `skills/**/SKILL.md`,
  `.shepherd/runs/v645/reports/discovery-d1-harness.md`
- **file_scope.must_not_touch:** `agents/**`, `commands/**`, `skills/**`, `hooks/**`
  (emission into these is W4-S*; this step only *reads* them), `crates/**`
- **interfaces — Produces:** `content/roles/*.md`, `content/skills/*/SKILL.md`,
  `content/predicates/*.toml`, and `content/RECONCILIATION.md`. Consumed by every W4
  adapter step.

**[SKILLS]** `code-style`, `markdown`
**[CONTEXT-INVENTORY]** Source corpus measured: `agents/` 9 files / 1,541 lines,
`commands/` 7 files / 864 lines, `skills/` 32 files / 4,370 lines, `hooks/scripts/` 32
shell files / 4,749 lines. The installed `codex-shepherd@1.0.2` skills tree is the drift
baseline. Full matrix and evidence:
`.shepherd/runs/v645/reports/discovery-d1-harness.md §Engineer follow-up`.
**[DO-NOT-DUPLICATE]** `rg -l 'name: (engineer|coder|critic|auditor|worker|discovery)'
agents/` (expected 6 of 9) — `content/roles/` must be authored *from* these, never as a
parallel second copy. The whole point is to end dual maintenance.
**[USER-STYLE]** One concept per file. The abstract capability vocabulary (`read`,
`search`, `shell`, `report-write`, `dispatch`) is the contract — never a concrete tool
name, because tool names are exactly what differs per harness.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT emit yet and do NOT delete anything from the root layout. This
step creates the source of truth and proves it round-trips; emission is W4.
**[ACCEPTANCE]**
```bash
test -f content/RECONCILIATION.md
# every Claude role has a content source
for f in agents/*.md; do test -f "content/roles/$(basename $f)" || { echo "MISSING $f"; exit 1; }; done
# write-eligibility is a hard fact on every role (Codex explorer cannot write)
python3 - <<'EOF'
import glob,re,sys
bad=[f for f in glob.glob('content/roles/*.md') if not re.search(r'^write_eligible:\s*(true|false)$',open(f).read(),re.M)]
assert not bad, f"roles missing write_eligible: {bad}"
print(f"ok: {len(glob.glob('content/roles/*.md'))} roles carry write_eligible")
EOF
```

**Actions**

1. Create `content/roles/*.md`: one per current `agents/*.md`, carrying the abstract
   capability vocabulary plus a **mandatory `write_eligible: true|false`** field. This
   field is not cosmetic — Codex's `explorer` type *cannot write files at all*, so a role
   whose write-eligibility is only a convention compiles into a broken Codex adapter
   (D1 Hazard 1).
2. Create `content/skills/` from the 7 Claude skills.
3. Write `content/RECONCILIATION.md` resolving the measured drift against Codex 1.0.2,
   one row per divergence with a decision:

   | Claude | Codex 1.0.2 | Decision required |
   |---|---|---|
   | `skills/adaptation` | `adapt` + `self-improvement` | keep split or re-merge |
   | `skills/harness` | absent | Claude-only; do not emit for Codex |
   | `commands/plant.md` + `agents/planter.md` | `skills/plant` | which shape is canonical |
   | 9 × `agents/*.md` | zero role files (`[agent_types]` TOML) | roles compile to a table for Codex |
   | 7 skills | 8 skills | net +1 to reconcile |

4. Create `content/predicates/*.toml` — the declarative guard-predicate spec both the
   Rust engine and Pi's TS layer interpret (decision 2). Every predicate carries at least
   one allow case and one deny case.

### W0-S9 — freeze the conformance oracle from the Python CLI (#281, CRITICAL)

- **step_id:** `W0-S9` · **predecessors:** none · **estimated_loc:** 340
- **file_scope.exclusive:** `conformance/` (NEW)
- **file_scope.may_read:** `services/cli/**`, `.shepherd/runs/v645/run.json`,
  `skills/context/schema/**`
- **file_scope.must_not_touch:** `crates/**`, `services/cli/**` (read-only), `content/**`
- **interfaces — Produces:** `conformance/run.sh --impl=<python|rust> [--suite=<name>]`,
  `conformance/cases/**`, `conformance/CHECKSUM`. **Every** W1–W3 acceptance consumes this.

**[SKILLS]** `code-style`, `shell`, `python`
**[CONTEXT-INVENTORY]** The canonical `run.json` is alphabetically key-sorted with
`schema_version: 1` (verified against `.shepherd/runs/v645/run.json`). The registry
parity surface is `sqlite_master` (45 tables, 14 views, 68 indexes, 7 triggers, 19
`json_valid` CHECKs, 2 FTS5 external-content tables tokenized
`unicode61 remove_diacritics 2`). Test fixtures today are programmatic and ephemeral in
`conftest.py` — there is no stored golden corpus, which is why this step precedes all
port code.
**[DO-NOT-DUPLICATE]** `find . -name '*.golden' -o -name '__snapshots__' -not -path './target/*' | wc -l`
(expected 0) — no snapshot corpus exists; this creates the first and only one.
**[USER-STYLE]** Deterministic space, not latent space: the oracle is a script plus
stored bytes. Anything eyeballed is not a conformance case.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT write any Rust. Do NOT modify `services/cli/` — this step observes
it. `--impl=rust` must exist as a runnable path that reports "0 cases implemented" rather
than erroring.
**[ACCEPTANCE]**
```bash
conformance/run.sh --impl=python; test $? -eq 0
test "$(conformance/run.sh --impl=python --count)" -gt 0
test -f conformance/CHECKSUM && test -s conformance/CHECKSUM
conformance/run.sh --impl=python --verify-checksum   # corpus is content-addressed
conformance/run.sh --impl=rust; test $? -eq 0        # 0 cases, exits clean
# Q6 / correction C11 — the five guard-driving CLI behaviors decision 3 wrongly assumed
# did not exist. Without this suite a Rust CLI passes full conformance and still breaks
# four guard scripts. MUST-FIX-BEFORE-DISPATCH (critic pass 2, HIGH).
conformance/run.sh --impl=python --suite=guard-cli; test $? -eq 0
```

**Actions**

1. Build the harness: per case, capture stdout, exit code, `run.json` bytes, rendered
   template bytes, and an order-normalized `sqlite_master` dump.
2. Pin every non-determinism source before capture — timestamps, UUIDs, absolute paths,
   hostname, locale, env leakage, and dict/row iteration order. Each gets an explicit
   substitution rule recorded in `conformance/NORMALIZATION.md`. An unpinned source is a
   flaky case, and a flaky oracle is worse than none.
3. Separate PURE cases (deterministic stdout, no mutation) from MUTATING cases (touch DB
   or filesystem); the two need different harnessing and different teardown.
4. Commit the corpus plus `conformance/CHECKSUM` so drift is detectable.
5. Provide `--impl=rust` as a real but empty lane so W1–W3 have a target from day one.
6. **Build `--suite=guard-cli`** capturing exact stdout, exit code and JSON shape for the
   five guard-driving CLI behaviors (Q6, correction C11):
   `dups check --stdin --as <path> --json`, `seed verify <path>`,
   `teammate heartbeat --note=<s>`, `deliverable stalled --since-mins=<n>`, `status`.
   These are the calls `dups_write_guard.sh:65`, `seed_preflight_check.sh:64`,
   `teammate_idle.sh:57,88` and `user_prompt_submit.sh:102` make; three of those four
   scripts touch DB state **exclusively** through the CLI, so a schema-only oracle cannot
   see them at all.

---

## Wave 1 — the engine and the registry, in parallel

**Wave gate (`W1-GATE`):** `conformance/run.sh --impl=rust --suite=run-state` byte-clean
against the Python oracle **and** the order-normalized `sqlite_master` dump identical
between implementations **and** `cargo check --workspace` exit 0 **and**
`scripts/check-features.sh` 23/23 **and** `scripts/check-features.sh --targets` green
(requires `brew install llvm`; Apple system clang has no wasm backend).

Absorbs seed dev.1 (`crates/core`) and dev.2 (`crates/registry`). These are file-disjoint
and run concurrently — they are the two lanes permitted a `CARGO_TARGET_DIR` under
constraint 5.

### W1-S1 — canonical run state and atomic write (#282)

- **step_id:** `W1-S1` · **predecessors:** `W0-S9` · **estimated_loc:** 420
- **file_scope.exclusive:** `crates/core/src/run.rs`, `crates/core/src/run/`
- **file_scope.may_read:** `crates/core/src/lib.rs`, `conformance/cases/run-state/**`,
  `services/cli/shepherd_cli/commands/run.py`
- **file_scope.must_not_touch:** `crates/registry/**`, `crates/cli/**`, `crates/render/**`
- **interfaces — Consumes:** `conformance/run.sh --impl=rust --suite=run-state` (W0-S9).
  **Produces:** `pub struct RunState`, `pub fn RunState::load(&Path) -> Result<RunState>`,
  `pub fn RunState::store(&self, &Path) -> Result<()>`, `pub fn RunState::to_canonical_json(&self) -> String`.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Canonical shape from `.shepherd/runs/v645/run.json`: keys `base`,
`branch`, `kind`, `lanes`, `plan`, `run`, `schema_version`, `seed`, `status`,
`updated_at`, alphabetically sorted, `schema_version: 1`. `crates/core` currently holds
666 lines and must not gain `clap`, `anyhow`, an I/O backend, `std::process`, or any
branch on `Harness` (decision 8, enforced by the `engine-boundary` job).
**[DO-NOT-DUPLICATE]** `rg -n 'struct RunState|fn to_canonical_json' crates/` (expected 0
before this step).
**[USER-STYLE]** `thiserror` in the library, never `anyhow`. Narrow types at the boundary.
No hollow wrappers — `RunState` earns existence by enforcing the sorted-key invariant.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not add a CLI surface. Do not touch the registry. Do not introduce a
new dependency (decision 7 is closed).
**[ACCEPTANCE]**
```bash
conformance/run.sh --impl=rust --suite=run-state   # byte-clean vs python oracle
cargo check -p shepherd-core --no-default-features --features alloc
cargo check -p shepherd-core --target wasm32-unknown-unknown   # boundary holds
# unknown keys must survive a load/store round-trip
cargo test -p shepherd-core run::tests::unknown_keys_round_trip
```

**Actions**

1. Define `RunState` with an `#[serde(flatten)]` capture map so unknown keys round-trip
   rather than being silently dropped (the seed asserts both round-trip preservation and
   recursively sorted output).
2. Implement recursively sorted canonical JSON serialization.
3. Implement atomic write: temp file, `fsync`, rename.
4. Table-test against the frozen corpus, including a case with unknown keys and a case
   with nested objects proving the sort is recursive, not top-level only.

### W1-S2 — migration runner and schema parity (#283)

- **step_id:** `W1-S2` · **predecessors:** `W0-S9` · **estimated_loc:** 380
- **file_scope.exclusive:** `crates/registry/src/migrate.rs`, `crates/registry/src/migrate/`
- **file_scope.may_read:** `skills/context/schema/**`, `conformance/cases/schema/**`,
  `crates/registry/src/lib.rs`
- **file_scope.must_not_touch:** `crates/core/**`, `crates/cli/**`, `skills/context/schema/**` (copy, never edit)
- **interfaces — Consumes:** `conformance/run.sh --impl=rust --suite=schema` (W0-S9).
  **Produces:** `pub fn migrate::apply_all(&Connection) -> Result<u32>` returning the
  highest applied version.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** **21 migrations, and the +1 is a trap (correction C1).**
`schema/migrations/` holds 20 files (`0002`–`0021`). `schema/0001_init.sql` sits at the
schema-dir **top level, outside `migrations/`**, and is applied by a *separate* path —
`shctx init`. Both existing runners glob `migrations/[0-9][0-9][0-9][0-9]_*.sql`, which
matches 20. Live `schema_versions` holds **21** rows.

> **A Rust runner that globs `migrations/*.sql` silently skips the entire baseline
> schema** and then fails every downstream parity assertion for reasons that look
> unrelated. Glob the 20, then apply `0001_init.sql` explicitly as version 1.

`schema_versions` is the state table; `PRAGMA user_version` is 0 and unused — which is
exactly why `rusqlite_migration` is rejected (decision 6). Target objects, **live counts,
not statement counts** (C2–C5, C5-bis): **36 tables** (34 base + 2 FTS5 virtual),
**14 views**, **34 named indexes**, **7 triggers** (6 FTS5 sync +
`trg_watch_paths_updated_at`), **24 `json_valid` CHECKs**, 2 FTS5 external-content tables
tokenized `unicode61 remove_diacritics 2`.

> **Do not size off the mesh's 39/25/40/25.** Those are `grep -c "CREATE …"` counts across
> migration *history* and include rename-dance transients (`mem_entries_new`,
> `locks_history_new`, `focus_new`, `mailbox_new`) plus the fully-dropped `mailbox`.

**Out of scope for this step, and it needs its own:** `shepherd migrate --layout v2/v3/v4`
is a **different class of migration** — workdir/filesystem moves (`root.db`→`shepherd.db`,
`plans/`→`docs/plans/`), pure Python, no `.sql` counterpart. Decision 6 covers only the 21
schema files and is correct about those. The layout migrations are tracked as **W3-S30**
(see Wave 3) so they do not vanish with `services/cli/`.
**[DO-NOT-DUPLICATE]** `rg -n 'schema_versions' crates/registry/` (expected 0 before this
step). Migration SQL is copied **verbatim**; a rewritten migration is a defect.
**[USER-STYLE]** `rusqlite` with `features = ["bundled"]` only. There is no `fts5` cargo
feature — `libsqlite3-sys` passes `-DSQLITE_ENABLE_FTS5` unconditionally on the bundled
path. Assert the *behavior*, never the `ENABLE_JSON1` compile flag (absent since JSON went
core at SQLite 3.38).
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not edit any `.sql`. Do not add a migration. Do not change the tokenizer.
**[ACCEPTANCE]**
```bash
conformance/run.sh --impl=rust --suite=schema    # sqlite_master identical, order-normalized
cargo test -p shepherd-registry migrate::tests::applies_twenty_one
# FTS5 present and tokenizer preserved
cargo test -p shepherd-registry migrate::tests::fts5_tokenizer_verbatim
# SEEDED predicate from seed §6 #283, restored after the critic caught it dropped:
sqlite3 "$DB" "PRAGMA compile_options;" | grep -q ENABLE_FTS5
# the 8 guard-frozen objects exist with their exact column sets (tier (a), correction C10)
for t in deliverables focus mem_entries spawn_leads sprint_metrics teammates worktrees; do
  sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE name='$t';" | grep -qx 1 || exit 1
done
sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_teammates_live';" | grep -qx 1
```

> `PRAGMA compile_options | grep ENABLE_FTS5` is a **seeded** §6 predicate for #283 and I
> had silently dropped it. Restored. Note it does **not** contradict decision 4's "assert
> the behavior, never that flag" — that warning is about `ENABLE_JSON1`, which is absent
> from `compile_options` even though `json_valid` works. `ENABLE_FTS5` genuinely is present
> on the bundled path and the seed asserts it by name.

**Actions**

1. Copy all 21 migration files plus the 5 view files into the crate as embedded assets,
   byte-identical.
2. Implement the runner against `schema_versions` (never `user_version`), applying in
   version order and recording each.
3. Assert post-migration object counts match the frozen corpus exactly: 45/14/68/7/19.
4. Assert both FTS5 tables carry `tokenize='unicode61 remove_diacritics 2'` and that the
   6 sync triggers exist by name.

---

---

---

> ## Waves 2–3 are NOT dispatched from this plan
>
> **This is the critic's HIGH decomposition finding, fixed structurally rather than
> argued with.** The critic was right: Waves 2/3 were written at module granularity
> (~1,000 LOC per nominal step) while `pipeline.md §Lane law` binds steps to ~80–100 LOC,
> and *"under-decomposition → RECONSIDER to @engineer"* is the literal named trigger. My
> flagging the gap honestly in Q1 did not make the plan dispatchable, and a plan that a
> conductor cannot walk mechanically is a half-plan.
>
> The fix is in the Stage Graph, not in the prose: **`W1-GATE → OPERATOR-GATE-Q1 →
> PLAN-REVISION-POST-Q1 → PLAN-GATE-POST-Q1`**. Waves 2 and 3 reach a conductor only after
> a fresh `@engineer` pass decomposes them to the floor and a fresh `@critic` gates that
> decomposition. **Nothing under-decomposed is dispatchable from this document.**
>
> That also fixes the critic's second HIGH finding: the graph previously routed
> `W1-GATE --on-green--> WAVE-2-IMPL` unconditionally, so a conductor walking the graph
> would have blown straight past the Q1 stop-boundary the prose recommended — a silent
> quota overrun and a directive-3 violation. The operator gate is now a node, not a
> paragraph.
>
> The two wave sections below therefore define **scope, gates and measured surface** —
> the inputs the post-Q1 decomposition consumes. They are deliberately not step lists.

## Wave 2 — render, template parity, and the mechanically-portable verbs

**Wave gate (`W2-GATE`):** `conformance/run.sh --impl=rust --suite=render` byte-clean,
with `template_sha256`, `vars_sha256` and `output_sha256` all reproducing identically.

**Measured surface** (engineer-derived; A2/D2 did not return in time — see §Proof of
dispatch). The template surface is far smaller than the seed implies, which materially
de-risks this wave:

| Fact | Measured |
|---|---|
| Templates | **5**: `boot-prompt.md.j2`, `plan.md.j2`, `seed.md.j2`, `handoff.md.j2`, `lane-plan.md.j2` |
| Jinja constructs used | `{% for %}` ×12, `{% if %}` ×4, `\| tojson` ×3 — **and nothing else** |
| NOT used | `{% include %}`, `{% extends %}`, `{% macro %}`, `{% set %}`, whitespace-control markers (`{%-`/`-%}`), `loop.*`, every other filter |
| Custom filters | **exactly one** — `render.py:160` sets `env.filters["tojson"] = _sorted_tojson` |
| Environment | `StrictUndefined`, `trim_blocks=True`, `lstrip_blocks=True`, `keep_trailing_newline=True`, `autoescape=False` (`render.py:152-158`) |

### W2-S1 — minijinja environment parity

- **step_id:** `W2-S1` · **predecessors:** `W1-GATE` · **estimated_loc:** 190
- **file_scope.exclusive:** `crates/render/src/env.rs`, `crates/render/src/filters.rs`
- **file_scope.may_read:** `services/cli/shepherd_cli/render.py`,
  `services/cli/shepherd_cli/templates/*.j2`, `conformance/cases/render/**`
- **file_scope.must_not_touch:** `crates/core/**`, `crates/registry/**`, `crates/cli/**`
- **interfaces — Consumes:** `conformance/run.sh --impl=rust --suite=render` (W0-S9).
  **Produces:** `pub fn render::env::build() -> minijinja::Environment<'static>`,
  `pub fn render::filters::sorted_tojson(Value) -> Result<String>`.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Python's environment is configured at `render.py:152-159`.
**The byte-parity killer is `render.py:129-138` + `:160`, and it diverges in TWO
independent ways — D2 rates it HIGH:**

`_sorted_tojson` is `json.dumps(sort_keys=True, separators=(", ", ": "), ensure_ascii=False)`
— plain JSON, key-sorted, **no escaping**. minijinja's builtin `tojson`
(`filters.rs:1205-1219`):

1. **unconditionally HTML-escapes** `<` `>` `&` `'` to `<` `>` `&` `'`, and
2. **does not sort map keys.**

Either alone breaks `output_sha256`. **Live blast radius today:** `boot-prompt.md.j2`
(`peer_teammate_names | tojson`) and `seed.md.j2` (`sprint_dependencies | tojson`,
`parallel_with | tojson`) — any branch name, path or URL containing `&` or `'` renders
different bytes. **Reusing the builtin fails the gate; the filter must be hand-written.**
**[DO-NOT-DUPLICATE]** `rg -n 'sorted_tojson|tojson' crates/render/` (expected 0 before
this step). Do not add a second JSON serializer — `crates/core` already owns canonical
sorted JSON via `RunState::to_canonical_json` (W1-S1); reuse it.
**[USER-STYLE]** `thiserror` in the library. No hollow wrapper around
`minijinja::Environment` — return it directly.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not implement the manifest or digests (W2-S2). Do not add template
features the 5 real templates do not use.
**[ACCEPTANCE]**
```bash
cargo test -p shepherd-render env::tests::matches_python_settings
# sorted tojson is byte-identical to python's _sorted_tojson on a multi-key dict
cargo test -p shepherd-render filters::tests::sorted_tojson_key_order
conformance/run.sh --impl=rust --suite=render
```

**minijinja API — already confirmed against docs.rs (Context7), so the coder does not
re-derive it:**

| Python (Jinja2) | minijinja equivalent | Status |
|---|---|---|
| `StrictUndefined` | `UndefinedBehavior::Strict` — enum is `{Lenient, Chainable, SemiStrict, Strict}`, `#[non_exhaustive]` | CONFIRMED, MATCH |
| `trim_blocks` / `lstrip_blocks` / `keep_trailing_newline` | all three default **`false` in BOTH engines**; this repo sets all three `true` at `render.py:152-159` | CONFIRMED, MATCH — but see the trap |
| `{# … #}` comment tags | funnel through the **same whitespace path** as block tags (verified in minijinja `lexer.rs`) | MATCH — and load-bearing: **all 5 templates open with a header comment** |
| `env.filters["tojson"] = _sorted_tojson` | `env.add_filter("tojson", …)` overrides the builtin — but the builtin is **not** a drop-in (see above) | **DIVERGE — must hand-write** |
| `autoescape=False` | must be set explicitly | — |

Everything except `tojson` is MATCH, which is good news for decision 7. **Residual MEDIUM
(D2):** these are four separate setter calls and omitting any one shifts bytes with **no
compile-time signal** — hence the env-construction assertion in the acceptance below.

**D2 marked three items UNVERIFIED — do not let a coder assume them:** whether minijinja's
in-memory `template_from_str` path is byte-identical to the loader path (`handoff.md.j2`
uses `from_string()`, the other four use the loader); the `{% else %}` whitespace boundary
in `lane-plan.md.j2`; and whether biome's glibc package carries `libc:["glibc"]` or omits
it (W4-S1's concern, not this step's).

> **TRAP, and it produces wrong bytes silently.** minijinja's docs state these settings
> **"apply to templates at the time they are loaded into the environment."** Configuring
> the environment *after* loading a template leaves that template rendering with the
> defaults, and minijinja's defaults for `trim_blocks`/`lstrip_blocks` are **off** — which
> is what Jinja2 defaults to as well, but the Python renderer explicitly turns all three
> **on**. Set every flag before the first `add_template`, or the digests diverge with no
> error anywhere.

**Actions**

1. Build the environment and set all five settings **before loading any template** (see
   the trap above), including `autoescape=false` — these are Markdown templates and
   escaping would corrupt every one.
2. Set `UndefinedBehavior::Strict` and preserve Python's exit 4 on a missing variable.
3. Register `sorted_tojson` via `add_filter("tojson", …)`, delegating to `crates/core`'s
   canonical sorted-JSON writer so there is exactly one sort implementation in the
   workspace.
4. Add a negative-control test: render a multi-key object through `tojson` with the
   override *removed* and assert the output differs from the corpus. A parity test that
   cannot fail is not a parity test — this is the same discipline
   `scripts/check-plugin.py --self-test` applies to the layout gate.
5. Table-test each of the 5 templates end-to-end against the frozen corpus.

### W2-S2 — render manifest and reproducible digests

- **step_id:** `W2-S2` · **predecessors:** `W2-S1` · **estimated_loc:** 160
- **file_scope.exclusive:** `crates/render/src/manifest.rs`
- **file_scope.may_read:** `services/cli/shepherd_cli/render.py`, `crates/render/src/env.rs`
- **file_scope.must_not_touch:** `crates/core/**`, `crates/registry/**`
- **interfaces — Consumes:** `render::env::build()` (W2-S1). **Produces:**
  `pub struct RenderManifest { template_sha256, vars_sha256, output_sha256 }` and
  `pub fn render_with_manifest(&Path, &Value) -> Result<(String, RenderManifest)>`.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Mesh row 9 requires `template_sha256`, `vars_sha256` and
`output_sha256` to reproduce byte-identically. `vars_sha256` is a digest **of the
canonicalized variables**, so it depends on W2-S1's sorted serialization — an unsorted
input digest is unstable across runs even when output is identical.
**[DO-NOT-DUPLICATE]** `rg -n 'sha256' crates/` — `sha2` is the sanctioned crate
(decision 7); do not add another hasher.
**[USER-STYLE]** `StrictUndefined` means a missing variable is a hard error at exit 4 —
preserve that exit code, do not soften it to a warning.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not change what is hashed. Do not add a caching layer.
**[ACCEPTANCE]**
```bash
cargo test -p shepherd-render manifest::tests::digests_reproduce
# same template + same vars => byte-identical output and identical digests, twice
conformance/run.sh --impl=rust --suite=render --assert-reproducible
```

**Actions**

1. Implement the three digests over template bytes, canonicalized vars, and output bytes.
2. Assert reproducibility by rendering twice in one test and comparing all three.
3. Preserve exit 4 on undefined variables.

### W2-S3..S16 — the Typer-native verb surface (14 modules of 43)

> **Counts corrected by A2 (AST-walked against `app.py:59-113` `LAZY_GROUPS`/
> `LAZY_COMMANDS`), superseding my own grep.** The surface is **101 leaf verbs strict /
> 111 counting bare-invocation usage shims, across 43 groups** — the mesh's "~147 ±10" is
> overstated by 30–46. Of the 43 groups, **29 are hand-parsed** (Wave 3) and **14 are
> Typer-native** (this wave). My earlier figures of 107 verbs and 21 hand-parsed modules
> were wrong; A2's method is stronger and I am adopting it.

- **step_ids:** `W2-S3` … `W2-S16` · **predecessors:** `W1-GATE` · **one step per source
  module**, decomposed at the doctrine floor (~80–100 LOC, ≤5 files, 2–5 min)
- **file_scope.exclusive:** `crates/cli/src/cmd/<module>.rs` — one file per step, mutually
  disjoint, so the batch fans out cleanly
- **file_scope.may_read:** `services/cli/shepherd_cli/commands/<module>.py`,
  `conformance/cases/<module>/**`
- **file_scope.must_not_touch:** every sibling's `<module>.rs`, `crates/core/**`,
  `crates/registry/**`
- **interfaces — Consumes:** `shepherd::registry` and `shepherd::core` through the
  umbrella (decision 9 — `crates/cli` never names a member crate directly).
  **Produces:** one `clap` subcommand tree per module.

**Measured scope:** **14 Typer-native groups of 43**, carrying the balance of the
**101 leaf verbs** (strict; 111 counting bare-invocation usage shims). The hand-parsed 29
hold **72.8% of command-registration LOC**, so this wave is the smaller share of the verb
surface despite covering a comparable verb count. Densest Typer-native groups: `run` (16
verbs), `mem` (8), `loop` (8), `report` (6), `panes` (6), `lock` (6), `adapt` (6),
`seed` (5).

> Superseded figures, struck: an earlier draft said "107 leaf verbs across 23 modules,
> 27,542 LOC," derived from my own `@app.command(` grep. A2's AST walk of
> `app.py:59-113` is authoritative and the numbers above replace them. Recorded rather
> than silently overwritten because critic pass 2 found the stale paragraph surviving
> twenty lines below its own correction box — exactly the drift this note prevents.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** These modules use Typer's normal decorator registration, so their
argument grammar maps onto `clap` derive mechanically. **Read correction C10 before
touching schema access:** the compatibility surface is tiered, not binary. The 7 objects
the runtime guards read are the hottest contract, but 42 objects are referenced across
shell (including the bash tests W4-S2 migrates) and all 59 schema objects are reproduced
by W1-S2. "Not in the 7" does **not** mean "free to restructure."
**[DO-NOT-DUPLICATE]** Per step: `rg -n 'fn <verb>' crates/cli/src/cmd/` before writing.
The umbrella rule is a dedup rule too — `rg -n 'shepherd-core|shepherd-registry|shepherd-render' crates/cli/Cargo.toml`
MUST return 0 (decision 9).
**[USER-STYLE]** `anyhow` is permitted here (binary), `thiserror` below it. Named-file
module pattern: `cmd.rs` + `cmd/` directory.
**[FILE-SCOPE]** one module per step.
**[NON-GOALS]** Do not port a callback module here — those are Wave 3 and have different
parity requirements. Do not change any verb's output.
**[ACCEPTANCE]** per step:
```bash
conformance/run.sh --impl=rust --suite=<module>     # byte-clean, zero skips
cargo check -p shepherd-cli
rg -c 'shepherd-core|shepherd-registry|shepherd-render' crates/cli/Cargo.toml; test $? -eq 1
```

---

## Wave 3 — the parity-hostile surface (29 of 43 groups)

**Wave gate (`W3-GATE`):** `conformance/run.sh --impl=rust` green on **every** case with
**zero skips** — the seed's acceptance for #239.

**Why this is a separate wave.** These groups do not register leaf verbs normally. They
use `@app.callback(invoke_without_command=True)` with
`context_settings={"allow_extra_args": True, "ignore_unknown_options": True}`, a single
catch-all `raw: list[str]`, and `help_option_names=[]` so they can emit byte-exact bash
`-h` heredocs. Neither `clap` nor `commander` wants to be told to print an exact string.
They carry **72.8% of command-registration LOC while being 67.4% of groups** — they are
disproportionately expensive per group, which is what makes this a wave rather than a
tail. `query.py` additionally carries order-sensitive substitution semantics needing real
unit tests, not a usage-text diff.

> **Two modules in this bucket are NOT independent porting units — the critic caught this
> and it would have mis-briefed a coder.** `render.py` and `models_graph.py` both register
> zero Typer commands, so a mechanical bucketing (mine) swept them in here. But **`render.py`
> has no retired bash-layer predecessor**, so the wave's blanket acceptance — "byte-match
> exact usage text against the retired bash layer" — is a bar it *cannot satisfy*, because
> there is nothing to match against. Its real acceptance is W2-S1/S2's render parity.
> `models_graph.py` is not a standalone verb surface either and risks being double-planned
> here and in W0-S4. **Both are excluded from the W3 step range**; W3 covers 27 groups, and
> `render`/`models_graph` are named exceptions with their acceptance pointing elsewhere.

**Two corrections, one to the mesh and one to my own earlier draft:**
- The mesh calls the mechanism "hand-parsing `sys.argv`". **`grep -c 'sys.argv'` is zero
  repo-wide.** Anyone porting off that literal description hunts the wrong Python API. The
  real mechanism is the Typer escape-hatch trio above.
- **The mesh's count of 29 is exactly right; my earlier figure of 21 was wrong.** I counted
  modules with no `@app.command(` decorator; A2 walked the actual registration tables. Its
  method is stronger.

### W3-S1..S29 — one step per hand-parsed group

- **step_ids:** `W3-S1` … `W3-S29` · **predecessors:** `W2-GATE`
- **file_scope.exclusive:** `crates/cli/src/cmd/<module>.rs` — mutually disjoint
- **file_scope.may_read:** `services/cli/shepherd_cli/commands/<module>.py`,
  `conformance/cases/<module>/**`
- **file_scope.must_not_touch:** siblings, `crates/core/**`, `crates/registry/**`
- **interfaces — Consumes:** the umbrella. **Produces:** a `clap` command per module whose
  stdout and exit code are byte-identical to Python's.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Each module's exact usage string and exit-code table are frozen in
the conformance corpus by W0-S9 — that corpus, not the Python source, is the
specification a coder implements against. `doctor.py` is the largest at 1,748 lines and
already carries a correct exit-code contract (`:1704`, `:1745`); preserve it exactly
(DF-07 is refuted — do not "fix" it).
**[DO-NOT-DUPLICATE]** `rg -n 'fn usage|const USAGE' crates/cli/src/cmd/` — one usage
string per module, sourced from the corpus.
**[USER-STYLE]** Use `clap`'s `allow_external_subcommands` / `trailing_var_arg` where it
genuinely maps; hand-write the usage string where it does not. Do NOT bend the whole CLI
to force a match — a per-module override is cheaper and clearer than a global one.
**[FILE-SCOPE]** one module per step.
**[NON-GOALS]** Do not "improve" a usage string, an error message, or an exit code. Byte
parity is the deliverable; taste is out of scope until after the canon flip.
**[ACCEPTANCE]** per step:
```bash
conformance/run.sh --impl=rust --suite=<module>   # stdout + exit code byte-identical
```

### W3-S30 — port the workdir layout migrations (a class decision 6 does not cover)

- **step_id:** `W3-S30` · **predecessors:** `W2-GATE` · **estimated_loc:** 220
- **file_scope.exclusive:** `crates/cli/src/cmd/migrate_layout.rs`
- **file_scope.may_read:** `services/cli/shepherd_cli/commands/migrate.py`,
  `conformance/cases/migrate-layout/**`
- **file_scope.must_not_touch:** `crates/registry/**` (schema migrations live there),
  `skills/context/schema/**`
- **interfaces — Consumes:** the umbrella. **Produces:** `shepherd migrate --layout v2|v3|v4`.

**Why this exists as its own step.** `shepherd migrate --layout` performs **filesystem**
moves (`root.db` → `shepherd.db`, `plans/` → `docs/plans/`), not SQL. It is pure Python
with no `.sql` counterpart, so decision 6's "migration SQL is the portable artifact; only
the runner is rewritten" does not reach it. Without this step the layout migrations are
deleted along with `services/cli/` in W4-S2 and any user on an old workdir layout is
stranded with no upgrade path.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** A3 confirms decision 6 is correct about the 21 schema files and
silent about this class. The migration is idempotent and must stay so — users may run it
against an already-migrated tree.
**[DO-NOT-DUPLICATE]** `rg -n 'layout' crates/registry/src/` (expected 0) — layout
migration is a CLI concern, not a registry concern; do not fold it into the schema runner.
**[USER-STYLE]** `anyhow` at the binary boundary. Filesystem moves are atomic-rename where
possible.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not merge this into the schema migration runner. Do not change what the
layouts are.
**[ACCEPTANCE]**
```bash
conformance/run.sh --impl=rust --suite=migrate-layout
# idempotent: running twice is a no-op, not an error
./target/release/shepherd migrate --layout v4 && ./target/release/shepherd migrate --layout v4
test $? -eq 0
```

**Loop node.** Wave 3 runs as a `CODER-CONVERGENCE` Loop-Until-Done: `max_iterations: 5`,
`new_findings` predicate = *the conformance failing-case count decreased since the
previous iteration*. Declared here so the node is not `PLAN-MISSING-LOOP-CAP` at the gate.

---

## Wave 4 — distribution, retirement, and the three adapters

**Wave gate (`W4-GATE`):** clean install resolves exactly one binary on macOS arm64,
linux gnu, linux musl and windows, **and** `--no-optional` still resolves, **and**
`rg -n 'shepherd-venv-ensure|poetry' --glob '!CHANGELOG.md'` returns **0** hits, **and**
no `.py` remains under `services/cli`, **and** each adapter's emitted role set diffs clean
against `content/`.

Absorbs seed dev.4 (distribution + retirement) and dev.5 (content compiler + adapters).
These run in parallel: L4 owns retirement, L5 owns the compiler and adapters.

### W4-S1 — platform packages and one launcher for one implementation (#235)

- **step_id:** `W4-S1` · **predecessors:** `W3-GATE` · **estimated_loc:** 300
- **file_scope.exclusive:** `packages/` manifests, `bin/shepherd`, `scripts/install-shctx-launcher.sh`
- **file_scope.may_read:** `Cargo.toml`, `.github/workflows/release.yml`
- **file_scope.must_not_touch:** `crates/**`, `content/**`, `conformance/**`
- **interfaces — Consumes:** `packages/` skeleton (W0-S7). **Produces:** one launcher
  resolving one binary; consumed by all three adapters.

**[SKILLS]** `code-style`, `typescript`, `shell`
**[CONTEXT-INVENTORY]** **#235's resolver bug is already fixed** — shipped v6.4.3 in
`d887ad4`, `scripts/install-shctx-launcher.sh:142-175` scans `cache/*/shepherd/*`
publisher-agnostically and version-sorts (`sort -V` + a pure-bash `version_gt()`
fallback), with **19 regression tests** at `scripts/tests/test_shctx_launcher.sh` covering
the exact `fl03/6.3.3` vs `pzzld/6.3.9` case. **This step does NOT rewrite resolution.**
The open gap is that **nothing invokes that installer**: absent from `hooks/hooks.json`,
`plugin.json`, `session_open.sh`, and `README.md:274` still points at the legacy
`skills/context/scripts/` path. See §SEED DRIFT — mechanical (#235).

Distribution facts, corrected by D2 — **use these, not the seed's**:
- **Use `@biomejs/biome` as the musl precedent, NOT esbuild.** esbuild ships **no `-musl`
  variant and no `libc` field at all**, so it cannot demonstrate the case we need.
- npm's `libc` field landed in **npm 10.3.0** (npm/cli#6914) — the floor is `>=10.3.0`,
  not "npm 10.x".
- **npm/cli#8320 is CLOSED but self-resolved by the reporter, with no structural fix**, so
  the seed's "lockfile generated on glibc CI" mitigation is **still required**.
- esbuild's `--no-optional` fallback is a postinstall self-heal chain: `require.resolve()`
  → `installUsingNPM()` → `downloadDirectlyFromNPM()` → a **named throw**. Never a silent
  no-op — copy that shape.
- **UNVERIFIED (D2):** whether biome's glibc package carries `libc:["glibc"]` or omits it.
  Confirm before writing the glibc manifest.

**[DO-NOT-DUPLICATE]** `rg -n 'cache/\*/shepherd' scripts/ bin/` — the corrected resolver
already exists and is tested; **wire to it, never rewrite it.**
**[USER-STYLE]** Vanilla. No install-time build step — `source: github` installs must work
without one.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT rewrite launcher resolution — it is fixed and tested. Do not publish
to npm in this sprint. Do not remove `shctx` as a name until Q3 is answered by the operator.
**[ACCEPTANCE]**
```bash
node packages/scripts/install-probe.mjs --triple=darwin-arm64
node packages/scripts/install-probe.mjs --triple=linux-x64-gnu
node packages/scripts/install-probe.mjs --triple=linux-x64-musl
node packages/scripts/install-probe.mjs --triple=win32-x64
node packages/scripts/install-probe.mjs --no-optional   # must still resolve
command -v shepherd && shepherd --version | grep -qx '6.4.5'
```

**Actions**

1. **Auto-wire the existing installer** — this is #235's actual Ask. Register
   `scripts/install-shctx-launcher.sh` so it runs on install: a `SessionStart` entry in
   `hooks/hooks.json` (or the plugin's install path), and fix `README.md:274` to name the
   current path instead of the legacy `skills/context/scripts/` one.
2. Write the root package with `optionalDependencies` over four platform packages, each
   carrying `os`/`cpu` and `libc` for the musl/glibc split, with `engines.npm >= 10.3.0`.
3. Write the launcher fallback as a postinstall self-heal chain mirroring esbuild's:
   resolve → install-via-npm → direct download → **named throw**. Never a silent no-op.
4. Generate the lockfile on glibc CI; document the npm/cli#8320 mitigation inline, noting
   the issue is closed without a structural fix.
5. Add `install-probe.mjs` covering all four triples plus `--no-optional`.

### W4-S2 — retire Python and the bash verb layer (#266, #239)

- **step_id:** `W4-S2` · **predecessors:** `W3-GATE`, `W4-S1` · **estimated_loc:** −9,000 (net deletion)
- **file_scope.exclusive:** `services/cli/`, `bin/shepherd-venv-ensure`,
  `hooks/scripts/session_venv.sh`, the 40 `cmd_*.sh`
- **file_scope.may_read:** `conformance/**`, `hooks/tests/**`
- **file_scope.must_not_touch:** `crates/**`, `content/**`, `packages/**`
- **interfaces — Consumes:** a green `conformance/run.sh --impl=rust` (W3-GATE). This step
  MUST NOT start before that gate — decision 5 forbids a canon flip before parity.
  **Produces:** the SUBTRACT delta that makes this sprint net-negative.

**[SKILLS]** `code-style`, `python`, `shell`
**[CONTEXT-INVENTORY]** Measured retirement baselines: **59** `shepherd-venv-ensure|poetry`
hits across **9** files; **123** `.py` files under `services/cli` (excluding `.venv` and
`__pycache__`); **40** `cmd_*.sh` totalling **8,310** lines; **53** tests under
`skills/context/tests/` and **99** `test_*.sh` repo-wide.
**[DO-NOT-DUPLICATE]** The 50 bash test assertions are **migrated, not dropped** (seed
spec). `rg -c 'assert' skills/context/tests/*.sh` gives the pre-migration count; the
post-migration Rust test count must be ≥ it.
**[USER-STYLE]** Delete, do not comment out. `git log` is the archive.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT delete anything while any conformance case is failing or skipped.
Do NOT drop a test assertion to make a count pass.
**[ACCEPTANCE]**
```bash
conformance/run.sh --impl=rust; test $? -eq 0          # precondition, re-asserted
rg -n 'shepherd-venv-ensure|poetry' --glob '!CHANGELOG.md' . ; test $? -eq 1   # 0 hits
find services/cli -name '*.py' -not -path '*/.venv/*' | wc -l | grep -qx '0'
find . -name 'cmd_*.sh' -not -path './target/*' | wc -l | grep -qx '0'
bin/shepherd lint; test $? -eq 0
```

**Actions**

1. Re-assert the parity gate is green with zero skips before deleting anything.
2. Migrate the bash test assertions into Rust tests; verify the count did not shrink.
3. Delete `services/cli/`, the 40 `cmd_*.sh`, `bin/shepherd-venv-ensure`, and
   `hooks/scripts/session_venv.sh`.
4. Remove the venv/poetry references from the remaining 9 files.

### W4-S3 — the `content/` compiler

- **step_id:** `W4-S3` · **predecessors:** `W1-GATE` · **estimated_loc:** 420
- **file_scope.exclusive:** `packages/compiler/`
- **file_scope.may_read:** `content/**`, `.shepherd/runs/v645/reports/discovery-d1-harness.md`
- **file_scope.must_not_touch:** `content/**` (source of truth — read only), `crates/**`
- **interfaces — Consumes:** `content/roles/*.md` with `write_eligible` (W0-S8).
  **Produces:** `compile(target: 'claude'|'codex'|'pi') -> EmittedTree`, consumed by
  W4-S4/S5/S6.

**[SKILLS]** `code-style`, `typescript`
**[CONTEXT-INVENTORY]** Emission targets differ structurally and this is measured, not
assumed (`discovery-d1-harness.md`): Claude reads `agents/`, `commands/`, `skills/`,
`hooks/`; Codex reads **only** `skills/` + `hooks/` + `shepherd.codex.toml` and has **no
command surface at all**; Pi reads `prompts/`, `skills/`, and TS `extensions/`.
**[DO-NOT-DUPLICATE]** `rg -n 'minijinja|jinja' packages/` (expected 0) — the compiler is
a plain emitter, not a second template engine. `crates/render` owns templating.
**[USER-STYLE]** One concept per file. Emission is a pure function of `content/`.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do NOT emit a Codex command target — Codex has nowhere to put one, so
emitting it is a defect rather than a gap. Do NOT invent capabilities a harness lacks.
**[ACCEPTANCE]**
```bash
node packages/compiler/bin/compile.mjs --target=claude --check   # idempotent, diffs clean
node packages/compiler/bin/compile.mjs --target=codex  --check
node packages/compiler/bin/compile.mjs --target=pi     --check
# Codex must NOT receive a command surface
node packages/compiler/bin/compile.mjs --target=codex --list | grep -qv '^commands/'
# a non-write-eligible role must never compile to a Codex worker
node packages/compiler/test/write-eligibility.test.mjs
```

**Actions**

1. Parse `content/roles/*.md`, `content/skills/`, `content/predicates/`.
2. Emit per target, mapping the abstract capability vocabulary onto each harness's
   concrete mechanism: Claude `tools:` frontmatter, Codex `[agent_types]`
   explorer/worker, Pi `--tools` (a **replacing** allowlist, so the full desired set must
   be enumerated per role, never "built-ins minus a few").
3. Enforce `write_eligible: false` → Codex `explorer`. A read-only role emitted as a
   `worker` is the defect this field exists to prevent.
4. Make `--check` idempotent so drift between `content/` and the committed emission is a
   gate failure.

### W4-S4/S5/S6 — the three adapters

- **step_ids:** `W4-S4` (claude), `W4-S5` (codex), `W4-S6` (pi)
- **predecessors:** `W4-S3` · **estimated_loc:** 240 / 260 / 380
- **file_scope.exclusive:** `packages/harness-claude/` · `packages/harness-codex/` ·
  `packages/harness-pi/` — mutually disjoint, so all three fan out together
- **file_scope.may_read:** `packages/compiler/`, `content/**`
- **file_scope.must_not_touch:** each other, `crates/**`, `content/**`
- **interfaces — Consumes:** `compile(target)` from W4-S3. **Produces:** three adapters
  over one core.

**[SKILLS]** `code-style`, `typescript`
**[CONTEXT-INVENTORY]** Per-harness constraints, all probe-confirmed:
- **Claude** — `agents/*.md` + `commands/*.md` + `skills/*/SKILL.md` + `hooks/hooks.json`;
  `model:` is a closed enum `sonnet|opus|haiku|fable`.
- **Codex** — `skills/` + `hooks/hooks.json` (same relative path shepherd already uses)
  + `shepherd.codex.toml`; roles are a TOML `[agent_types]` table mapping to exactly two
  primitives; `max_concurrent_children = 3`; models carry `reasoning_effort`.
- **Pi** — extensions load via jiti as a default-exported
  `(pi: ExtensionAPI) => void | Promise<void>`; guards are `pi.on("tool_call", …)`
  returning `{block, reason, terminate}` with `input` mutable in place; `setModel()` is
  session-global so per-role pinning means one subprocess per role; **no native team
  primitive exists**.
**[DO-NOT-DUPLICATE]** `rg -n "on\\('tool_call'" packages/` — exactly one guard
interpreter per harness; the predicate spec is shared data (decision 2), so a predicate
expressed as code twice is a defect.
**[USER-STYLE]** Adapters are thin. Logic that is identical across two adapters belongs in
the core or the compiler.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** No napi-rs, no `.node` addon (decision 1). Do not add a Pi team primitive
by depending on the unvetted third-party `@tintinweb/pi-subagents`; declare the capability
absent instead.
**[ACCEPTANCE]**
```bash
# every guard predicate has an allow AND a deny case, in every adapter
node packages/scripts/predicate-coverage.mjs --require-allow-and-deny
# emitted role sets diff clean against content/
node packages/compiler/bin/compile.mjs --target=claude --check
node packages/compiler/bin/compile.mjs --target=codex  --check
node packages/compiler/bin/compile.mjs --target=pi     --check
# Codex concurrency ceiling is declared, not discovered at runtime
grep -q 'max_concurrent_children = 3' packages/harness-codex/shepherd.codex.toml
```

**Actions (per adapter)**

1. Emit the harness's tree from the compiler; assert `--check` is clean.
2. Wire the guard layer: Claude and Codex read the shared predicate spec from the Rust
   engine; Pi interprets the same spec in TypeScript (decision 1 — Pi's is the only
   second interpreter, and it is kept in lockstep by the shared allow/deny case corpus,
   not by discipline).
3. Declare each harness's real ceilings in config rather than discovering them at
   runtime: Codex's 3-descendant cap, Pi's absent team primitive, Pi's session-global
   model.
4. **W4-S4 only — release-gate criterion C.4.** Assert cross-implementation run-state
   interop: a `run.json` written by the Rust binary is read and advanced by the Claude
   adapter with no migration step.
   ```bash
   ./target/release/shepherd run init c4probe && \
     node packages/harness-claude/test/advance-run.mjs c4probe && \
     ./target/release/shepherd run show c4probe | grep -q '"status"'
   ```

### W4-S7 — release-gate closeout (criteria C.6, C.7)

- **step_id:** `W4-S7` · **predecessors:** `W4-S1`, `W4-S2`, `W4-S3` · **estimated_loc:** 120
- **file_scope.exclusive:** `CHANGELOG.md`, `README.md`, `.claude-plugin/plugin.json`
- **file_scope.may_read:** `Cargo.toml`, `.github/workflows/release.yml`,
  `hooks/tests/test_changelog_current.sh`
- **file_scope.must_not_touch:** `crates/**`, `packages/**`, `content/**`, `conformance/**`
- **interfaces — Consumes:** the acceptance output of every prior deliverable step.
  **Produces:** a green `test_changelog_current.sh` and version agreement across all
  three manifests.

**[SKILLS]** `code-style`, `markdown`
**[CONTEXT-INVENTORY]** **Measured red at plan time:**
`bash hooks/tests/test_changelog_current.sh` exits **1**, and `CHANGELOG.md` contains
**zero** `## v6.4.5` sections. The mesh separately records that README claims 6.4.4 while
`plugin.json` already reads 6.4.5. `release.yml:219` bumps `skills/*/SKILL.md` versions as
part of the release commit and is `[ -f ]`-guarded — it silently skipped for the whole
period the component dirs were moved, so verify it actually fires.
**[DO-NOT-DUPLICATE]** `rg -n '^## v6\.4\.5' CHANGELOG.md` (expected 0 before, 1 after).
Do not hand-bump `skills/*/SKILL.md` — `release.yml` owns that.
**[USER-STYLE]** No em dashes, no AI vocabulary in release notes.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do not tag or publish a release — `[release].driver = "operator"`.
**[ACCEPTANCE]**
```bash
bash hooks/tests/test_changelog_current.sh          # must exit 0
rg -c '^## v6\.4\.5' CHANGELOG.md | grep -qx 1
# all three version sources agree
test "$(jq -r .version .claude-plugin/plugin.json)" = "$(grep -m1 '^version' Cargo.toml | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
rg -q '6\.4\.5' README.md
# C.6 — every deliverable issue closed with its acceptance output pasted in
for n in 280 281 282 283 239 235 266 279; do
  gh issue view "$n" --json state,comments \
    | jq -e '.state=="CLOSED" and ([.comments[].body] | join("") | test("\\$ |```"))' >/dev/null \
    || { echo "issue #$n not closed with acceptance evidence"; exit 1; }
done
```

**Actions**

1. Write the `## v6.4.5` CHANGELOG entry covering every landed deliverable.
2. Reconcile README and `plugin.json` to the Cargo workspace version.
3. Confirm `release.yml`'s `[ -f ]`-guarded SKILL.md bump actually fires on this tree.
4. Close each of the 8 deliverable issues with its acceptance command output pasted in
   (criterion C.6). MCP is unavailable, so `gh` is the sanctioned write path — emit
   `[WARN] MCP github unavailable — using gh`.

---

## Stage Graph

```yaml
nodes:
  - id: INTRO-COMBO-WAVE
    type: parallel-batch
    agents: [discovery x2, auditor x3]
    in_predicates: []
    parallel_with: []
    out_edges: [{to: MESH, label: on-intro-wave-complete}]
    status: done
    note: "5 lanes, parallel_max=5 per config; fanout in-context (Workflow absent)"

  - id: MESH
    type: single-agent
    agents: [engineer]
    in_predicates: [{from: INTRO-COMBO-WAVE, label: on-intro-wave-complete}]
    out_edges: [{to: PLAN-GATE, label: unconditional}]
    status: done

  # Pass 1 returned RECONSIDER; the engineer revised; pass 2 gated the revision. Both are
  # HISTORY by the time root walks this graph, so they are marked done rather than left as
  # live re-entrant nodes -- cmd_graph.sh:281 requires ALL in_predicates satisfied by an
  # exact predecessor+edge match and has no done-to-ready reset, so a live loop-back here
  # would strand the walk exactly as critic pass 2 found at PLAN-GATE-POST-Q1.
  - id: PLAN-GATE
    type: single-agent
    agents: [critic]
    in_predicates: [{from: MESH, label: unconditional}]
    out_edges:
      - {to: DEDUP-GATE-W0, label: on-green}
      - {to: HARD-STOP, label: on-red}
    status: done
    note: "pass 1 RECONSIDER (10 findings) -> revised -> pass 2; see §Critic pass 1"

  # Predicates on DEDUP-GATE-W0, matching its parallel_with sibling WAVE-0-IMPL. Predicating
  # on PLAN-GATE instead left it unbacked: cmd_graph.sh satisfies a predicate only on an
  # exact predecessor+edge match, and PLAN-GATE's on-green fires at DEDUP-GATE-W0.
  - id: CANONICAL-TYPES-REFRESH
    type: parallel-batch
    agents: [worker]
    in_predicates: [{from: DEDUP-GATE-W0, label: on-dedup-clear}]
    parallel_with: [WAVE-0-IMPL]
    out_edges: [{to: W0-GATE, label: unconditional}]

  - id: DEDUP-GATE-W0
    type: conductor-inline
    in_predicates: [{from: PLAN-GATE, label: on-green}]
    out_edges:
      - {to: WAVE-0-IMPL, label: on-dedup-clear}
      - {to: HARD-STOP, label: on-dedup-block}

  - id: WAVE-0-IMPL
    type: parallel-batch
    agents: [coder x13]
    in_predicates: [{from: DEDUP-GATE-W0, label: on-dedup-clear}]
    parallel_with: [CANONICAL-TYPES-REFRESH]
    out_edges: [{to: WAVE-0-AUDIT, label: on-coder-complete}]
    note: "S1-S13. W0-S5 has predecessor W0-S2 (both own commands/spawn.md) - not co-batched"

  - id: WAVE-0-AUDIT
    type: parallel-batch
    agents: [auditor]
    in_predicates: [{from: WAVE-0-IMPL, label: on-coder-complete}]
    parallel_with: [WAVE-1-IMPL]
    max_iterations: 3
    redo_loop: "owns the REDO loop inline (flock.md §@auditor, pipeline.md §Wave review + REDO); emits on-pass only after REDO converges, else on-hard-stop"
    out_edges:
      - {to: W0-GATE, label: on-pass}
      - {to: HARD-STOP, label: on-hard-stop}

  - id: W0-GATE
    type: wave-gate
    in_predicates:
      - {from: WAVE-0-AUDIT, label: on-pass}
      - {from: CANONICAL-TYPES-REFRESH, label: unconditional}
    out_edges: [{to: WAVE-1-IMPL, label: on-green}, {to: HARD-STOP, label: on-hard-stop}]

  - id: WORKER-IO
    type: parallel-batch
    agents: [worker]
    in_predicates: [{from: W0-GATE, label: on-green}]
    parallel_with: [WAVE-1-IMPL]
    out_edges: [{to: W1-GATE, label: unconditional}]

  - id: WAVE-1-IMPL
    type: parallel-batch
    agents: [coder x2]
    in_predicates: [{from: W0-GATE, label: on-green}]
    parallel_with: [WAVE-0-AUDIT, WORKER-IO]
    out_edges: [{to: WAVE-1-AUDIT, label: on-coder-complete}]

  - id: WAVE-1-AUDIT
    type: parallel-batch
    agents: [auditor]
    in_predicates: [{from: WAVE-1-IMPL, label: on-coder-complete}]
    parallel_with: [WAVE-2-IMPL]
    max_iterations: 3
    redo_loop: "owns the REDO loop inline (flock.md §@auditor, pipeline.md §Wave review + REDO); emits on-pass only after REDO converges, else on-hard-stop"
    out_edges: [{to: W1-GATE, label: on-pass}, {to: HARD-STOP, label: on-hard-stop}]

  - id: W1-GATE
    type: wave-gate
    in_predicates:
      - {from: WAVE-1-AUDIT, label: on-pass}
      - {from: WORKER-IO, label: unconditional}
    out_edges:
      - {to: OPERATOR-GATE-Q1, label: on-green}
      - {to: HARD-STOP, label: on-hard-stop}

  # Fixes critic HIGH finding (stage-graph): the prose recommended stopping here for an
  # operator decision, but the graph routed straight through. A conductor walks the graph,
  # not the prose, so without this node the Q1 recommendation was unenforceable and the
  # arc would silently overrun the quota -- a directive-3 violation.
  - id: OPERATOR-GATE-Q1
    type: pause
    in_predicates: [{from: W1-GATE, label: on-green}]
    operator_question: "Q1: Option A (ship the harness layer, defer the engine port) or Option B (continue the verb port)?"
    out_edges:
      - {to: PLAN-REVISION-POST-Q1, label: on-amend}
      - {to: HARD-STOP, label: on-hard-stop}

  # Fixes critic HIGH finding (decomposition). BOTH operator answers route through this ONE
  # node -- no OR-join, because in_predicates are AND-joins and two mutually-exclusive
  # predecessors would deadlock a reconvergence node forever. The engineer takes the
  # operator's Q1 answer and emits the remainder graph for whichever option was chosen:
  #   Option A -> harness layer only (W4-S1/S3/S4/S5/S6/S7; W4-S2 cannot run, decision 5)
  #   Option B -> W2/W3 decomposed to the 80-100 LOC floor, then full W4
  # Either way Waves 2/3 are NEVER dispatched from THIS plan at module granularity.
  - id: PLAN-REVISION-POST-Q1
    type: single-agent
    agents: [engineer]
    in_predicates: [{from: OPERATOR-GATE-Q1, label: on-amend}]
    out_edges: [{to: PLAN-GATE-POST-Q1, label: on-amend}]

  # on-yellow routes to HARD-STOP, NOT back to PLAN-REVISION-POST-Q1. Critic pass 2 caught
  # that loop-back as a deadlock: a downstream in_predicate is satisfied only on an exact
  # predecessor+edge match, PLAN-REVISION-POST-Q1 declares no such entry, and it is
  # type single-agent so there is no done-to-ready reset in the state machine either.
  # This mirrors the original PLAN-GATE/PLAN-REVISION pair, which likewise has no
  # loop-back, and matches the doctrine: revise ONCE, then pass-2 GREEN -> READY, else
  # ESCALATED (== HARD-STOP terminal, same treatment as on-red).
  - id: PLAN-GATE-POST-Q1
    type: single-agent
    agents: [critic]
    in_predicates: [{from: PLAN-REVISION-POST-Q1, label: on-amend}]
    out_edges:
      - {to: WAVE-2-IMPL, label: on-green}
      - {to: HARD-STOP, label: on-yellow}
      - {to: HARD-STOP, label: on-red}

  # Placeholder for whichever wave the amended plan emits. Under Option A the amended graph
  # replaces this node with the harness batch; under Option B with the decomposed verb port.
  - id: WAVE-2-IMPL
    type: parallel-batch
    agents: [coder]
    in_predicates: [{from: PLAN-GATE-POST-Q1, label: on-green}]
    parallel_with: [WAVE-1-AUDIT]
    out_edges: [{to: WAVE-2-AUDIT, label: on-coder-complete}]

  - id: WAVE-2-AUDIT
    type: parallel-batch
    agents: [auditor]
    in_predicates: [{from: WAVE-2-IMPL, label: on-coder-complete}]
    parallel_with: [WAVE-3-IMPL]
    max_iterations: 3
    redo_loop: "owns the REDO loop inline (flock.md §@auditor, pipeline.md §Wave review + REDO); emits on-pass only after REDO converges, else on-hard-stop"
    out_edges: [{to: W2-GATE, label: on-pass}, {to: HARD-STOP, label: on-hard-stop}]

  - id: W2-GATE
    type: wave-gate
    in_predicates: [{from: WAVE-2-AUDIT, label: on-pass}]
    out_edges: [{to: WAVE-3-IMPL, label: on-green}, {to: HARD-STOP, label: on-hard-stop}]

  - id: CODER-CONVERGENCE
    type: loop
    agents: [coder]
    in_predicates: [{from: W2-GATE, label: on-green}]
    parallel_with: [WAVE-3-IMPL]
    max_iterations: 5
    new_findings_predicate: "conformance failing-case count decreased since previous iteration"
    out_edges:
      - {to: WAVE-3-AUDIT, label: on-coder-complete}
      - {to: HARD-STOP, label: on-budget-exceeded}

  - id: WAVE-3-IMPL
    type: parallel-batch
    agents: [coder]
    in_predicates: [{from: W2-GATE, label: on-green}]
    parallel_with: [WAVE-2-AUDIT, CODER-CONVERGENCE]
    out_edges: [{to: WAVE-3-AUDIT, label: on-coder-complete}]

  - id: WAVE-3-AUDIT
    type: parallel-batch
    agents: [auditor]
    in_predicates:
      - {from: WAVE-3-IMPL, label: on-coder-complete}
      - {from: CODER-CONVERGENCE, label: on-coder-complete}
    parallel_with: [WAVE-4-IMPL]
    max_iterations: 3
    redo_loop: "owns the REDO loop inline (flock.md §@auditor, pipeline.md §Wave review + REDO); emits on-pass only after REDO converges, else on-hard-stop"
    out_edges: [{to: W3-GATE, label: on-pass}, {to: HARD-STOP, label: on-hard-stop}]

  - id: W3-GATE
    type: wave-gate
    in_predicates: [{from: WAVE-3-AUDIT, label: on-pass}]
    out_edges: [{to: WAVE-4-IMPL, label: on-green}, {to: HARD-STOP, label: on-hard-stop}]

  - id: WAVE-4-IMPL
    type: parallel-batch
    agents: [coder x7]
    in_predicates: [{from: W3-GATE, label: on-green}]
    parallel_with: [WAVE-3-AUDIT]
    out_edges: [{to: WAVE-4-AUDIT, label: on-coder-complete}]

  - id: WAVE-4-AUDIT
    type: parallel-batch
    agents: [auditor]
    in_predicates: [{from: WAVE-4-IMPL, label: on-coder-complete}]
    max_iterations: 3
    redo_loop: "owns the REDO loop inline (flock.md §@auditor, pipeline.md §Wave review + REDO); emits on-pass only after REDO converges, else on-hard-stop"
    out_edges: [{to: W4-GATE, label: on-pass}, {to: HARD-STOP, label: on-hard-stop}]


  - id: W4-GATE
    type: wave-gate
    in_predicates: [{from: WAVE-4-AUDIT, label: on-pass}]
    out_edges: [{to: LANE-CLOSE, label: on-green}, {to: HARD-STOP, label: on-hard-stop}]

  - id: LANE-CLOSE
    type: conductor-inline
    in_predicates: [{from: W4-GATE, label: on-green}]
    out_edges: [{to: LANE-INTEGRATE, label: unconditional}]

  - id: LANE-INTEGRATE
    type: conductor-inline
    in_predicates: [{from: LANE-CLOSE, label: unconditional}]
    out_edges: [{to: CLOSE-SWARM, label: on-rebase-clean}, {to: HARD-STOP, label: on-hard-stop}]

  - id: CLOSE-SWARM
    type: parallel-batch
    agents: [auditor x5]
    in_predicates: [{from: LANE-INTEGRATE, label: on-rebase-clean}]
    concerns: [code-quality, data-flow, dependency-topology, datastore-state, completeness]
    max_iterations: 3
    redo_loop: "owns HOTFIX-CLOSE inline; a CRITICAL/HIGH loops here up to 3x before escalating"
    # The on-grade-cap edge is REQUIRED by pipeline.md (a CLOSE-SWARM without one is a
    # STAGE-GRAPH-VIOLATION). It is present. But CLOSE-FINALIZE deliberately keeps a
    # SINGLE in_predicate -- see grade_cap_note.
    out_edges:
      - {to: CLOSE-FINALIZE, label: on-no-finding}
      - {to: CLOSE-FINALIZE-CAPPED, label: on-grade-cap}
      - {to: HARD-STOP, label: on-hard-stop}
    grade_cap_note: |
      Finding 14 is real, but BOTH the prescribed patch and my first correction deadlock.
      Verified against cmd_graph.sh _cmd_mark directly: on a `done` mark it sets
      satisfied=True ONLY on predicates whose (predecessor, edge) matches the ONE fired
      exit_edge, then promotes a node to ready only when all(p.satisfied).
        - Prescribed patch (two predicates on CLOSE-FINALIZE, both from CLOSE-SWARM):
          one edge fires, the other predicate never satisfies, all() is False forever.
        - My first correction (keep the on-grade-cap out_edge, single predicate):
          firing on-grade-cap matches no predicate, so CLOSE-FINALIZE never becomes ready.
      Resolved with the doctrine's own rule -- "OR-joins are separate nodes"
      (pipeline.md §Stage Graph). on-no-finding and on-grade-cap route to two distinct
      single-predicate nodes that both terminate at PAUSE. This keeps the grade-cap edge
      the doctrine requires (its absence is a STAGE-GRAPH-VIOLATION), keeps every
      reconvergence single-predecessor, and deadlocks on neither path.

  - id: CLOSE-FINALIZE
    type: conductor-inline
    in_predicates: [{from: CLOSE-SWARM, label: on-no-finding}]
    out_edges: [{to: PAUSE, label: unconditional}]

  - id: HARD-STOP
    type: terminal
    in_predicates: []
    out_edges: []

  - id: PAUSE
    type: terminal
    in_predicates: [{from: CLOSE-FINALIZE, label: unconditional}]
    out_edges: []
```

---

## Lane projection

Five lanes, **total and constant across waves**. One per file-disjoint architectural
boundary — that is the justification, and it is the sprint's cost multiplier, so it is
deliberately the smallest number that keeps sibling scopes disjoint. Fewer would force
two lanes to share `crates/`; more would fragment without buying parallelism, since
cache-warm fan-out *within* a lane is already cheap.

| lane_id | member_steps | file_scope.exclusive | parallel_with |
|---|---|---|---|
| `L1-engine` | W1-S1, W2-*(core), W3-*(core) | `crates/core`, `crates/sdk`, root `Cargo.toml` | L2, L3, L4, L5 |
| `L2-registry` | W1-S2, W3-*(registry) | `crates/registry` | L1, L3, L4, L5 |
| `L3-surface` | W2-*(render), W3-*(cli) | `crates/cli`, `crates/render` | L1, L2, L4, L5 |
| `L4-conformance` | W0-S1, W0-S3, W0-S4, W0-S9, W0-S10, W4-S2, W4-S7 | `conformance/`, `scripts/`, `services/cli/`, `.shepherd/runs/*/run.json`, `CHANGELOG.md`, `README.md`, `.claude-plugin/plugin.json` | L1, L2, L3, L5 |
| `L5-harness` | W0-S2, W0-S5, W0-S6, W0-S7, W0-S8, W0-S11, W0-S12, W0-S13, W4-S1, W4-S3, W4-S4, W4-S5, W4-S6 | `packages/`, `content/`, `agents/`, `commands/`, `skills/`, `hooks/`, `bin/`, `.github/workflows/` | L1, L2, L3, L4 |

**Cargo concurrency cap: 2.** Only `L1-engine` and `L2-registry` may hold a
`CARGO_TARGET_DIR=target/.lanes/<lane-slug>` simultaneously. `L3-surface` builds only at
its wave gate, against the shared warm `target/`. `L4` and `L5` do not build Rust at all.
This honors operator directive 3's per-lane target dirs where they buy parallelism, while
avoiding five cold 2.5 GB trees on a disk that is 90% full.

**Lane scope is assigned by DIRECTORY, not by wave.** An earlier draft split Wave 0's
doctrine steps into L4 while leaving the emitted trees to L5, and justified the overlap as
"they never collide in time." That was wrong: `file_scope.exclusive` is a **static**
disjointness property that the DEDUP-GATE and the wave batcher check structurally — a
lane pair that is disjoint only because of sequencing is a latent write collision, not a
disjoint pair. Corrected above by cutting Wave 0 along directory lines instead:

- **L4** takes every Wave-0 step touching `scripts/`, `services/cli/` or the run dirs —
  W0-S1 (lint unblock), W0-S3 (`doctor.py`), W0-S4 (`models.py`), plus W0-S9
  (`conformance/`).
- **L5** takes every Wave-0 step touching the plugin component dirs — W0-S2 and W0-S5
  (`commands/spawn.md`, `skills/harness/SKILL.md`, `hooks/scripts/session_open.sh`),
  W0-S6 (`hooks/scripts/_lib.sh`, `skills/shepherd/SKILL.md`), plus W0-S7 and W0-S8.

**Emitted-tree ownership is now unconditional.** `agents/`, `commands/`, `skills/`,
`hooks/` and `bin/` belong to **L5 for the entire sprint** — in Wave 0 as hand-edited
doctrine, from W4-S3 as compiler output. No other lane writes them at any point, so the
ownership claim needs no temporal argument to hold.

**Intra-lane ordering.** W0-S2 and W0-S5 both write `commands/spawn.md`. Both now sit in
L5, so the collision is resolved by the declared `predecessors: [W0-S2]` on W0-S5 inside
one lane, rather than across two — which is where such a conflict is actually resolvable.

**Neither lane is markdown-only.** L4's Wave-0 load is `conformance/` (340 LOC) plus
`doctor.py`/`models.py`; L5's is `packages/` (200) plus `content/` (260). Both clear the
`[TIER-MISMATCH]` floor for a lane.

**Materialization warning for root — GH #269.** Root materializes this projection via
`shepherd render lane-plan.md.j2` → `{run_dir}/lanes/{lane}/plan.md`, but the brief is
rendered from `{run_dir}/lanes/{lane}/vars.json`. #269 records these as **two sources of
truth with no drift check, measured 5/5 lanes**: every correction made to the lane prose
silently fails to reach the artifact dispatch actually renders from. This plan does not
fix #269 (unseeded scope), so the mitigation is procedural and belongs to root: **edit
`vars.json`, then re-render — never hand-edit `lanes/{lane}/plan.md` and expect the change
to reach a coder.** Called out here because this is the exact file root touches during
BODY.

---

## Proof of dispatch

- **Fan-out vehicle:** in-context `Agent()`, whole file-disjoint batch in ONE message.
- **`fanout_downgrade_reason`:** `workflow-absent-from-tool-list`.
- **`WORKFLOW-VEHICLE-PROBE`:** run once, before first fan-out, by reading the visible
  tool list for the literal token `Workflow`. **Result: NEGATIVE.** `Workflow`, `Glob`
  and `Grep` are all absent despite `agents/engineer.md:7` granting them. Per
  `agents/engineer.md:67` this is the "genuinely absent" branch and in-context `Agent()`
  is the correct and only option — not a downgrade to apologize for. `ToolSearch` was
  **not** used to answer this (`WORKFLOW-SELFCHECK-TOOLSEARCH`).
- **Sub-flock:** 2 × `shepherd:discovery` + 3 × `shepherd:auditor`, every call pinning
  both `subagent_type: "shepherd:<role>"` and `model: "sonnet"`, every brief tagged
  `[INVOCATION-CONTEXT].dispatcher: engineer-self-contained`. No `@coder`/`@worker`/
  `@engineer` was dispatched.
- **Flat-roster correction:** the first batch passed `name:` and was refused
  ("Teammates cannot spawn other teammates"). Re-dispatched without `name:`. Recorded as
  DF-02's extension.
- **Notification routing:** all five completions routed to the task-tree owner, not to
  the dispatcher. **The engineer received none of its own five lane results as tool
  results.** Recovery, per lane:
  - **D1** — arrived via root relay, materialized to
    `.shepherd/runs/v645/reports/discovery-d1-harness.md`, residual closed by a direct
    engineer probe of the installed `codex-shepherd@1.0.2` bundle.
  - **A1, A3** — **superseded by direct engineer verification** rather than paying for a
    resume: A1's landed-state question was answered by the central build run
    (§Verified baseline) and A3's schema question by direct `sqlite3` derivation
    (corrections C1–C11).
  - **A2, D2** — `SendMessage` resume issued; both replied *"had no active task; resumed
    from transcript"*. Their re-emissions **also** routed to root (A2's own closing line:
    *"No SendMessage-class tool is present in this session's tool list, so I cannot route
    this directly to `shepherd-engineer-v645`"*), costing a further ~271k tokens for data
    root already held. **Root then materialized all five reports to disk**, which is the
    only working channel: `.shepherd/runs/v645/reports/{discovery-d1-harness,
    discovery-d2-distribution-template,audit-a1-rust-landed-state,
    audit-a2-verb-surface-sizing,audit-a3-registry-schema-ledger}.md`, committed at
    `aa19ffd` (force-added — `.gitignore:58` excludes `.shepherd/runs/**`, itself a
    reproduction of #277).
  - **Where my own derivations were superseded.** While the reports were unreachable I
    derived the surfaces myself. A2 and A3 proved more careful and **I adopted their
    numbers over mine**: verbs 101 not 107, hand-parsed groups 29 not 21, port size 16,684
    executable lines not 42,560 raw, tables 37 addressable not 45, indexes 34 named not
    68, and the guard surface 8 not 7. Each correction is recorded at its point of use
    rather than quietly swapped.
  - **Cost note:** ~660k subagent tokens were spent across five lanes and two resumes;
    the dispatcher received **none** of it as tool results. That is the concrete cost of
    #270 and the reason W0-S5 and W0-S12 treat it as sprint work rather than commentary.
- **Critic gate:** pass 1 → **RECONSIDER**, 10 findings, all dispositioned (see §Critic
  pass 1). Verdict recovered by reading `audit_findings` rows from the registry, since the
  critic's completion could not reach the dispatcher either. Pass 2 dispatched against the
  revised bytes with the same registry-write channel.
- **Central verification:** run once by the engineer, never fanned out
  (`SKILL.md §Fan-out counterweight` rule 2). Results in §Verified baseline.
- **MCP:** no GitHub MCP registered. `gh` 2.97.0 used as the sanctioned write fallback
  per `SKILL.md §MCP-over-CLI`. `[WARN] MCP github unavailable — using gh`.
- **Adaptation priors:** `shctx adapt priors` is empty in this checkout. No `prior:<id>`
  is cited because none exists; the absence is recorded rather than invented.

---

## Critic pass 1 — verdict RECONSIDER, all 10 findings dispositioned

Dispatched `shepherd:critic` (sonnet, `dispatcher: engineer-self-contained`). Its
completion never reached me — GH #270 — so I recovered the verdict by reading its
`audit_findings` rows **directly from the registry**, which is the durable-artifact
channel working exactly as designed. Deliverable row 1 is `delivered`.

Worth recording: the critic **refused** my request to re-emit in a compact 4-section
format, citing `agents/critic.md §Step 3` and the principle that a peer message cannot
authorize deviating from its own mandate, and it re-verified against the plan's revised
bytes rather than taking my word that a revision had happened. A gate that can be talked
into a shorter report by the party it is gating is not a gate. This one could not be.

| # | Concern | Sev | Disposition |
|---|---|---|---|
| 1 | decomposition | HIGH | **FIXED structurally.** Waves 2/3 removed from the dispatchable set; gated behind `OPERATOR-GATE-Q1 → PLAN-REVISION-POST-Q1 → PLAN-GATE-POST-Q1`. The critic was right that honest flagging ≠ a dispatchable plan |
| 2 | stage-graph | HIGH | **FIXED.** `OPERATOR-GATE-Q1` node added; `W1-GATE` no longer routes unconditionally into `WAVE-2-IMPL`. The Q1 stop-boundary is now enforceable by a conductor walking the graph |
| 3 | mesh-correction (`worktrees`) | MED | **FIXED.** Tier (a) corrected 7 → **8**. Root cause was my `FROM\|JOIN` grep missing `INSERT INTO`; methodology note added so a future re-derivation unions reads and writes |
| 4 | mesh-correction (`render.py`/`models_graph.py`) | MED | **FIXED.** Both excluded from the W3 range as named exceptions; W3 covers 27 groups. `render.py` cannot satisfy a bash-parity bar that has no bash predecessor |
| 5 | outcome-verification | MED | **FIXED.** Seeded §6 predicate `PRAGMA compile_options \| grep ENABLE_FTS5` restored to W1-S2, plus explicit existence assertions for all 8 tier-(a) objects |
| 6 | mesh-correction (table count) | LOW | **FIXED.** C2 now states the decomposition (45 rows = 35 base + 2 virtual + 8 shadow = 37 addressable) instead of a bare number |
| 7 | mesh-correction (`json_valid`) | LOW | **FIXED.** C5 now reads "19 tables carrying 24 CHECK constraints" so the oracle's counting query is unambiguous |
| 8 | necessity (`tracing-subscriber`) | LOW | **FIXED.** Named in Global Constraint 2 as a sanctioned 15th crate, architecturally required because the binary is the only place a subscriber may be installed |
| 9 | code-style-conflict (`resolver`) | LOW | **FIXED.** `resolver = "3"` recorded as an intentional pre-existing project-wins deviation, same treatment as `hashbrown`/`tokio` |
| 10 | dogfood-disposition (DF-07) | LOW | **FIXED.** Causal claim hedged; the refutation now rests on the measurement, not the pipeline-artifact story |

**Two findings I did not merely accept but verified independently before acting:** #3
(re-derived the guard surface as reads ∪ writes — the critic is right, it is 8) and #8
(`crates/cli/Cargo.toml:62` does carry `tracing-subscriber`). #9 I confirmed at
`Cargo.toml:11`.

## Critic pass 2 — 6 findings, and it caught a deadlock I introduced

Pass 2 confirmed both HIGH fixes were structural rather than narrated (finding 11: *"HIGH
finding 1 is genuinely fixed structurally, not just narrated"*), and then **found a
deadlock I created while fixing the other one.** That is the whole argument for running
pass 2 rather than declaring victory on my own revision.

| # | Concern | Sev | Disposition |
|---|---|---|---|
| 11 | verify-decomposition-fix | LOW | **Confirmed fixed.** `WAVE-2-IMPL.in_predicates` is `PLAN-GATE-POST-Q1` only; `W1-GATE` no longer targets it |
| 12 | post-Q1 deadlock | **HIGH** | **FIXED.** My `PLAN-GATE-POST-Q1 --on-yellow--> PLAN-REVISION-POST-Q1` loop-back could never fire: `cmd_graph.sh:281` needs an exact predecessor+edge match, no such `in_predicate` existed, and the target is `type: single-agent` with no done→ready reset. Now routes `on-yellow → HARD-STOP` (= ESCALATED), matching the original PLAN-GATE pair |
| 13 | Q6 oracle scope | **HIGH** | **FIXED, Option 1 adopted.** `--suite=guard-cli` added to W0-S9 as Action 6 plus an acceptance line, covering all five guard-driving CLI behaviors. Critic independently re-verified decision 3 is false and confirmed 3 of the 4 scripts touch the DB *exclusively* via the CLI. Marked MUST-FIX-BEFORE-DISPATCH on the first dispatchable wave |
| 14 | CLOSE-FINALIZE grade-cap | MED | **Finding ACCEPTED, prescribed patch DECLINED with reasoning.** Adding a second `in_predicate` from CLOSE-SWARM would reintroduce finding 12's own deadlock class — one node fires one edge, `all()` never satisfies. The required `on-grade-cap` edge is restored; CLOSE-FINALIZE keeps one predicate because grade-cap and no-finding are the same *routing* outcome differing only in grade. See `grade_cap_note` in the graph |
| 15 | verb-split inconsistency | LOW | **FIXED.** The stale "107 verbs / 23 modules / 27,542 LOC" paragraph surviving below its own correction box is replaced; Q2 marked RESOLVED with a pointer |
| 16 | seed-drift classification | LOW | **Observation, no action.** Critic independently verified every underlying fact (v6.4.3 fix shipped, 19 regression tests, zero live glob hits, no `~/.codex/prompts`) and judged MECHANICAL *defensible but borderline*. Recorded for operator awareness; the restated §2 is, in its words, "stronger than the original" |

**Generalizing finding 12 paid for itself.** The critic found one stranding edge; I wrote a
check for the whole class (*every `out_edge` must be matched by an `in_predicate` on its
target*) and it found **8 more** — the five `HOTFIX-W*` → gate edges, `PLAN-REVISION` →
`DEDUP-GATE-W0`, and two into `CLOSE-FINALIZE`. All were latent stalls. Resolved by
collapsing the HOTFIX nodes into the audit nodes' inline REDO loops (which is what
`flock.md §@auditor` describes anyway) and marking the historical PLAN-GATE pair done.
**Final graph: 31 nodes, zero stranding edges, zero unbacked predicates, every branch
point reaching HARD-STOP.**

## Open questions for critic

**Q1 (BLOCKING on operator, not critic) — the arc does not fit the remaining quota, and
I will not pretend otherwise.** 1,363 lines of Rust have landed against **42,560** lines
of Python to reproduce (measured, confirming the mesh exactly): roughly **3%**. The seed
sized this as six sprints; directive 1 compresses it into one run against a partly-spent
weekly quota. I am planning the full arc as instructed and **not** silently downscoping.
The operator decides what gets cut.

**The arithmetic, using A2's measurements — which correct my own.** My first pass sized
off 42,560 *raw* lines and produced ~480 steps. A2 tokenize-measured real executable
density at **39.2% — 16,684 lines**; the rest is bash-parity rationale prose. That
overstated the port ~2.5×. Corrected:

| Wave | Measured | Steps at the ~90 LOC floor |
|---|---|---|
| W0 foundation + oracle + dogfood | ~1,900 | ~14 |
| W1 core + **registry built from zero** | ~2,300–3,300 | ~26–37 |
| W2–W3 verb surface (101 leaf verbs, 43 groups) | **21,700–26,700 Rust logic lines** | **~240–297** |
| W4 distribution + adapters + retirement | ~1,600 new, −50,870 deleted | ~18 |
| **Total** | | **≈ 300–370 coder steps** |

The verb surface is still **~80%** of the work. At 5 lanes × ~10 steps per lane per wave
that is **five to six waves of verb porting alone**. The conclusion does not change; only
its magnitude does, and I would rather correct my own number than let a 2.5× overstatement
stand and frighten the operator into cutting more than necessary.

Two further facts sharpen it, both from A2:
- **The registry crate does not exist.** `crates/registry/src/lib.rs` is 241 lines of
  doc-contract plus `error.rs`, committed the same day as the audit. The premise that
  registry-backed verbs become "mechanical once the crate exists" is **false today** —
  nothing downstream of it is cheap yet.
- **#281 is 100% from scratch.** Zero golden fixtures exist anywhere; `conftest.py` is
  fully programmatic and ephemeral. The oracle is not a wrap of prior art.

Waves 2 and 3 are therefore written at **module granularity** rather than enumerated to
the floor: enumerating ~270 steps would produce an unreadable document whose only real
content is "this does not fit." Each nominal W2/W3 step is genuinely ~8–12 coder units and
**needs sub-decomposition before dispatch**. Flagged rather than disguised — a plan that
looks finished but hides a 10× expansion at dispatch time is worse than one that says so.

**Seed open question 3, answered with numbers: yes, the verb surface deserves its own
arc.**

### The recommendation the operator can accept or reject in one read

**Do not measure this arc by how far down the wave list it gets. The verb port is a
LANGUAGE MIGRATION; harness-agnosticism is a DIFFERENT GOAL, and only one of them is the
operator's stated north star.**

The north star was: *"a clean, canonical slate between any harness giving us a standard
set of routines, loops, template engine, etc."* What actually delivers that is
`content/` + the compiler + the three adapters + the shared predicate spec. **None of
those depend on the Rust verb surface.** The compiler emits Markdown/TOML/TS; the adapters
wrap whichever engine is canonical. Decision 5 already keeps Python canonical until parity
is green — so the adapters can ship over the *existing* engine and swap underneath later.

That makes the seed's `dev.5 → depends on dev.1` edge **not a real dependency** for the
emission path, only for run-state interop (C.4). This is the load-bearing claim of Option
A, so here is the reasoning explicitly rather than as an assertion — **test it, do not
take it:**

| Adapter output | What consumes it | Needs Rust? |
|---|---|---|
| `agents/*.md`, `commands/*.md`, `skills/*/SKILL.md` | the harness itself, as static files | **No** — emission is Markdown generation |
| Codex `[agent_types]` + `shepherd.codex.toml` | Codex, as static TOML | **No** |
| Pi `prompts/*.md` + a TS extension | Pi, via jiti | **No** — Pi's guard layer is TypeScript by decision 1 |
| `hooks/hooks.json` + guard scripts | the harness, which execs them | **No** — the guards read SQLite directly and shell out to the *existing* CLI (correction C11) |
| `run.json` read/advance (release-gate C.4) | the adapter | **No** — Python's `atomic_write_json` already writes canonical sorted JSON with `extra="allow"` round-tripping (A2, `models_run.py:615-639`, `:485`) |

Every row is satisfiable against the **current** Python engine. Decision 5 already
mandates Python stays canonical until parity is green, so Option A does not violate it —
it *leans* on it. The engine swap becomes a later, invisible substitution beneath a
contract the adapters already speak.

**The strongest counter-argument, stated fairly:** the predicate spec (decision 2) is
supposed to have ONE interpreter shared by the Rust engine and Pi's TS layer. Under Option
A there is no Rust interpreter yet, so the spec is interpreted by TS and by the existing
bash guards — arguably two interpreters of a spec designed for one, which is the exact
defect decision 2 forbids. My answer is that this is already today's state (bash guards +
nothing else) and Option A does not worsen it, while shipping the spec *as data* is what
makes the later single-interpreter consolidation cheap. **If the critic judges that
reasoning wrong, Option A collapses and Option B at W1-GATE is the fallback.**

**OPTION A — reorder: ship the harness-agnostic layer this run, defer the engine port.**

| | |
|---|---|
| **Runs now** | W0 (foundation, oracle, 11 dogfood dispositions) → W4-S3/S4/S5/S6 (`content/`, compiler, Claude + Codex + Pi adapters) → W4-S1 (auto-wire the launcher) |
| **Steps** | ~40, not ~340 |
| **What stands at the boundary** | Three harnesses driven from one authored source; a checksummed conformance oracle; a bootstrappable clean clone; the drift between Claude and Codex reconciled. **Python remains canonical and untouched** |
| **Carries forward** | The entire engine port — core, registry, render, 101 verbs, retirement — as its own arc, with the oracle already built to grade it |
| **Delivers the north star?** | **Yes, fully** |

**OPTION B — sequential: execute waves in order and stop at a gate.**

| Stop after | What stands | Delivers the north star? |
|---|---|---|
| W0-GATE | Oracle + dogfood fixes; no adapters | No |
| W1-GATE | Engine + registry parity-proven; no adapters | No |
| W3-GATE | Full verb parity; no adapters | No |
| W4-GATE | Everything | Yes — but ~340 steps away |

Under Option B every intermediate stop leaves the north star undelivered, because the
adapters are last. Under Option A the north star is delivered first and the language
migration is what waits.

**My recommendation: OPTION A.** It delivers exactly what the operator asked for, in ~12%
of the steps, and it leaves the deferred work in better shape than it found it (the oracle
exists before the port that needs it). If the operator's actual priority is retiring
Python rather than harness-agnosticism, Option B at **W1-GATE** is the right stop instead —
but those are different goals and the directive named the first one.

**The only irreversible step in either option is W4-S2** (deletes Python), which is gated
behind full parity and cannot run in Option A at all.

Coherent stop-boundaries, in order of preference. Decision 5 ("no canon flip before the
parity gate is green") is what makes every one of these safe: Python stays canonical, so
nothing is broken by stopping.

| Stop after | State shipped | Safe? |
|---|---|---|
| **W0-GATE** | Registry bootstraps on a clean clone; lint green; the oracle exists and is checksummed; 11 dogfood findings dispositioned | **Yes** — highest value per token in the whole arc |
| **W1-GATE** | Engine + registry landed and byte-parity-proven against the oracle | **Yes** — the recommended boundary |
| **W2-GATE** | Render + template parity proven | Yes |
| **W3-GATE** | Full verb parity, zero skips | Yes |
| mid-W4 | **UNSAFE** — W4-S2 deletes Python | **No** |

**My recommendation: plan the full arc, execute through W1-GATE, then re-decide.** W0+W1
delivers the structural wins (no more unbootstrapped clones, no more venv outages, a
real oracle) and leaves the repo strictly better with Python still canonical. The only
irreversible boundary in the whole plan is W4-S2.

**Q1-bis — stopping early collides with SUBTRACT, and the seed does not pre-authorize
it.** `SKILL.md §Principles` requires every sprint to end **strictly net-negative** on
LOC across `[gates.subtract_paths]`, and the close `completeness` auditor files
`SUBTRACT-VIOLATION` (grade-cap C+) otherwise. The only deletion in this entire arc is
**W4-S2**, which removes ~50,870 lines (42,560 Python + 8,310 bash) — and it is the last
substantive step, gated behind full parity by decision 5.

So the LOC curve is monotonically **positive** until the very end:

| Stop after | Net LOC delta | SUBTRACT verdict |
|---|---|---|
| W0-GATE | ≈ +1,400 | **net-positive → violation** |
| W1-GATE | ≈ +2,200 | **net-positive → violation** |
| W2-GATE | ≈ +12,000 | **net-positive → violation** |
| W3-GATE | ≈ +27,000 | **net-positive → violation** |
| W4-GATE (full arc) | ≈ −20,000 | passes |

This is structural, not a planning error: a rewrite that must prove parity before it may
delete is net-positive at every intermediate boundary, by construction. Two honest ways
out, and the operator picks:

1. **Amend the seed with a `sprint_metadata` block** declaring `expected_loc_delta` and
   `subtract_floor` — the sanctioned pre-authorization. This is the correct fix and costs
   one seed edit.
2. **Accept the C+ grade cap** for an intermediate stop, on the record, as the price of
   the parity-before-deletion discipline.

I am flagging this rather than letting the close auditor discover it, because discovering
it at close means the grade is already capped. **Recommend option 1, applied before Wave
0 starts.**

**Q2 — is the Wave 2/3 split right? RESOLVED, no longer an open question.** Wave 2 takes
the **14 Typer-native groups** whose argument grammar maps onto `clap` mechanically;
Wave 3 takes the **29 hand-parsed groups** (27 real steps after `render.py` and
`models_graph.py` are excluded as named exceptions) that bypass Typer via
`allow_extra_args` + `ignore_unknown_options` + a catch-all `raw: list[str]` and
`help_option_names=[]`. That is a difference in kind, not just size — the first is
translation, the second is byte-matching frozen strings.

The question I originally posed here was "29 or 21?" — **A2's AST walk settled it at 29,
and my 21 was wrong.** The mesh's *count* was right all along; only its *mechanism* name
was wrong (`sys.argv` appears zero times repo-wide; the real mechanism is the Typer
escape-hatch trio). Left in place as a resolved question rather than deleted, because
"the planter was right and I was not" is worth keeping visible. See §Wave 3.

**Q3 — does `shctx` survive as an alias?** Seed open question 2, unresolved. Agent-authored
prose across `skills/**` invokes it by name; W4-S1 deliberately does not remove it.
Operator's call.

**Q4 — DF-10, GitHub MCP provisioning.** The Docker catalog carries `github-official` but
it needs a `github.personal_access_token` secret. Wiring a credential is an operator
decision, not the engineer's. Until then `gh` remains the sanctioned fallback and this is
compliant, not a violation.

**Q5 — does `loader.rs`'s 4-tier chain degrade for harnesses with fewer tiers?** Codex has
3 effective tiers, Pi exactly 2. Decision 12 warns the chain is written highest-priority
first while `config` applies lowest-first, and that an adapter reimplementing it loads
configuration exactly backwards with no error anywhere. Carried as a W1 acceptance, but
flagged because it is the failure mode with no symptom.

**Q6 (CRITIC-RED escalation) — locked decision 3 is factually false, and #281 is
under-scoped as a result.**

Decision 3 reads: *"The registry schema is the cross-harness contract, not CLI stdout. All
32 guard scripts read SQLite directly and zero of them shell out to the CLI."* A3 found
**five functional shellouts across four guard scripts**, each feeding a guard decision
(correction C11). Three of those four scripts touch DB state *exclusively* through the
CLI, so they are invisible to a schema-only view.

I flagged this as CRITIC-RED rather than correcting it silently, because the seed says
changing a locked decision is exactly that. Note also that **my own earlier grep
"confirmed" decision 3** — I filtered `msg+=`/`warn+=` lines to exclude prose and
over-filtered, missing executed calls. A3 is right; I was wrong; the falsification is
cheap to re-run (`grep -nE '(bash )?"?\$?(shctx|bin/shepherd)"? [a-z]' hooks/scripts/*.sh`).

**Consequence, which is the part that matters:** the conformance oracle as specified in
#281 pins `sqlite_master` + `run.json` + template digests. That scope **lets five CLI
behaviors drift silently** — `dups check --stdin --as --json`, `seed verify`,
`teammate heartbeat --note`, `deliverable stalled --since-mins`, and `status`. A Rust
implementation could pass every conformance case and still break four guard scripts.

Three ways out; the operator picks, and I am not choosing unilaterally:

1. **Widen the oracle** — add a `--suite=guard-cli` covering those five verbs' exact
   stdout, exit codes and JSON shape. Cheapest, smallest blast radius, keeps decision 3's
   *intent* (the contract is machine-checked) while correcting its *claim*. **Recommended.**
2. **Remove the shellouts** — make all four guards read SQLite directly, restoring
   decision 3 as literally true. Larger change, touches live guards, and `dups check`'s
   `--stdin` shape is not obviously expressible as a query.
3. **Amend decision 3** to "schema *plus* an enumerated CLI surface is the contract."
   Honest, but leaves the surface unbounded unless the enumeration is itself gated.

Whichever is chosen, **the acceptance for #281 changes**, so this cannot be deferred past
PLAN-GATE.

## Mid-sprint plan deviations

*(append-only; empty at authorship)*
