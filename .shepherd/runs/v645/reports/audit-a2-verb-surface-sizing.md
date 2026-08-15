# A2 — Python verb surface and sizing

**Reporter:** intro-mode `@auditor` · **Run:** v645 · **Materialized by:** root (payload landed in root's
notification stream, not the dispatching engineer's — see `dogfood.md` DF-11) · 2026-08-12

## Verb inventory

**43 command groups.** Ground truth `services/cli/shepherd_cli/app.py:59-113` — `LAZY_GROUPS` (42) plus
`LAZY_COMMANDS` (1, `render`). `app.py:116-124` `command_names()` is the single source both `--help` and
`__main__`'s passthrough set derive from. The `commands/` directory holds 44 non-`__init__` files, not 43:
`models_graph.py` is a shared contract module backing both `plan` and `graph`, registers no `app` object
(0 `@app.command`/`@app.callback` decorators), and is correctly absent from `LAZY_GROUPS`.

**101 leaf verbs, strict.** AST-walked, not grep and not `--help`: every `@X.command(...)` plus every
`@X.callback(invoke_without_command=True, ...)`, minus the 10 callbacks whose only job is printing the
bash-parity usage heredoc on bare group invocation (confirmed by reading bodies — `adapt.py:161-171`,
`deliverable.py:46-63`, both literally named `_default`, both gated on `ctx.invoked_subcommand is None`).
Counting those shims as verbs gives **111**. Either number is far below the mesh's "~147 ±10".

| Group | Leaves | Names |
|---|---|---|
| adapt | 5 | roll, reflect, priors, report, recommend |
| audit | 1 | |
| close-lane | 1 | |
| config | 1 | |
| dash | 1 | |
| deliverable | 3 | promise, complete, stalled |
| discovery | 1 | |
| doctor | 1 | |
| dups | 1 | |
| eval | 1 | |
| export | 1 | |
| graph | 1 | |
| handoff | 1 | |
| home | 3 | init, show, which |
| init | 1 | |
| inject | 1 | |
| insights | 1 | |
| issues | 1 | |
| lint | 1 | |
| lock | 4 | show, acquire, release, reap |
| loop | 8 | init, native-cmd, status, record, close, list, focus:upsert, focus:show |
| mem | 8 | add, list, search, show, pin, unpin, rm, delete |
| migrate | 1 | |
| models | 3 | help, resolve, show |
| panes | 6 | status, dash, capture, tail, prune, help |
| plan | 1 | |
| prune | 1 | |
| query | 1 | |
| ready | 1 | |
| refresh | 1 | |
| release | 1 | |
| render | 1 | (bare command, `LAZY_COMMANDS`) |
| report | 6 | help, discovery, audit, escalation, teammates, close |
| run | 16 | init, rename, canonicalize, show, list, migrate, set, lane:add, lane:set, wave:accept, wave:merged, wave:pending, ledger:path, ledger:check, wave:verify, layout |
| search | 1 | |
| seed | 1 | |
| signal | 2 | send, poll |
| sprint | 4 | help, open, wave, close |
| status | 1 | |
| style | 1 | |
| sync | 1 | |
| teammate | 3 | liveness, status, state |
| worktree | 1 | |
| **Total** | **101** | 43 groups |

`loop` and `run` each nest a second-level Typer sub-app (`loop.py:145` `add_typer(focus_app, name="focus")`;
`run.py:138-140` `lane_app`/`wave_app`/`ledger_app`), producing 3-token paths like `shepherd run wave verify`.

## Hand-parsed modules — 29 of 43, count exact, mesh's mechanism wrong

`grep -c 'sys.argv' services/cli/shepherd_cli/commands/*.py` returns **zero hits repo-wide.** The mesh's
"hand-parse `sys.argv`" description names an API this codebase does not use. The real mechanism is Typer's
`context_settings={"allow_extra_args": True, "ignore_unknown_options": True}` on a single
`@app.callback(invoke_without_command=True)`, capturing every post-group token into one
`raw: list[str] = typer.Argument(None)`, then a private `_parse_args` or inline loop classifying each token
by hand. `doctor.py:214-232` documents the reason directly: `help_option_names=[]` is required for
byte-exact bash `-h`/`--help` heredoc parity, which Click's own `--help` machinery cannot produce.

The 29: `audit, close_lane, config, dash, discovery, doctor, dups, eval, export, graph, handoff, init,
inject, insights, issues, lint, migrate, plan, prune, query, ready, refresh, release, search, seed, status,
style, sync, worktree`.

Three worked examples:

1. **`doctor.py:1640-1672`** (`_parse_args`) — flat `for token in tokens`; `-h`/`--help` prints `_USAGE`
   (`doctor.py:239-251`) verbatim to stdout and exits 0, short-circuiting so later tokens are never
   examined (bash `case`-arm semantics, documented at `:1652-1658`); `--json`/`--md` are last-token-wins;
   anything else is `ERROR: unknown arg: {token}` to stderr, exit 1. The 3-way exit contract (0/1/2 from
   `run()`, `:1675-1698`) lives in the docstring and is not derivable from the flag vocabulary.
2. **`close_lane.py:778-825`** — `<lane-id>` positional plus `--sprint=`/`--issues=`/`--status=`/
   `--acceptance=` in any order, each with its own missing/invalid-value message and its own exit code —
   including exit 2 specifically when the `lane_closures` table predates migration 0003 (`:803-806`).
3. **`query.py:1-67`** — genuinely bespoke. A 3-stage ordered `str.replace` substitution: `:project_id` to
   a quoted UUID unescaped, then each `--key=val` flag in argv order with quote-doubling, then a final
   regex sweep replacing any leftover `:token` with bare `NULL` across the **entire already-substituted SQL
   text, including inside string literals** (`:39-47`). The module docstring flags this as "an inherited
   quirk kept for parity rather than fixed" (`:37-38`). Order-sensitive, deliberately non-obvious, and it
   needs independent unit tests — a usage-text diff will not catch a regression here.

**Verdict: mechanical, not creative-bespoke, but per-module and non-batchable.** No module needs business
judgment; every one is "reproduce this exact usage string, this exact flag vocabulary, this exact
exit-code table, in this order." But each of the 29 has its *own* heredoc, vocabulary, and exit-code table
(confirmed distinct across all three samples), so there is no macro or codegen shortcut. It is 29 separate
transcription-plus-golden-verification passes.

## Sizing

| Metric | Value | Method |
|---|---|---|
| Implementation LOC (excl. tests, `.venv`, `__pycache__`) | **42,560** | `find shepherd_cli -name '*.py' -not -path '*/__pycache__/*' \| xargs wc -l` |
| Test LOC | **32,945** | same over `tests/` |
| pytest functions | **1,583** | `grep -rhE '^\s*(async )?def test_' tests \| wc -l`, 54 files |
| Hand-parsed 29 modules | **25,127 LOC** (72.8% of `commands/`) | `wc -l` |
| Typer-native 14 modules | **8,942 LOC** | `wc -l` |
| `models_graph.py` (shared, non-command) | 468 LOC | |
| Real executable density | **16,684 of 42,560 = 39.2%** | `tokenize`, excluding COMMENT/STRING/structural tokens |

The 29 hand-parsed modules carry **72.8% of command-registration LOC while being 67.4% of the groups** —
disproportionately expensive per group, consistent with the per-module-transcription verdict.

Raw LOC **overstates translation effort by roughly 2.5x**: 60.8% of the implementation is comment and
docstring prose, because this codebase documents bash-parity rationale exhaustively (`query.py` opens with
a 67-line module docstring before any code).

**Rust estimate to parity: ~21,700-26,700 lines of executable logic** (16,684 real Python lines x 1.3-1.6
verbosity multiplier for explicit types and error propagation over dynamically-typed Python with a
framework doing implicit dispatch). Matching this codebase's own doc density adds another 25-40%, landing
total Rust file-LOC in the same 35-45K neighbourhood as the Python source — **plus** the registry crate,
which is not built.

Thin-CRUD versus bespoke-logic split is an **ESTIMATE, not a count** — a true per-verb split needs reading
all 101 bodies. Keyword-density scan (`SELECT|INSERT|UPDATE|DELETE` plus
`difflib|SequenceMatcher|regex|scor(e|ing)|threshold`): clear-bespoke are `dups.py` (47 hits, dedup and
similarity), `eval.py` (47, scoring), and `config.py`/`worktree.py`/`panes.py`/`query.py`/`lint.py` (12-18
each). Clear-thin are `home.py`, `teammate.py`, `signal.py`, `deliverable.py`, and `mem.py`'s simpler
verbs. **Directional: roughly 35-45 of 101 verbs are thin registry CRUD-plus-format wrappers; the
remainder carry real per-verb logic** a mechanical stamp-out will not cover.

## NO-FIT verdict

**This does not fit inside one run alongside 5 other deliverables.** Three independent numbers converge:

1. **The premise the sizing model leans on is false today.** "Thin wrappers become mechanically portable
   once the registry crate exists" presumes a registry crate. `crates/registry/src/lib.rs` is a 241-line
   skeleton — doc contract plus `error.rs`, no schema, no migration runner, no query surface — committed
   **the same calendar day as this audit** (`git log -1 --format=%ai crates/registry/src/lib.rs` →
   `2026-08-12 16:10:34`). Nothing downstream of it is cheap yet.
2. **29 of 43 groups need independent, non-batchable transcription plus golden-diff**, one of which
   (`query.py`) additionally requires porting order-sensitive substitution semantics correctly.
3. **1,583 pytest assertions define the byte-exact bash-parity contract, with zero golden fixtures to lean
   on.** The conformance oracle (#281/#282, both CRITICAL) must be built from scratch before any port work
   can be verified, and it does not exist.

The verb surface alone is a multi-sprint arc even under the now-disproven "mechanical CRUD" framing the
mesh used to justify XL-not-bigger.

## Oracle requirements

**`run.json` writer: `services/cli/shepherd_cli/models_run.py:615-639`, `atomic_write_json`.** Tempfile in
target dir → `json.dump(payload, handle, indent=2, sort_keys=True)` (`:627`) → `\n` → `fsync` →
`os.replace` → `fsync(dir)`.

- **Canonical sorted ordering: TRUE** (`sort_keys=True`, `:627`). #282's first assertion already holds.
- **Unknown-key round-trip: TRUE.** `RunState.model_config = ConfigDict(extra="allow")` (`:485`), same for
  `LaneState` (`:507`). Deliberate #247 fix — the module docstring (`:20-32`) records that a prior
  `extra="forbid"` schema rejected **100% of live `run.json` files** (33 and 17 validation errors on two
  measured runs) because bash and codex-shepherd both write fields this CLI does not declare. The tolerant
  reader `normalize_run_document` (`:678+`) plus `extra="allow"` preserves them load-to-save. #282's second
  assertion also holds.
- **Contrast worth carrying into the harness:** `crates/registry/src/lib.rs:31` itself states acceptance
  requires an *order-normalized* `sqlite_master` dump — `sqlite_master` is **not** naturally
  canonical-ordered and the harness must normalize it, unlike `run.json` which already is.

**Pure versus mutating verb split: ESTIMATE, do not treat as ground truth.** Module-file write-signal grep
(`.save(|.create(|.update(|.delete(|INSERT|UPDATE|DELETE|atomic_write_json|os.makedirs|open(...'w'`) shows
~17 modules with zero mutation signal: `teammate, sync, status, seed, search, report, ready, query, models,
lint, issues, insights, inject, doctor, dash, sprint`. This **undercounts** true mutators whose write call
lives in an imported shared module — `sprint.py`'s `open`/`close`/`wave` verbs almost certainly mutate via
`models_graph.py`/`models_run.py` rather than inline. Starting point for harness triage only.

**Non-determinism sources the harness must pin:**

| Source | Where | Pin |
|---|---|---|
| `time.time()` | duplicated per-module: `adapt.py:192`, `close_lane.py:191`, `doctor.py:791/823`, `dash.py:845`, `audit.py:525` (`int(time.time())*1000`, deliberately **not** `int(time.time()*1000)` — `:514-525`) | freeze clock per MUTATING case |
| UUIDv7 ids | `_uuid7()` duplicated per-module (`adapt.py:195-207`, `close_lane.py:194+`; per `close_lane.py:68` more copies exist) — embeds the timestamp in its high bits | seed a deterministic generator, or normalize UUID fields out of the diff |
| Absolute paths in stdout | `resolve_repo_root`/`resolve_workdir` (`resolution.py:53,122`) leak into ≥10 modules: `close_lane, discovery, dups, audit, graph, init, handoff, migrate, plan, models` | path-normalize repo root and workdir to fixed tokens before diffing |
| Locale | `issues.py:579` docstring notes `printf '%-Ns'` under C/POSIX is load-bearing for column padding | pin `LC_ALL=C` |
| Env leakage | `resolve_workdir`/`resolve_repo_root` precedence is env-driven (`resolution.py:122-125`) | fix env vars per case, not just cwd |
| Hostname / PID | none found — `grep -rn 'socket\.\|platform.node\|os.uname' commands/*.py` empty | no action; recheck as modules land |

`_uuid7()`/`_now()` are duplicated per-module by **deliberate self-containment policy**
(`close_lane.py:68-69` names it), not accidental drift — so the pinning shim cannot hook one shared helper.
It must monkeypatch `time.time` and UUID generation globally.

**Golden or snapshot fixtures: NONE exist.** `find tests -iname '*golden*' -o -iname '*snapshot*' -o -iname
fixtures` returns nothing; `find tests -type d` returns only `.` (55 files, flat). `conftest.py:100-145`
builds fixture DBs programmatically from migration SQL into a `tmp_path` per test. Nothing on disk is a
checked-in golden output. **#281 starts from zero prior art — 100% new build, not a wrap-and-extend.**

## Findings

1. **HIGH** — Mesh's leaf-verb estimate is **overstated by 30-46 verbs**, not understated. 101 strict / 111
   loose against "~147 ±10". Shrinks the count; does not offset findings 2-3.
2. **HIGH** — "Mechanically portable once the registry crate exists" is currently false. Registry is 0%
   built; the 20 migration SQL files it commits to porting verbatim total 1,182 lines and are trivial, but
   the runner and query surface every thin-CRUD verb depends on do not exist.
3. **HIGH** — No conformance oracle and no golden fixtures anywhere. #281 (CRITICAL) is from-scratch.
4. **MEDIUM** — Raw impl LOC overstates effort ~2.5x; real density 39.2%.
5. **MEDIUM** — "`sys.argv`" is the wrong mechanism name (0 hits repo-wide). The 29 count is right; anyone
   porting off the mesh's literal description hunts the wrong Python API.
6. **MEDIUM** — Exit-code branches are per-module bespoke, not table-driven (`close_lane.py:806`). A
   generic usage-text-plus-flag-loop generator misses these without per-module review.
7. **LOW** — Absolute-path leakage confirmed in ≥10 modules; harness needs a normalization pass.
8. **LOW** — `_uuid7()`/`_now()` duplication is policy, so the shim must patch globally.

**Routing note from the reporter:** "No SendMessage-class tool is present in this session's tool list, so I
cannot route this directly to `shepherd-engineer-v645`." This is the DF-11 leak in the direction the
doctrine predicted — the sub-agent has no channel back to its dispatching lead.
