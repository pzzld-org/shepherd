## CODER REPORT

- Lane: l5-harness
- Step: W0-S2 — a clean clone can spawn (DF-01)
- Skills loaded: `code-style` (Skill tool; per-language shell file absent from the global ledger — see Deviations), `shell` (resolved to `skills/context/styles/shell.md`, read directly — see Deviations)

## Files changed

- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/commands/spawn.md` (modified)
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/hooks/scripts/session_open.sh` (modified)

## LOC delta

```
 commands/spawn.md             |  1 +
 hooks/scripts/session_open.sh | 24 +++++++++++++++++++++++-
 2 files changed, 24 insertions(+), 1 deletion(-)
```
Total: +24 / -1 (well within the ~90 LOC estimate).

## Acceptance outputs

All commands actually run by me, verbatim.

### 1. Baseline (BEFORE fix) — literal acceptance command, bare scratch dir

```
$ SCRATCH=/private/tmp/.../scratchpad/df01-baseline
$ rm -rf "$SCRATCH" && mkdir -p "$SCRATCH"
$ cd "$SCRATCH" && git init -q && shctx doctor
STATUS CATEGORY  NAME                   MESSAGE
OK     bin       sqlite3                3.51.0 ...
OK     bin       jq                     jq-1.7.1-apple
OK     bin       git                    git version 2.50.1 (Apple Git-155)
OK     bin       gh                     gh version 2.97.0 (2026-07-31)
FAIL   ns        namespace dir          missing
                                          → fix: run 'shctx init' or 'shctx ready'
FAIL   ns        project.json           missing
                                          → fix: run 'shctx init'
FAIL   db        shepherd.db            missing
                                          → fix: run 'shctx init' or 'shctx ready'
OK     lock      shepherd.lock          free
WARN   config    shepherd.toml          not found at standard paths
                                          → fix: run 'shctx config init' — see docs/configuration.md

shctx doctor: 3 fail, 1 warn, 5 ok
EXIT_CODE=1
```
Confirms `test $? -ne 0` passes — current behavior fails closed. PASS (baseline reproduced).

### 2. Documented preflight text present in `commands/spawn.md`

```
$ rg -n "4b" commands/spawn.md
55:| 4b | Registry DB | Scaffold-then-proceed: `shctx init` if the registry DB is absent, emit `[REGISTRY] scaffolded`, PROCEED. Non-blocking. |
```
PASS — worded exactly parallel to Check 4's existing shape (`Scaffold-then-proceed: <cmd> if <condition>, emit <tag>, PROCEED. Non-blocking.`).

### 3. `hooks/scripts/session_open.sh` syntactically valid + invokes `shctx init` when DB absent

```
$ bash -n hooks/scripts/session_open.sh && echo "SYNTAX OK"
SYNTAX OK

$ rg -n "shctx init|\"\$sh_cli\" init" hooks/scripts/session_open.sh
71:  if [[ -x "$sh_cli" ]] && "$sh_cli" init >/dev/null 2>&1; then
72:    registry_line="[REGISTRY] scaffolded — registry DB was absent; ran 'shctx init'."
74:    registry_line="registry DB absent — run 'shctx init' to scaffold it."
```
PASS — syntactically valid, invokes `shctx init` (via `$plugin_root/bin/shepherd init`, the same absolute-path invocation pattern the existing shctx-locator/trend-probe code already uses) gated on `[[ ! -f "$db" ]]`, never a hard failure (the `else` branch just surfaces a message, exits 0 via the existing `emit_context`/`pass_silent` machinery).

### 4. Real DF-01 scenario — clean clone of THIS repo, hook fires, registry self-heals, doctor re-run

