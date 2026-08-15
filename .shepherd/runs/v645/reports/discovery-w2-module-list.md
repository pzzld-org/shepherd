---
title: Discovery — W2-S3..S16 Typer-native module member list
date: 2026-08-13
discovery_id: w2-module-list
sprint: v6.4.5
sources_consulted: 48
tool_calls_used: 30
time_used_minutes: 25
---

## Sources

- `.shepherd/runs/v645/plan.md` (full 2,590 lines; targeted reads at L1380-1460, L2495-2560, L2548-2549)
- `.shepherd/runs/v645/module-classification.json` (root's structured classification artifact — `callback`/`native` arrays + per-module `rows` with `callback_default`/`loc`/`verbs`)
- `.shepherd/runs/v645/reports/audit-a2-verb-surface-sizing.md` (A2's AST-walk report; the plan's cited authority for 101 verbs / 29 hand-parsed / 72.8% LOC)
- `services/cli/shepherd_cli/app.py` (full — `LAZY_GROUPS`/`LAZY_COMMANDS`, `command_names()`, `_LazyGroup`)
- `services/cli/shepherd_cli/__main__.py` (full — `_ported()`, bash-passthrough dispatch)
- All 44 non-`__init__` modules under `services/cli/shepherd_cli/commands/` — `wc -l`, targeted `grep`/`Read` for `context_settings`, `allow_extra_args`, `ignore_unknown_options`, `ctx.args`, `sys.argv`, `@app.command`, `@app.callback`, `invoke_without_command`, `add_typer` (sub-app nesting), plus full `Read` of `status.py` and targeted reads of `adapt.py`, `deliverable.py`, `home.py`, `teammate.py`, `run.py`, `loop.py`, `render.py`, `config.py`, `discovery.py`, `dups.py`, `eval.py`, `graph.py`, `handoff.py`, `insights.py`, `lint.py`, `plan.py`, `seed.py`, `style.py`

All numbers below are grounded in commands actually run; see the `## Findings` sections for the exact `grep`/`wc`/`python3` invocations.

## Findings

### 1. Neither of root's two stated predicates, nor any tested variant, reproduces the plan's literal 14/29 split

Commands run (from `services/cli/shepherd_cli/commands/`):

```bash
grep -l "allow_extra_args" *.py   # 17 files
grep -l "ctx\.args" *.py          # 1 file (query.py — already in the allow_extra_args set)
grep -l "sys\.argv" *.py          # 0 files, repo-wide
grep -l "invoke_without_command=True" *.py   # 39 files
```

- **Predicate "no `allow_extra_args`/`ctx.args`/`sys.argv`"** (root's claimed result: 43 native / 1 hand-parsed): the literal OR of these three substrings across `commands/*.py` matches **17 files** (all subsumed by the `allow_extra_args` set), not 1. There is no scoping of this predicate (module-level, whole-`shepherd_cli`-package level, or `__main__.py`-only) that yields "43/1" — the only file anywhere in the package that references `sys.argv` directly is `__main__.py:51`, and that module is the bash-passthrough entrypoint, not one of the 43 command groups. **This predicate's claimed result is not reproducible from the source as stated.**
- **Predicate "`@app.callback(invoke_without_command=True)`"** (root's claimed result: 5 native / 39 callback-driven): this one **does** reproduce exactly — confirmed two independent ways: (a) direct `grep -l invoke_without_command=True commands/*.py` → 39 files; (b) `module-classification.json`'s `native`/`callback` arrays → `native: [home, models_graph, render, run, teammate]` (5) / `callback: [...]` (39). But 5/39 is not 14/29 either — root's own predicate 2 disagrees with the plan by even more than predicate 1 does.
- I also tested the two structured fields on `module-classification.json` directly (`python3` script in scratchpad, exact commands below): `callback_default == True` → 39/4 (94.9% LOC); `verbs == 0` → 18/25 (42.2% LOC); `callback_default AND verbs==0` → 18/25 (identical to the previous). **None land near 14/29 or 72.8%.**

```python
# ran against module-classification.json rows (43 registered commands, models_graph excluded)
report("A: callback_default == True", lambda v: v["callback_default"])          # -> 39 hand / 4 native, 94.9% LOC
report("B: verbs == 0", lambda v: v["verbs"] == 0)                              # -> 18 hand / 25 native, 42.2% LOC
report("C: callback_default AND verbs==0", ...)                                  # -> identical to B
```

**Conclusion for item 2 of the brief: no predicate — root's two, nor the two additional structured-field predicates tested — reproduces the plan's 14/29 (72.8% LOC) figure exactly.** This is a legitimate finding, not a tooling failure.

### 2. The one predicate that gets within one module of 14/29 — and exactly why it's off by one

Reading each of the 29 modules A2 lists as hand-parsed shows a single, clean, bimodal structural signature separating real hand-parsed groups from Typer-native ones — **not** any of the substring predicates above, but the actual Click/Typer mechanism: does the group's `@app.callback(invoke_without_command=True)` set `context_settings={"allow_extra_args": True}` and/or `"ignore_unknown_options": True}` to swallow every token into one `raw: list[str] = typer.Argument(...)` and then hand-loop-classify it? Verified per-module with:

```bash
for f in <all 43 group modules>; do
  loc=$(wc -l < "$f.py")
  raw=$(grep -c "ignore_unknown_options\|allow_extra_args" "$f.py")
  cmds=$(grep -c "^@app.command" "$f.py")
  cbs=$(grep -c "^@app.callback" "$f.py")
  echo "$f,$loc,$raw,$cmds,$cbs"
done
```

Every one of the 28 modules with `raw>0` has the identical signature: `cmds=0, cbs=1` — one callback, zero `@app.command`s, all argument grammar hand-classified inside. Every module with `raw==0` either has `cmds>0` (real per-verb `@app.command()`s, e.g. `adapt`, `home`, `run`) or is a bare single-verb callback with ordinary typed `typer.Option`/`typer.Argument` parameters and no raw-capture `context_settings` at all (e.g. `status`).

Result: **15 native / 28 hand-parsed**, hand-parsed LOC = 24,817 of 34,260 total (**72.4%**), hand-parsed groups = 28/43 (**65.1%**). This is one module off from the plan's 14/29 (72.8%/67.4%) — and the one module is identifiable exactly:

**`status.py` is misclassified in A2's report and the plan.** Full read of `status.py` (382 lines) shows a single `@app.callback(invoke_without_command=True)` whose body is the entire command — a typed `json_out: bool = typer.Option(False, "--json", ...)` flag, `asyncio.run(_status_async(json_out=json_out))`, nothing else. `grep -n "context_settings\|allow_extra_args\|ignore_unknown_options\|typer.Argument" status.py` returns **zero hits** except the one `typer.Option` line. There is no raw-token capture, no `ignore_unknown_options`, no hand-parsed loop — it is structurally identical to the confirmed-native `home`/`teammate` pattern, just expressed as a bare callback instead of a `_default`-plus-subcommands pair. A2's own text even states the mechanism directly ("The real mechanism is Typer's `context_settings={allow_extra_args:True, ignore_unknown_options:True}`... capturing every post-group token") — `status.py` has none of that, yet A2's list of "the 29" includes `status`.

Corroborating evidence that A2's 14-module enumeration was never actually built as a coherent list (this is the plan's stated gap, independently confirmed): `plan.md:1435` — *"Densest Typer-native groups: `run` (16 verbs), `mem` (8), `loop` (8), `report` (6), `panes` (6), `lock` (6), `adapt` (6), `seed` (5)."* Two of these are wrong on their face: **`seed` is one of the 29 hand-parsed modules** (`seed.py:74-75`, own docstring: *"One `@app.callback(invoke_without_command=True, context_settings={ignore_unknown_options: True})` captures every token"*, confirmed `cmds=0, cbs=1, raw=4` hits) — it cannot simultaneously be in "the densest Typer-native groups." And the verb counts are wrong for two more: `lock` is listed at 6 but A2's own leaf-verb table (same report) gives it 4 (`show, acquire, release, reap`); `adapt` is listed at 6 but A2's own table gives it 5 (`roll, reflect, priors, report, recommend`). **The plan's only attempt at naming members of the 14 is internally self-contradictory and includes a module that belongs in the 29.** This is exactly the enumeration gap the brief identifies, now demonstrated three separate ways in the source text itself.

### 3. Full 43-group classification (mechanical clap-derive fit vs. hand-written parser)

`mechanical = YES` means: argument grammar is ordinary typed `typer.Option`/`typer.Argument` on `@app.command()`/`@app.callback()`, and maps onto `clap`'s `#[derive(Parser)]`/`#[derive(Subcommand)]` with no custom token loop. `mechanical = NO` means: single `@app.callback(invoke_without_command=True, context_settings={"allow_extra_args"/"ignore_unknown_options": True, ...})` swallowing all tokens into `raw: list[str]` and hand-classifying them (own usage heredoc, own flag vocabulary, own exit-code table — verified per A2's three worked examples: `doctor.py:1640-1672`, `close_lane.py:778-825`, `query.py:1-67`).

| Group | Source module | Leaf verbs | LOC | Mechanical? | Why |
|---|---|---:|---:|:---:|---|
| adapt | commands/adapt.py | 5 | 1267 | YES | `_default` bare-invoke shim (`ctx.invoked_subcommand is None`) + 5 flat `@app.command()`s (roll/reflect/priors/report/recommend), typed args |
| audit | commands/audit.py | 1 | 743 | NO | `context_settings={allow_extra_args, ignore_unknown_options, help_option_names:[]}`, single callback, hand loop |
| close-lane | commands/close_lane.py | 1 | 828 | NO | `allow_extra_args`; `<lane-id>` + 4 `--flag=` tokens hand-parsed, bespoke exit codes incl. migration-guard exit 2 |
| config | commands/config.py | 1 | 1204 | NO | `ignore_unknown_options`, `help_option_names:[]`; own docstring names the pattern explicitly |
| dash | commands/dash.py | 1 | 932 | NO | `allow_extra_args` + `ignore_unknown_options` |
| deliverable | commands/deliverable.py | 3 | 344 | YES | `_default` shim + 3 flat `@app.command()`s (promise/complete/stalled) |
| discovery | commands/discovery.py | 1 | 1007 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| doctor | commands/doctor.py | 1 | 1816 | NO | `allow_extra_args`; `_parse_args` flat token loop, `-h`/`--help` short-circuits (`:1640-1672`) |
| dups | commands/dups.py | 1 | 1207 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| eval | commands/eval.py | 1 | 968 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| export | commands/export.py | 1 | 706 | NO | `allow_extra_args` + `ignore_unknown_options` |
| graph | commands/graph.py | 1 | 1302 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| handoff | commands/handoff.py | 1 | 807 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| home | commands/home.py | 3 | 239 | YES | No callback at all — 3 plain `@app.command()`s (init/show/which) |
| init | commands/init.py | 1 | 1418 | NO | `allow_extra_args` + `ignore_unknown_options`, `help_option_names:[]` |
| inject | commands/inject.py | 1 | 449 | NO | `allow_extra_args` + `ignore_unknown_options` |
| insights | commands/insights.py | 1 | 760 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| issues | commands/issues.py | 1 | 1028 | NO | `allow_extra_args`; own docstring names `{allow_extra_args:True, ignore_unknown_options:True}` |
| lint | commands/lint.py | 1 | 546 | NO | `ignore_unknown_options` |
| lock | commands/lock.py | 4 | 650 | YES | 4 flat `@app.command()`s (show/acquire/release/reap), no raw capture |
| loop | commands/loop.py | 8 | 1071 | YES | flat commands + one nested sub-app (`add_typer(focus_app, name="focus")`) — mechanical but 2-level clap tree |
| mem | commands/mem.py | 8 | 815 | YES | 8 flat `@app.command()`s (add/list/search/show/pin/unpin/rm/delete) |
| migrate | commands/migrate.py | 1 | 928 | NO | `allow_extra_args` |
| models | commands/models.py | 3 | 640 | YES | 3 flat `@app.command()`s (help/resolve/show) |
| panes | commands/panes.py | 6 | 864 | YES | 6 flat `@app.command()`s (status/dash/capture/tail/prune/help) |
| plan | commands/plan.py | 1 | 1168 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| prune | commands/prune.py | 1 | 1109 | NO | `allow_extra_args` |
| query | commands/query.py | 1 | 395 | NO | `allow_extra_args`; also the only `ctx.args` hit — bespoke ordered-substitution SQL parser (`:1-67`) |
| ready | commands/ready.py | 1 | 518 | NO | `allow_extra_args` + `ignore_unknown_options`, `help_option_names:[]` |
| refresh | commands/refresh.py | 1 | 667 | NO | `ignore_unknown_options`, `help_option_names:[]` |
| release | commands/release.py | 1 | 942 | NO | `allow_extra_args` + `ignore_unknown_options`, `help_option_names:[]` |
| render | commands/render.py | 1 | 164 | YES | bare `LAZY_COMMANDS` entry, plain typed `typer.Argument`/`typer.Option` (template/var/vars-json/out/manifest/list) |
| report | commands/report.py | 6 | 818 | YES | 6 flat `@app.command()`s (help/discovery/audit/escalation/teammates/close) |
| run | commands/run.py | 16 | 1064 | YES | flat commands + **3** nested sub-apps (`lane_app`, `wave_app`, `ledger_app`) — mechanical but the deepest clap tree of the 43 |
| search | commands/search.py | 1 | 803 | NO | `allow_extra_args` |
| seed | commands/seed.py | 1 | 613 | NO | `ignore_unknown_options`; own docstring: "captures every token" — **plan's L1435 wrongly lists this as "densest Typer-native"** |
| signal | commands/signal.py | 2 | 209 | YES | 2 flat `@app.command()`s (send/poll) |
| sprint | commands/sprint.py | 4 | 651 | YES | `_default`-style bare-invoke help + 4 flat `@app.command()`s (help/open/wave/close), no raw capture |
| status | commands/status.py | 1 | 382 | YES | single callback IS the command, typed `--json: bool` only, zero raw-capture markers — **plan's 29 wrongly includes this** |
| style | commands/style.py | 1 | 677 | NO | `ignore_unknown_options` |
| sync | commands/sync.py | 1 | 354 | NO | `allow_extra_args` + `ignore_unknown_options`, `help_option_names:[]` |
| teammate | commands/teammate.py | 3 | 265 | YES | No callback at all — 3 plain `@app.command()`s (liveness/status/state) |
| worktree | commands/worktree.py | 1 | 922 | NO | `allow_extra_args` |

Totals: **15 mechanical** (9,443 LOC, 27.6%) / **28 hand-parsed** (24,817 LOC, 72.4%) / 101 leaf verbs total (73 in the mechanical 15, 28 in the hand-parsed 28 — 1 each).

### 4. Recommended W2-S3..S16 member list

The plan's step range `W2-S3..S16` has exactly **14** slots, but the source supports **15** genuinely mechanical modules (finding 2 above). Ranked cheapest-first by clap-tree-building cost — this wave's stated deliverable is "one `clap` subcommand tree per module" (`plan.md:1421-1422`), so the cost driver is leaf-verb count and sub-app nesting depth, not raw Python LOC (most of that LOC is bash-parity docstring prose per A2's own 39.2%-density finding, not argument-grammar surface):

| Step | Group | Verbs | Justification (cheapest first) |
|---|---|---:|---|
| W2-S3 | render | 1 | Bare `LAZY_COMMANDS` entry, single flat arg list, no sub-app — smallest possible clap surface |
| W2-S4 | status | 1 | Single callback, one typed bool flag — trivially maps to a zero-subcommand `clap` struct. **Correction to the plan: this module belongs in W2, not Wave 3** |
| W2-S5 | signal | 2 | 2 flat leaves (send/poll), no nesting |
| W2-S6 | home | 3 | 3 flat leaves, no callback/default shim to reason about |
| W2-S7 | teammate | 3 | 3 flat leaves, no callback at all — already the reference "ported" module the codebase docs point to |
| W2-S8 | deliverable | 3 | 3 flat leaves + one `_default` usage shim (same pattern as `adapt`, smaller) |
| W2-S9 | models | 3 | 3 flat leaves (help/resolve/show), no nesting |
| W2-S10 | sprint | 4 | 4 flat leaves + bare-invoke help, no nesting |
| W2-S11 | lock | 4 | 4 flat leaves, no nesting |
| W2-S12 | adapt | 5 | 5 flat leaves + `_default` shim — largest LOC in the flat-command tier but still zero nesting |
| W2-S13 | panes | 6 | 6 flat leaves, no nesting |
| W2-S14 | report | 6 | 6 flat leaves, no nesting |
| W2-S15 | mem | 8 | 8 flat leaves, no nesting — most leaves of any flat (non-nested) group |
| W2-S16 | loop | 8 | 8 leaves **with one nested sub-app** (`focus`) — first 2-level clap tree, deliberately landed last |

**15th mechanical module, recommend as a new `W2-S17` (not Wave 3):** `run` — 16 leaf verbs across **3** nested sub-apps (`lane`, `wave`, `ledger`), the largest and deepest clap tree of all 43 groups. It is unambiguously mechanical (zero raw-capture markers, all typed `@app.command()`s) so routing it to Wave 3 would be a category error, but its verb count and 3-way nesting make it a poor fit to force into the existing S3..S16 budget alongside 14 simpler modules — it is better decomposed on its own as an additional step (or split across 2 steps: one for `lane`+`wave`+`ledger` sub-app scaffolding, one for the 4 top-level leaves) rather than silently dropped or silently added as a 15th same-size step. This is a recommendation for engineer/conductor to accept or reject, not a plan edit made here.

## Open questions

1. **Does the plan want exactly 14 steps preserved (drop/merge one of the 15), or is `W2-S17` acceptable?** This changes downstream step numbering in `W2-GATE` and any step-count-based estimates elsewhere in the plan. Not resolved here — flagged for engineer.
2. **`plan.md:2548-2549`** states Wave 3 is "**27 real steps** after `render.py` and `models_graph.py` are excluded as named exceptions" from the 29 hand-parsed count — but neither module is in A2's 29-hand-parsed list to begin with (`render` is native; `models_graph` isn't a registered command at all, confirmed 0 `@app.command`/`@app.callback` decorators, imported only as a shared helper by `plan`/`graph`/`dash`/`release`). This sentence does not parse against the source and is a second, separate enumeration gap in the plan (Wave 3 scope, out of this brief's scope but worth engineer attention before W3-S1..S29 is dispatched).
3. Root's predicate-1 result ("43 native / 1 hand-parsed") could not be reproduced under any scoping tested (module-level, package-level, or `__main__.py`-only). If root ran a different corpus or a buggy grep, the artifact backing that specific number is unknown to this report — flag to root/engineer to locate or retract.
4. A2's report states LOC figures (25,127 for the 29, 8,942 for the 14) that are close to but not identical to what `wc -l` on the current tree gives for the same module lists (25,199 / 9,061 respectively — within ~0.3% and plausibly ordinary file drift since A2's audit ran, not a methodology error).

## Confidence

**HIGH** on findings 1-3 (predicate reproducibility, the true 15/28 mechanical split, the `status.py` misclassification, and the full 43-row table) — every classification is grounded in a `grep`/`wc`/direct `Read` against the actual current source, not inference from the plan's prose, and the bimodal signature (`cmds=0,cbs=1,raw>0` vs. everything else) was checked against all 43 modules with no exceptions found beyond `status.py`.

**MEDIUM** on the specific W2-S3..S16 ranking in finding 4 — the cheapest-first ordering is a reasonable, defensible proxy (leaf-verb count + nesting depth, matching this wave's own stated "one clap subcommand tree per module" deliverable) but is a recommendation, not a re-derivation from a doctrine-floor LOC estimate on the Rust output side, which nobody has produced yet.

## Suggested follow-ups

- Amend `plan.md`'s `W2-S3..S16` section to either (a) explicitly enumerate the 14-member list above with `status.py` swapped in for whichever module the engineer wants moved to Wave 3 (not recommended — none of the 15 are hand-parsed), or (b) add `W2-S17` for `run` and update `W2-GATE`'s step-count-dependent text accordingly.
- File a correction against `audit-a2-verb-surface-sizing.md`'s "the 29" list: remove `status`, and against `plan.md:1435`'s "Densest Typer-native groups" line: remove `seed` (hand-parsed), correct `lock` 6→4 and `adapt` 6→5.
- Resolve open question 2 before Wave 3 (`W3-S1..S29`) is dispatched — the `render.py`/`models_graph.py` "named exceptions" sentence needs its own source citation or should be struck.
