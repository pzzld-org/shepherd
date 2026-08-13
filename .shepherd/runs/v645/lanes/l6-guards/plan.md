# Lane l6-guards — Make dispatch doctrine mechanical (DF-44)

**Run:** v645
**Objective:** Two dispatch rules that are written down and unenforced get a mechanical guard, and the guard that enforces them gets its first self-test. This lane exists because root violated `agents/auditor.md:92` on a live lane's wave-review gate and nothing stopped it. Prose doctrine is advisory; only what a hook denies is binding.
**Worktree:** /Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards
**Base commit:** ada05dd
**git_custody:** lane

## File scope

- Exclusive (OWNED):
  - `hooks/scripts/dispatch_guard.sh`
  - `tests/test_dispatch_guard.sh` (NEW)
  - `skills/context/scripts/cmd_teammate.sh`
- May read:
  - `agents/auditor.md`, `agents/conductor.md`, `agents/shepherd.md`
  - `hooks/hooks.json`, `hooks/scripts/*.sh` (for the emit_deny/emit_context idiom)
  - `tests/` (for the existing gate-test idiom)
  - `.shepherd/runs/v645/dogfood.md`
- MUST NOT TOUCH: `crates/**` (l1 and l2 are live in those trees), `conformance/**`

## Steps

Three steps, file-disjoint, dispatch all three as **separate `@coder`s**. Do not write any
of them yourself — that is DF-42, recorded against l2-registry this same wave.

### W2-G1 — `hooks/scripts/dispatch_guard.sh`: Checks 7 and 8

Checks 1–6 exist; append 7 and 8 using the file's existing `emit_deny` / `emit_context`
idiom and its existing session-role detection (see Check 4's teammate-session handling
around line 107 — reuse it, do not invent a second mechanism).

**Check 7 — `AUDIT-CONCERN-UNDECLARED` (deny).**
Any dispatch with `subagent_type` = `shepherd:auditor` whose `tool_input.prompt` does not
declare exactly one concern is refused.
- zero `[CONCERN]` declarations → deny, message names the required form
- two or more → deny, message says to split into N dispatches, one concern each
- exactly one → pass
The authority is `agents/auditor.md:92`: *"brief's `concern` field is authoritative —
NEVER collapse two into one report."* The deny text MUST cite that line and MUST list the
valid concern slugs it found or expected, so the fix is mechanical for the dispatcher.
Match the declaration as a line of the form `[CONCERN] <slug>`; be strict about the form
(a prose mention of the word "concern" is not a declaration) and say so in the message.

**Check 8 — `WAVE-GATE-USURPED` (deny).**
A **root-session** dispatch of `shepherd:auditor` whose prompt names a
`.worktrees/<lane>` path belonging to a lane with a **live** conductor is refused.
Wave-review belongs to the lane conductor (`agents/conductor.md §Lane walk`); root holds
the `@auditor` role grant but not another tier's gate. This is the mirror of the existing
`ROOT-INTRO-USURPED` shape one section over.
- "live" = a row in the teammate registry for that lane whose `declared_state` is
  `in-progress`. Reuse `shctx teammate liveness` or query the same DB the other hooks use;
  do not open a second code path to the registry.
- deny message routes root to the correct action: `SendMessage(to: shepherd-conductor-<lane>)`
  telling the conductor to widen its OWN review, never a second review behind it.
- **Fail-visible, not fail-open.** If the registry is unreadable or the lane cannot be
  resolved, `emit_context` a warning naming the reason and PASS. Do not silently pass and
  do not deny on an unreadable DB — a bricked dispatch path is worse than the miss. The
  warning text must make the degraded state obvious in the transcript.

Both checks land in one file, so they are ONE coder, not two. That is the counterweight's
write test (`SKILL.md §Fan-out counterweight` rule 1): file-disjointness authorizes
concurrent writes, and these two are not disjoint.

### W2-G2 — `tests/test_dispatch_guard.sh` (NEW)

`dispatch_guard.sh` is 296 lines of deny logic with **zero** tests. A checker never shown
to fail is not known to check anything.

One deliberately-broken fixture per rule, asserting the guard **DENIES** — checks 1, 2, 3,
4, 4b, 4c, 5, 7, 8 — plus at least two positive controls asserting a well-formed dispatch
PASSES (a legal `shepherd:coder` step dispatch, and a legal single-concern
`shepherd:auditor` dispatch). Feed each fixture as PreToolUse JSON on stdin and assert on
**exit code and on the halt code in stderr separately** — a test that only checks non-zero
exit passes on the wrong rule firing.

Follow the existing `tests/` idiom for gate tests and keep it in the `fast` tier: pure
stdin/stdout, no compilation, under 2s total. bash 3.2 only — no `${var,,}`, no
`declare -A`, no `mapfile` (`~/.claude/skills/shell/SKILL.md`).

**Write this step against the CONTRACT above, not against W2-G1's implementation.** The two
steps run concurrently and that is deliberate: if the test and the guard disagree, that
disagreement is the signal. Run the suite only after both coders return.

### W2-G3 — `skills/context/scripts/cmd_teammate.sh`: `status` crashes

`shctx teammate status <name>` dies with `cmd_teammate.sh: line 183: $1: unbound variable`.
The `status)` branch reads `name="$1"` after the dispatcher has already consumed the
subcommand, so `$1` is unset under `set -u`. Fix the branch, and check the sibling branches
in the same `case` for the same defect rather than patching only the reported one.

Add a regression test asserting `status` with a name returns a row and `status` with **no**
name exits non-zero with a usage message rather than a bash trace. Put it wherever the
existing `shctx` command tests live; if there is no such file, say so in your report and
put it in `tests/`.

## Acceptance

Per step, and none of these are satisfied by a command that exits 0 while printing nothing —
DF-41 was exactly that defect twice over. Read what each command actually prints.

- W2-G1: `bash -n hooks/scripts/dispatch_guard.sh` clean; shellcheck clean; each new check
  demonstrated firing by hand at least once with the fixture JSON pasted into the report.
- W2-G2: `tests/test_dispatch_guard.sh` runs green, and **every** assertion is shown to be
  load-bearing — invert one fixture per rule, confirm the suite goes red, restore. Report
  the count of rules proven able to fail. If any rule cannot be made to fail, that is a
  finding about the guard, not about the test, and it gets escalated, not worked around.
- W2-G3: the two regression assertions pass; `shctx teammate status shepherd-conductor-v645-l1-engine`
  returns JSON.
- Lane-wide: `./scripts/gate.sh fast` (or the repo's fast tier equivalent) green.

## Audit

Wave-review is split by concern — **one `[CONCERN]` per `@auditor` dispatch**, which is the
rule this lane exists to enforce, so do not violate it while landing it:

1. `[CONCERN] guard-fail-closed` — do checks 7 and 8 actually deny, and is the fail-visible
   path on an unreadable registry genuinely a warning-and-pass rather than a silent pass?
2. `[CONCERN] test-integrity` — is every assertion in the new suite load-bearing, or does
   any pass tautologically?

Two concerns, two dispatches. Not one brief with two headings.

## Do not duplicate

- `emit_deny`, `emit_context`, `pass_silent`, `json_field` already exist in
  `hooks/scripts/dispatch_guard.sh`. Use them. Do not write a second JSON field reader.
- The teammate registry already has a read path used by `teammate_idle.sh` and
  `coordinate_drive_guard.sh`. Reuse it for Check 8.
- Check 6 already handles the fan-out-vehicle flag. Checks 7 and 8 are additive; do not
  restructure 1–6.
