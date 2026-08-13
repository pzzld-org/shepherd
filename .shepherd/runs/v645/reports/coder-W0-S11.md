# CODER REPORT — W0-S11

- Lane: l5-harness
- Skills loaded: code-style (SKILL.md; per-language files present: rust.md only — no shell.md exists)
- Halt: **BRIEF INVALID** — skill `shell` listed in `[SKILLS]` not found

## Files changed

None. Halted at Step 1 (Load skills) of the mandatory Startup Protocol, before the Step 0
brief-shape check completed and before any read/write inside `[FILE-SCOPE]`. Per
`agents/coder.md`: "you MUST NOT write code before Steps 0-3 of the Startup Protocol
complete. Stop — do not partial-execute on a malformed brief."

## LOC delta

+0 / -0

## Acceptance outputs

NOT RUN. The brief's `[ACCEPTANCE]` commands (`bash hooks/tests/lint_agent_capabilities.sh`,
`--self-test`, and the `rg -q 'observed|runtime'` grep) exercise the fix this step is meant
to produce. Producing that fix requires completing the Startup Protocol first, which halted
at the skill-load gate (Step 1) — before Step 0.5's worktree/base-commit check even runs in
the mandated order. Running the acceptance commands now would only reproduce the pre-existing
(stale) state of `hooks/tests/lint_agent_capabilities.sh`, which is not a valid acceptance
signal for work not yet done, and running them is not itself a git/cargo write so it is
technically permitted — but doing so here would misrepresent verification of code I did not
write.

For traceability, the verification commands I actually ran (read-only, no writes):

```
$ cd /Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness && git rev-parse HEAD && pwd
5be42280615c8dc5321061798240f476dffed645
/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness
```
→ matches `[BASE-COMMIT-EXPECTED]` exactly and `pwd` matches `[WORKTREE].Path`. Step 0.5
would have PASSED had Step 1 cleared first (order is documented as Step 1 before Step 0.5 in
`agents/coder.md §Startup Protocol`; I ran this check regardless, out of order, purely to
confirm the worktree itself was not the problem before concluding the halt is skill-related).

```
$ (Skill tool) skill: code-style, args: shell
```
→ loaded `code-style/SKILL.md` successfully. It documents its own directory contents
verbatim: only `rust.md` and `python.md` (scaffolded) exist as per-language files — no
`shell.md`. Its own text: "If no file exists for the language, apply the shared principles
below and note the gap."

```
$ (Skill tool) skill: shell
Unknown skill: shell. Did you mean help?
```
→ confirms `shell` is not a registered/invokable skill via the Skill tool — the only
authoritative runtime oracle for "is this skill installed."

```
$ (Skill tool) skill: bash
Unknown skill: bash. Did you mean batch?
```
→ confirmed no alternate slug (`bash`) resolves either, ruling out a naming mismatch.

```
$ find /Users/jo3/.claude/skills -maxdepth 1 -type d | sort
```
→ 23 entries (agents-sdk, cloudflare*, code-style, context7-mcp, durable-objects,
polymarket, questdb, rust, sandbox-sdk, sentry-cli, trader, turnstile-spin, typing,
wasmtime, web-perf, webassembly, workers-best-practices, workflow, wrangler, .archive).
No `shell` entry.

```
$ find /Users/jo3/.claude/plugins/cache/shepherd -maxdepth 6 -type d -iname "*shell*"
$ find /Users/jo3/.claude/plugins/cache/shepherd/shepherd/6.4.4/skills -maxdepth 1 -type d
```
→ Only hit for `*shell*` is `.shepherd/profiles/shell` (a shepherd **profile** artifact, not
a Skill-tool-invokable skill). The plugin's actual `skills/` directory contains exactly
`adaptation, bridge, context, harness, motivation, shepherd, thinking` — matching this
project's own `skills/` directory 1:1. No `shell` skill.

```
$ find /Users/jo3/.claude/plugins/marketplaces -type d -iname "shell"
```
→ 1 hit: `/Users/jo3/.claude/plugins/marketplaces/shepherd/.shepherd/profiles/shell` — same
profile artifact, not a skill.

## Deviations

**HALT — BRIEF INVALID.** `[SKILLS]` for this dispatch reads `code-style, shell`.
`agents/coder.md §Skills to load` is unambiguous: "Listed skill not installed → halt
`BRIEF INVALID — skill \`<slug>\` listed in [SKILLS] not found. Halting.`" I verified across
every place a skill could be registered (user-level `~/.claude/skills/`, every cached plugin
under `~/.claude/plugins/cache/**`, this project's own `skills/` directory, every marketplace
cache, and two direct `Skill(skill=...)` invocations for both `shell` and `bash`) and `shell`
does not exist anywhere as an installed, invokable skill. `code-style` itself only carries a
`rust.md` per-language file — no `shell.md` — so there is no fallback language-idiom
reference for `.sh` files in this environment today.

