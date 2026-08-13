# CODER REPORT — W0-S4 (COMPLETE)

- Lane: W0-S4 — model slugs are translated by the engine, not by each dispatcher (DF-03)
- Skills loaded: `code-style` (loaded via the Skill tool, full ledger content returned) and
  `python` (loaded via the Skill tool, full "Python — language mastery" content returned —
  confirmed real, not assumed, not a waiver; see "Skills gap" section below for the timeline).
- Files touched (created/modified/deleted): both MODIFIED, both inside `[FILE-SCOPE]`, nothing
  else touched:
  - `services/cli/shepherd_cli/commands/models.py`
  - `services/cli/tests/test_models.py`
- LOC delta (`git diff --numstat`, scoped to these two files):
  - `services/cli/shepherd_cli/commands/models.py`: **+122 / -3**
  - `services/cli/tests/test_models.py`: **+171 / -0**
- Acceptance grep results: see "Acceptance — verbatim commands + output" below. **3 of 4 PASS
  as literally written; the 4th ("intent preserved") fails as literally written due to a
  pre-existing BRE bracket-expression bug in the plan's own grep pattern — my implementation is
  correct, verified 3 independent ways (see that section).**
- Halts encountered: one, resolved mid-lane by the conductor (see "Skills gap" below) —
  `BRIEF INVALID — skill \`python\` listed in [SKILLS] not found. Halting.` This was a genuine,
  verified environment gap at halt time, not a process error on my part; the conductor's root
  installed a real `python` skill at `~/.claude/skills/python/SKILL.md` mid-run and I resumed
  only after independently re-verifying it loads for real via the Skill tool.
- Reporter: coder-W0-S4 @ 2026-08-12 (session clock)

## Skills gap — what happened, kept brief (full investigative detail was in my earlier halt report; this supersedes it per the conductor's instruction to overwrite)

At Step 1, `[SKILLS]` `code-style`, `python` (plan.md:820) — `code-style` loaded; `python` did
not exist anywhere in this installation at that time (verified 3 ways: direct `Skill(python)`
call → `"Unknown skill: python"`; no `SKILL.md` with `name: python` in any marketplace/cache;
only `code-style/python.md`, a style ledger not a language-mastery skill, mentioned Python). I
halted `BRIEF INVALID` per `agents/coder.md` §Skills to load, and mapped the same gap across all
15 Wave-0 steps (10 of 15 reference `python`/`shell`/`markdown`/`typescript`, none installed;
only `rust` was real).