Neither `commands/spawn.md` (an LLM-consumed doc, not executable) nor `session_open.sh` (a Claude Code SessionStart hook) fire from a bare `shctx doctor` invocation in an isolated shell — so the literal re-run described in the acceptance note is exercised by simulating the actual SessionStart firing against a faithful clean-clone stand-in (a real local clone of this repo's `v6.4.5` branch, carrying the tracked `.shepherd/shepherd.toml` but — correctly — no `.shepherd/shepherd.db`, gitignored):

```
$ git clone --branch v6.4.5 /Users/jo3/src/fl03/shepherd "$SCRATCH_CLONE"
Cloning into '.../df01-clean-clone'...
done.
$ ls .shepherd/shepherd.toml   # present (tracked)
$ ls .shepherd/*.db            # absent (gitignored) — ABSENT (expected)

$ cd "$SCRATCH_CLONE" && shctx doctor      # PRE-FIX doctor, real clean-clone shape
...
FAIL   ns        project.json           missing        → fix: run 'shctx init'
FAIL   db        shepherd.db            missing        → fix: run 'shctx init' or 'shctx ready'
...
shctx doctor: 2 fail, 0 warn, 7 ok
PRE-FIX DOCTOR EXIT_CODE=1

$ echo '{}' | bash "$WORKTREE/hooks/scripts/session_open.sh"     # fire MY edited hook
{"additionalContext":"[shepherd] Session orientation:\n...
[REGISTRY] scaffolded — registry DB was absent; ran 'shctx init'.
adaptation: empty — first cycle records at CLOSE-FINALIZE via 'shctx adapt roll'.  [adaptation-loop.md]\n"}
HOOK_EXIT=0

$ ls .shepherd/ | grep -i "\.db\|project.json"
project.json
shepherd.db
shepherd.db-shm
shepherd.db-wal

$ shctx doctor      # POST-FIX doctor, same clean-clone directory, no hand-run shctx init
...
OK     ns        project.json           id=019ff88c-1eb7-7772-b2e6-f32f16598d21
OK     db        shepherd.db            1.1M
OK     db        schema_version         21
OK     db        pending migrations     none (schema at head)
...
WARN   refresh   symbols                rows=0, never refreshed   (× 5 refresh zones — unrelated to bootstrap, expected on any first run)
...
shctx doctor: 0 fail, 5 warn, 11 ok
POST-FIX DOCTOR EXIT_CODE=2
```
PASS — `0 fail` confirms the registry is bootstrapped (release-gate criterion C.1: "shctx doctor reports a bootstrapped registry"); the automatic path is `SessionStart → session_open.sh → self-heal → shctx init`, reaching `shctx init` before doctor ever reports success, with zero hand-run intervention. The remaining 5 WARNs are refresh-staleness (an orthogonal, expected first-run condition, not a registry-bootstrap failure) and exit code 2 (documented as "warnings only", never a failure).

### 5. Idempotency check (not explicitly required, run for correctness confidence)

```
$ echo '{}' | bash "$WORKTREE/hooks/scripts/session_open.sh"   # second fire, DB now present
{"additionalContext":"[shepherd] Session orientation:\n...  (no [REGISTRY] line)\nadaptation: empty ...\n"}
HOOK_EXIT=0
```
Confirms the self-heal is a no-op once the DB exists — no needless re-invocation of `shctx init` on every session open.

## Deviations

1. **`[SKILLS] shell` is not a Skill-tool-invokable skill in this install** (no `skills/shell/SKILL.md` anywhere in the plugin — only 7 top-level skills exist: `shepherd`, `bridge`, `harness`, `thinking`, `adaptation`, `motivation`, `context`). It resolves to this repo's own `skills/context/styles/shell.md` — a per-language style reference sibling to `rust.md`/`python.md`/etc., the exact pattern `code-style`'s per-language ledger uses (which itself has no `shell.md`, only `rust.md`). I read `skills/context/styles/shell.md` directly and applied its rules (`set -eu -o pipefail`... — already present in `session_open.sh`'s existing `set -euo pipefail`; quoted expansions; `[[ ]]` over `[ ]`; local naming) rather than halting `BRIEF INVALID`, since the content was genuinely present and unambiguous, just addressed via `Read` instead of the `Skill` tool. Not guessing at shell idioms — reading the authoritative, already-existing project reference.

2. **No renumbering of spawn.md's Preflight Checks 5-8.** The brief's Action 1 says "numbered after existing Check 4"; a literal positional insert-and-renumber (new check 5, old 5→6, 6→7, 7→8, 8→9) would have desynchronized external references to "Spawn Check 8" living in `skills/adaptation/SKILL.md` and `skills/context/scripts/cmd_adapt.sh` — both strictly outside `[FILE-SCOPE]` (not even in `file_scope.may_read`), so I have no path to fix them if I renumbered. This repo already has a precedent for exactly this situation: `hooks/scripts/dispatch_guard.sh`'s own internal numbering uses `Check 4`, `Check 4b`, `Check 4c` — a sub-letter suffix that inserts a related check without cascading a renumber. I used the identical idiom (`4b`) for the new "Registry DB" row, positioned immediately after Check 4 in the table (satisfying "numbered after existing Check 4" — `4b` sorts after `4`), leaving Checks 5-8 and every external reference to them untouched and correct. No `### Check 4b` detail section was added, mirroring Check 4 itself (which likewise has no expanded detail section — only Checks 0, 1, 3 do).

3. **`canonical-types.md` absent** — expected for this step (no Rust types touched; this step is bash + a markdown doc). Confirmed absent repo-wide, then proceeded per the walk-the-tree fallback in the coder protocol.

## Staged GH commands

None — no GitHub-facing text to stage for this step.

## Notes

- `hooks/scripts/session_open.sh`'s self-heal block is inserted immediately after `db="$(hook_db_path "$ns")"` and BEFORE the existing adaptation-surface block, so once the registry is scaffolded in this same hook invocation, the adaptation surface (which itself gates on `[[ -f "$db" ]]`) correctly sees the fresh (empty) registry and reports "adaptation: empty — first cycle..." rather than staying silent.
- Reused the existing `sh_cli="$plugin_root/bin/shepherd"` absolute-path-invocation idiom already established at line ~91 (trend probe) for the new self-heal block, rather than inventing a second CLI-locating convention — consistent with the file's own established pattern and `[DO-NOT-DUPLICATE]`'s spirit.
- Self-heal is strictly additive and non-blocking: on `shctx init` failure (e.g. no venv, no network for first-time dependency install), `registry_line` still gets set to a plain informational message and the hook still exits 0 via the pre-existing `emit_context`/`pass_silent` machinery — never a hard failure, matching `[NON-GOALS]`.
- No destructive/auto-repair logic was added for a *corrupt* (as opposed to *absent*) DB — `[[ ! -f "$db" ]]` only fires on absence; a corrupt DB is left entirely alone for `shctx doctor` to report, per `[NON-GOALS]`.
- Verified no stray side-effect files landed in the shared worktree (`git status --porcelain` shows only the two intended files modified; `packages/`/`package.json` untracked entries belong to sibling lane W0-S7, not touched by me). All functional verification ran in isolated scratch dirs under the session scratchpad, cleaned up afterward.

- Reporter: shepherd:coder (W0-S2) @ 2026-08-12T19:40:00Z