This is the **identical gap** the sibling coder for step W0-S6 (same lane `l5-harness`, same
run `v645`) already hit and halted on — see
`/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/coder-W0-S6.md`, which reports the
same `[SKILLS] = code-style, shell` dispatch, the same missing-`shell` finding, and the same
halt code. Since W0-S11's brief also targets bash scripts
(`hooks/tests/lint_agent_capabilities.sh`, `hooks/scripts/agent_invocation_tagger.sh`) under
the same `[SKILLS] = code-style, shell` computation, the gap reproduces exactly. This is a
conductor-side skill-registration gap — not something resolvable by substitution or by
silently proceeding on `code-style` + general shell knowledge alone. `agents/coder.md` is
explicit: "load every entry, never substitute." Per the brief's own `[DOCTRINES]` clause for
this dispatch — "an unverified capability CLAIM ... must be checked by a script, not trusted
as prose" — I verified via the Skill tool itself (the deterministic oracle) rather than
assuming `shell` existed because it sounds plausible, and it does not.

I am halting before touching `hooks/tests/lint_agent_capabilities.sh` or
`hooks/scripts/agent_invocation_tagger.sh`.

Two ways to unblock, for the dispatcher to choose (not mine to adjudicate):
1. Register/author a `shell` language-mastery skill (mirroring how `rust` backs `.rs` work)
   and re-dispatch — the durable fix, given this repo's `hooks/scripts/*.sh` and
   `hooks/tests/*.sh` surface is large (already two steps in this single wave — W0-S6 and
   W0-S11 — dispatched against bash files with this same unmet `[SKILLS]` entry) and will
   recur every time a shell-scoped step is dispatched.
2. Amend `[SKILLS]` for this step (and W0-S6, and any other bash-scoped step in this wave)
   to drop `shell` and explicitly declare `code-style` (whose shared principles + this
   brief's own `[USER-STYLE]` clause, which already states bash 3.2 compatibility
   requirements verbatim) as sufficient, then re-dispatch with that correction on record.

No code was written under either path until re-dispatch; nothing in `[FILE-SCOPE]`
(`hooks/tests/lint_agent_capabilities.sh`, `hooks/scripts/agent_invocation_tagger.sh`) was
read or modified beyond the read-only existence/registration checks documented above.

## Staged GH commands

None.

## Notes

- The substance of the requested fix is understood and ready to execute the moment this gate
  clears: (1) design a simple observed-tools record convention — one text/JSON file per role
  invocation under a run-scoped directory (e.g. `.shepherd/runs/<run>/capabilities/<role>-<step>.observed`)
  that a script can populate today with a documented "static-script proxy" list (what tools
  *this* bash context can exercise, explicitly caveated as NOT the same oracle as a live
  dispatched agent) and that a future live-dispatched role could self-report into using the
  same file convention/schema; (2) extend `hooks/tests/lint_agent_capabilities.sh` in place
  (no new file — confirmed via `rg -n 'need .*tools:' hooks/tests/` returning nothing extra
  to duplicate) to diff each `agents/*.md` frontmatter `tools:` declaration against that
  role's observed-record file, reporting deltas as findings/warnings rather than a hard grep
  pass/fail, while preserving exit-0 on a clean/no-observed-record run (backward compatible)
  and adding a `--self-test` mode that seeds a synthetic fixture with a deliberately-missing
  observed tool and asserts the script detects and fails on it; (3) grep confirms
  `skills/harness/SKILL.md` already exists and is in `may_read` only — I did not open it in
  this halted run, so I cannot yet state whether it needs a new section; that determination
  is deferred to the re-dispatched run since it depends on Step 2/3 (CONTEXT-INVENTORY +
  DO-NOT-DUPLICATE greps) which I did not reach.
- I did not touch any file outside `[FILE-SCOPE]`, ran no git write commands, and ran no
  cargo/build commands (consistent with this step's "no cargo invocation" instruction).
- Cross-reference for the dispatcher: this is the second coder in lane `l5-harness`, wave W0,
  to independently hit and report this exact `shell`-skill-not-found gap (W0-S6 and now
  W0-S11). A single `[SKILLS]` amendment or skill registration would very likely unblock both
  (and any other bash-scoped step in this wave) in one shot rather than requiring N separate
  re-dispatches.
- Reporter: shepherd-conductor-v645-l5-harness (acting as @coder per dispatched `[ROLE]`) @ 2026-08-13T00:33:11Z