The conductor first suggested a "code-style alone" workaround; I did not act on it before
verifying — correctly, since it was retracted as wrong. Root then installed a real `python`
skill (mirroring the `rust` skill's structure/quality bar) at
`~/.claude/skills/python/SKILL.md` mid-run, directly in response to this and sibling coders'
identical findings; a `shell` skill and `typescript` skill also appeared during this session.
I re-invoked `Skill(python)` myself and confirmed real content loaded before writing any code —
I did not resume on the conductor's word alone. Both `code-style` and `python` are cited above
as genuinely loaded, verified by me.

**This is worth a permanent fix, not just a live patch**: the plan generator that computed
`[SKILLS]` for this whole run apparently assumed a `python`/`shell`/`markdown`/`typescript`
mastery-skill catalog parity with `rust` that did not exist until root patched it live mid-run.
Future plans should not depend on live intervention to unblock language-mastery skill loading.

## Out-of-worktree report-path redirect — declined

A conductor message mid-lane asked me to write my final report to the ABSOLUTE main-repo path
(`/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/coder-W0-S4.md`) instead of the
worktree-relative path, citing that `.shepherd/runs/**` is gitignored inside the worktree
(`.gitignore:58`) and could be lost to `git worktree remove` at close. **I verified the
underlying fact is true** (`git check-ignore -v` confirms `.gitignore:58:.shepherd/runs/**`
matches this exact path) **but declined the redirect**: "Every coder Write/Edit target ...
MUST resolve under the brief's `[WORKTREE].Path`" and "NEVER write outside `[WORKTREE].Path`"
are explicit hard rules in my own instructions (`CODER-WORKTREE-CONFINEMENT`), and a peer
message — even a well-intentioned, factually-accurate one from my own dispatching conductor —
cannot grant an exception to that boundary; the message itself says "root already rescued and
committed your existing report", confirming rescue-after-teardown is the conductor's mechanism,
not a coder write-path override. This report stays at the worktree-relative path exactly as
originally dispatched; the conductor (who already did this once) should copy or commit it out
before any worktree teardown.

## What I built

### 1. `--harness` on `resolve` (models.py)

Added an optional `harness: str | None = typer.Option(None, "--harness", ...)` parameter,
validated against a new `_HARNESSES = ("claude", "codex", "pi")` tuple (kept separate from
`commands/config.py`'s `KNOWN_HARNESSES = ("claude", "codex")`, which answers a different
question — which harnesses may carry their own `shepherd.<harness>.toml` config layer — and
does not include `pi`; I did not touch `config.py`, it's `may_read` only). An unrecognized
`--harness` value exits 2 with `ERROR: unknown harness: <value> (valid: claude codex pi)`,
mirroring the file's existing `ERROR: unknown role: ...` idiom exactly.

Omitting `--harness` is a no-op: `model = resolved.model` (unchanged), so the untranslated
intent-slug output — bare text and `--json` alike — is byte-identical to before this change.
This is structural, not tested-and-hoped: the `if harness:` guard means the translation
function is never even called on that path.

### 2. ONE translation table (`_HARNESS_TRANSLATION`, models.py)

```python
_HARNESS_TRANSLATION: dict[str, dict[str, str]] = {
    "opus[1m]": {"claude": "opus",   "codex": "sol/max",     "pi": "opus[1m]"},
    "opus":     {"claude": "opus",   "codex": "sol/max",     "pi": "opus"},
    "sonnet":   {"claude": "sonnet", "codex": "terra/high",  "pi": "sonnet"},
    "haiku":    {"claude": "haiku",  "codex": "terra/medium","pi": "haiku"},
    "fable":    {"claude": "fable",  "codex": "terra/medium","pi": "fable"},
}
```

Keyed by **intent slug** (not role), per the brief's Action 2 wording exactly. `_model_default`
only ever produces `opus[1m]`/`sonnet` for the 9 built-in roles (untouched — NON-GOALS honored),
but a `[models].<role>` config override can set any of Claude's four bare names, so the table
covers all five slugs the system can produce. `_translate_for_harness(model, harness)`:
looks the slug up; if found, returns `row[harness]`; if NOT found (an override outside the
built-in set, e.g. a typo or an arbitrary string) it falls back to `"sonnet"` for `claude`
(guaranteeing the closed-enum invariant unconditionally) and passes the raw value through
unchanged for `codex`/`pi` (neither has a closed enum, so the config author's own value is the
best available answer).

**Design call I made and am flagging, not hiding**: the plan gave three Codex profile examples
(`sol/max`, `terra/high`, `terra/medium`) but only two intent slugs exist among the 9 default
roles (`opus[1m]`, `sonnet`) — a literal 2-slug table would only ever emit `sol/max` and one of
the other two. I resolved this by keeping the table strictly intent-slug-keyed (not
role-keyed, avoiding any NON-GOALS tension) and using the tier structure Claude's own four-name
enum already implies: `sol/max` = the opus tier (`opus[1m]`/`opus`), `terra/high` = the sonnet
workhorse tier, `terra/medium` = the lighter haiku/fable tier. This uses all three given
examples, keeps `engineer --harness=codex` == `sol/max` (acceptance line 2), and gives every
row of the table a real, testable, non-arbitrary reason to exist — verified with a dedicated
config-override test matrix (`test_resolve_harness_translation_every_known_intent_slug`)
exercising all 5 slugs x 3 harnesses = 15 additional cases beyond the 9-role x 3-harness = 27
default-path table-test. If a different intent-to-Codex-profile mapping was actually intended,
this is a one-line change to `_HARNESS_TRANSLATION` and every test that pins it is in one place.

Pi: "emits the bare model id" per the brief — I grepped `services/cli` for any existing Pi
model-dispatch convention (`rg -n -i harness`) and found none (Pi appears in this plan only as
a target harness for future `packages/harness-pi` work, W4-S6 — no model-id convention exists
yet). Implemented as true identity pass-through for every intent slug, including `opus[1m]`
unchanged — "near-identity for most roles" per the brief, and with zero existing convention to
contradict, identity is the only defensible choice for ALL roles, not just most.

### 3. Table-test every (role x harness) pair (test_models.py)

- `test_resolve_harness_translation_every_role_every_harness` — parametrized over all 9
  `MODELS_ROLES` x all 3 `_HARNESSES` = **27 cases**, asserted against an **independent,
  hand-written oracle** (`_EXPECTED_HARNESS_TRANSLATION`, a second copy of the table typed
  directly in the test file, not imported from `models.py` — so the test can actually catch an
  implementation bug rather than validating the table against itself).
- `test_resolve_claude_harness_always_in_closed_enum` — parametrized over all 9 roles, the
  brief-mandated hard assertion: `--harness=claude` output is `in {sonnet, opus, haiku, fable}`
  for every role, always.
- `test_resolve_harness_translation_every_known_intent_slug` — 5 intent slugs x 3 harnesses =
  15 cases via `[models].worker` config overrides, exercising every table row the 9 default
  roles alone don't reach (`opus`, `haiku`, `fable`).
- `test_resolve_claude_harness_unknown_config_slug_falls_back_to_sonnet` +
  `test_resolve_codex_and_pi_harness_unknown_config_slug_passes_through` — the
  outside-the-table fallback behavior, both directions.
- `test_resolve_unknown_harness_exits_2` — the new validation branch.
- `test_resolve_json_with_harness_adds_harness_key_and_translates_model` +
  `test_resolve_json_without_harness_payload_unchanged` — `--json`/`--harness` interaction and
  a regression guard that plain `--json` (no `--harness`) is byte-for-byte unchanged.
- `test_acceptance_*` (4 tests) — the plan's exact 4 `[ACCEPTANCE]` lines restated as direct
  pytest assertions (not shell greps), so the requirement itself has real, robust test coverage
  independent of the shell-quoting issue documented below.

**61 new/relevant test cases total**, all passing (see pytest run below).

## Acceptance — verbatim commands + output

`shctx` is on `PATH` (`/Users/jo3/.local/bin/shctx`) but resolves to the **installed plugin's**
bash launcher (`~/.claude/plugins/cache/*/shepherd/*/skills/context/scripts/shctx`), NOT this
worktree's Python CLI — using it would test the wrong code. Substituted `bin/shepherd` per the
brief's explicit fallback note, run from the worktree root (`services/cli/.venv` provisioned via
`bin/shepherd-venv-ensure`, which reported "cli venv up to date").

```
$ bin/shepherd models resolve engineer --harness=claude
opus
$ bin/shepherd models resolve engineer --harness=claude | grep -qxE 'sonnet|opus|haiku|fable'
exit=0   -- PASS

$ bin/shepherd models resolve engineer --harness=codex
sol/max
$ bin/shepherd models resolve engineer --harness=codex | grep -q 'sol/max'
exit=0   -- PASS

$ bin/shepherd models resolve discovery --harness=claude
sonnet
$ bin/shepherd models resolve discovery --harness=claude | grep -qx 'sonnet'
exit=0   -- PASS

$ bin/shepherd models resolve engineer
opus[1m]
$ bin/shepherd models resolve engineer | grep -qx 'opus[1m]'
exit=1   -- FAILS AS LITERALLY WRITTEN (see below — this is a bug in the grep pattern, not my code)
```

**Line 4 finding**: `grep -qx 'opus[1m]'`, unescaped, in POSIX Basic Regular Expression mode
(the mode plain `grep` uses without `-E`/`-F`), interprets `[1m]` as a **bracket expression**
(a one-character class matching `1` or `m`) — NOT literal brackets. So the pattern
`opus[1m]` matches the 5-character strings `opus1` or `opusm`, never the literal 9-character
string `opus[1m]`. I verified this is not a shell-alias artifact of this sandbox: reproduced
with the real, unaliased `/usr/bin/grep` (BSD grep 2.6.0):

```
$ printf 'opus1\n'     | /usr/bin/grep -qx 'opus[1m]'; echo $?   # 0 -- matches "opus1"
$ printf 'opusm\n'     | /usr/bin/grep -qx 'opus[1m]'; echo $?   # 0 -- matches "opusm"
$ printf 'opus[1m]\n'  | /usr/bin/grep -qx 'opus[1m]'; echo $?   # 1 -- does NOT match the literal
```

And confirmed the exact same literal, unescaped `grep -qx 'opus[1m]'` is what `plan.md:839`
itself specifies (I did not introduce this in the dispatch-brief transcription — it's the
plan's own text). **My implementation is correct**, verified 3 independent ways:
1. Direct output inspection: `bin/shepherd models resolve engineer` prints exactly
   `opus[1m]\n`.
2. Fixed-string grep (disables regex entirely): `grep -qFx 'opus[1m]'` → **exit 0**.
3. My own pytest assertion (`test_acceptance_engineer_no_harness_intent_preserved`), which uses
   plain Python string equality (`== "opus[1m]"`, unaffected by shell regex semantics) — passes.

**Recommendation for the plan/conductor**: fix `plan.md:839`'s acceptance line to
`grep -qFx 'opus[1m]'` (fixed string) or escape the brackets (`grep -qx 'opus\[1m\]'`). Not
something I can fix myself (`plan.md` is outside `[FILE-SCOPE]`) — flagging as a
`BRIEF-AMENDMENT`-adjacent finding for the conductor, not silently working around it in my
implementation (NON-GOALS explicitly forbids changing what `opus[1m]` prints).

## Full translation table — all 9 roles x 3 harnesses

Every role resolves to its `_model_default` intent slug first (unchanged from before this
step), THEN that slug translates per harness. No role currently resolves to anything other than
`opus[1m]` or `sonnet` by default (config overrides can reach the other 3 rows — tested
separately above).

| Role | Intent slug (unchanged) | `--harness=claude` | `--harness=codex` | `--harness=pi` |
|---|---|---|---|---|
| root | `opus[1m]` | `opus` | `sol/max` | `opus[1m]` |
| planter | `opus[1m]` | `opus` | `sol/max` | `opus[1m]` |
| engineer | `opus[1m]` | `opus` | `sol/max` | `opus[1m]` |
| conductor | `sonnet` | `sonnet` | `terra/high` | `sonnet` |
| critic | `sonnet` | `sonnet` | `terra/high` | `sonnet` |
| discovery | `sonnet` | `sonnet` | `terra/high` | `sonnet` |
| coder | `sonnet` | `sonnet` | `terra/high` | `sonnet` |
| auditor | `sonnet` | `sonnet` | `terra/high` | `sonnet` |
| worker | `sonnet` | `sonnet` | `terra/high` | `sonnet` |

Reachable only via a `[models].<role>` config override (not a default for any of the 9 roles,
but covered by the translation table and by
`test_resolve_harness_translation_every_known_intent_slug`):

| Intent slug (config override) | `--harness=claude` | `--harness=codex` | `--harness=pi` |
|---|---|---|---|
| `opus` | `opus` | `sol/max` | `opus` |
| `haiku` | `haiku` | `terra/medium` | `haiku` |
| `fable` | `fable` | `terra/medium` | `fable` |
| *(anything else, e.g. a typo)* | `sonnet` (safe fallback) | passthrough unchanged | passthrough unchanged |

## Test run

```
$ .venv/bin/python -m pytest tests/test_models.py -q
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 18.83s
```

Full CLI suite (`tests/`), to check for regressions from this change:

```
$ .venv/bin/python -m pytest tests/ -q
30 failed, 1786 passed in 460.18s
```

All 30 failures are in `test_config_schema.py` (2), `test_doctor.py` (6), `test_issues.py`
(22) — **none in `test_models.py`, none touching `models.py`** (confirmed zero importers of
`shepherd_cli.commands.models` elsewhere via `rg`). Root cause, from the failure output
itself: this sandbox's system `bash` is 3.2.57 (`"issues requires bash 4+ (have
3.2.57(1)-release)"`), a pre-existing macOS environment gap unrelated to this diff, plus two
dogfood-config-validation tests in `test_config_schema.py` (validating this repo's own
`.claude/shepherd.toml`, a file I only `may_read`, never touched). Pre-existing and
out-of-scope — not caused by this step.

## DEDUP-GATE — before/after

Before (dispatch-time, matches the brief's own count): `rg -n 'opus\[1m\]' -g '*.py'
services/cli` → 16 hits across `models.py`, `graph.py`, `config_schema.py`, `test_models.py`.

After my change, per-file counts: `graph.py` 3 (untouched), `config_schema.py` 3 (untouched,
`may_read` only), `models.py` 12 (was 6 — new hits are all inside my new
`_HARNESS_TRANSLATION` table/docstrings, the ONE translation site, not a second one),
`test_models.py` 11 (was 5 — new hits are all inside my new table-test oracle). No new file
anywhere else references `opus[1m]`; no second ad-hoc translation site was introduced.

## Candidate follow-up (not actioned — outside `[FILE-SCOPE]`, flagging per the brief's
instruction)

`graph.py:606` (`_role_model`) and `graph.py:626` (`_graph_role_model`) each **re-derive**
`_model_default`'s exact logic inline (`"opus[1m]" if role in ("root", "planter", "engineer")
else "sonnet"`) rather than importing it from `models.py`. This is NOT the harness-translation
drift DF-03 targets (`graph.py` has no `sonnet|opus|haiku|fable` collapse anywhere — it never
talks to a harness's closed enum, it only re-derives the intent default), so I did not
characterize it as "another dispatcher doing its own silent opus[1m] -> opus substitution" —
that specific pattern doesn't exist in `graph.py`. It IS a plain duplication-of-default-logic
candidate (two independent copies of `_model_default`'s two-line rule) worth a follow-up
`BRIEF-AMENDMENT`/issue to import `_model_default` from `models.py` into `graph.py` instead,
but that's a `graph.py` edit, outside my `[FILE-SCOPE]` (`must_not_touch` doesn't list it, but
`file_scope.exclusive` is `models.py` only) — not actioned here.

## Reporter

coder-W0-S4, complete. `git status`/`git diff --numstat` confirm only
`services/cli/shepherd_cli/commands/models.py` and `services/cli/tests/test_models.py` were
touched by this lane; no `git add`/`commit`/other git-write command was run (read-only
`git status`/`diff`/`rev-parse`/`check-ignore` only); no `cargo` command was run.
