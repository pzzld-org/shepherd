# CODER REPORT — W0-S11 (DF-17, CRITICAL, RE-DISPATCH)

## Files changed
- `hooks/scripts/agent_invocation_tagger.sh` (modified)
- `hooks/tests/lint_agent_capabilities.sh` (modified)

No file outside `[FILE-SCOPE]` was touched. `agents/*.md` and `skills/harness/SKILL.md` were
read-only inputs. Confirmed via `git status --porcelain -- hooks/scripts/agent_invocation_tagger.sh
hooks/tests/lint_agent_capabilities.sh` (exactly these two, modified) and a broader
`git status --porcelain` scan that every other dirty/untracked path in the shared worktree belongs
to a sibling lane (`.github/workflows/*`, `commands/spawn.md`, `hooks/hooks.json`,
`hooks/scripts/_lib.sh`, `hooks/scripts/session_open.sh`, `hooks/tests/test_engineer_self_contained.sh`,
`hooks/tests/test_v644_wiring.sh`, `skills/shepherd/SKILL.md`, `.github/scripts/`, `content/`,
`hooks/scripts/plan_proof_guard.sh`, `hooks/tests/test_plan_proof_guard.sh`, `package.json`,
`packages/`) — none of it mine. `skills/harness/SKILL.md` shows as modified in the shared worktree;
that change is NOT mine (I only `Read` it) — see `## Notes`.

## LOC delta
`git diff --stat -- hooks/scripts/agent_invocation_tagger.sh hooks/tests/lint_agent_capabilities.sh`:
```
 hooks/scripts/agent_invocation_tagger.sh |  70 ++++++++++++++++-
 hooks/tests/lint_agent_capabilities.sh   | 128 ++++++++++++++++++++++++++++++-
 2 files changed, 194 insertions(+), 4 deletions(-)
```
+194 / -4 total. The brief's LOC budget (~130) is an estimate for shell, and this is shell, not
Rust — `loc-count.py`'s ONE-LOC rule is scoped to `*.rs` production lines by construction and does
not apply to `.sh` files at all (confirmed: invoking it against these two files errors out looking
for a `*.rs` pathspec). I'm reporting the actual number rather than trimming to force-fit the
estimate or adjudicating whether being over it is acceptable — that adjudication is the
dispatcher's per `LOC-BUDGET-GOVERNANCE`, never mine. The size is the honest cost of the two
`[ACTIONS]` items 1+2 (a written record schema + doc, and a reusable detector + `--self-test` +
scan loop + two summary-string updates) — both mandated, neither cuttable.

## Acceptance outputs
All three commands run from the worktree root (`/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness`),
verbatim stdout + exit code, captured on the final version of the file (re-run fresh, not reused
from an earlier iteration):

```
$ bash hooks/tests/lint_agent_capabilities.sh
  OBSERVED-CAPABILITY (DF-17): 0 dispatch record(s) under /Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/.shepherd carry a self-reported observed_tools list yet — expected until a future wave wires a role's own runtime tool-presence probe to self-report (agent_invocation_tagger.sh already records the declared half + a self-report-pending placeholder at every dispatch)
lint_agent_capabilities: OK — read-only trio mutation-free (GH #74); all nine carry no destructive MCP verb (GH #84); all three leads (shepherd/engineer/conductor) grant Workflow in-tree (#233, live on an Agent-Teams teammate substrate — #263); read-only shctx-runners grant Bash; no profile claims an ungranted tool (v6.2.1); NO frontmatter names a provider-specific MCP token — capabilities are discovered via ToolSearch (v6.4.3, #110); DF-17 observed-vs-declared capability scan ran (0 record(s), 0 delta(s), non-fatal)
(exit code: 0)

$ bash hooks/tests/lint_agent_capabilities.sh --self-test
  SELF-TEST (DF-17): fabricating a role that declares 'Glob' but whose observed set omits it
  SELF-TEST OK — the injected delta WAS detected:
    FINDING fixture-role: declares 'Glob' but it is not present in the runtime-observed tool list (declared != observed, DF-17)
lint_agent_capabilities --self-test: exiting 1 deliberately — this is the proof the detector CAN fail, not a normal-run failure
(exit code: 1)

$ rg -q 'observed|runtime' hooks/tests/lint_agent_capabilities.sh
(exit code: 0)
```

All three PASS: (1) the extended lint still exits 0 on the real tree; (2) `--self-test` proves
the detector genuinely fires (fabricates a `Glob` delta, detects it, and deliberately exits 1 as
the proof — not a normal-run failure); (3) the script's own text carries both `observed` and
`runtime`.

Beyond the three mandated commands, I additionally verified the mechanism end-to-end against a
real, non-synthetic scenario — a fixture dispatch record shaped exactly like DF-17's own cited
evidence (`agent_role: "engineer"`, `declared_tools` including `Workflow`/`Glob`/`Grep`,
`observed_tools` missing them), pointed at via `SHEPHERD_LINT_RUNS_DIR`:
```
$ SHEPHERD_LINT_RUNS_DIR=<fixture dir> bash hooks/tests/lint_agent_capabilities.sh
  FINDING (<fixture>/dispatch/testsprint/fx1.json):
    FINDING engineer: declares 'Workflow' but it is not present in the runtime-observed tool list (declared != observed, DF-17)
    FINDING engineer: declares 'Glob' but it is not present in the runtime-observed tool list (declared != observed, DF-17)
    FINDING engineer: declares 'Grep' but it is not present in the runtime-observed tool list (declared != observed, DF-17)
  OBSERVED-CAPABILITY (DF-17): scanned 1 dispatch record(s) with self-reported data, found 1 declared-vs-observed delta(s) — reported as findings above, non-fatal
lint_agent_capabilities: OK ... DF-17 observed-vs-declared capability scan ran (1 record(s), 1 delta(s), non-fatal)
(exit code: 0)
```
This proves the full pipeline (record on disk → declared/observed diff → FINDING, non-fatal) works
for real data, not only for the in-process `--self-test` shortcut.

I also smoke-tested `agent_invocation_tagger.sh` directly (fabricated `PreToolUse` JSON on stdin,
both a known role (`coder`) and an `unknown` role) and confirmed the written record for `coder`
carries `"declared_tools": ["Bash","Edit","Glob","Grep","Read","Skill","ToolSearch","Write"]` —
byte-for-byte the same 8 tokens as `agents/coder.md`'s real `tools:` line — and the `unknown`-role
case degrades cleanly to `"declared_tools": [], "declared_source": "role-unresolved"` with no
error and no non-zero exit, preserving the hook's "never blocks; pure side-effect" contract. Both
the jq path and the python3 fallback path were exercised. Test artifacts were removed afterward
(`.shepherd/dispatch/**` is gitignored by `.shepherd/.gitignore` regardless, so nothing could have
leaked into the diff).

## Deviations
None from `[ACTIONS]`. One correctness fix caught in testing, not a deviation from the brief:
`agent_invocation_tagger.sh` runs under `set -eu -o pipefail`. My first draft of the new
`declared_tools_csv()` helper ended its pipeline in `grep -v '^$' | paste -sd, -`; when a role has
no `tools:` line (e.g. `unknown`), `grep` exits 1 on the empty match, and under `pipefail` that
propagates through the plain (non-`local`) assignment `declared_csv="$(declared_tools_csv ...)"` —
`set -e` treats that assignment's failing exit status as the whole script's, silently killing the
hook before it wrote *any* record, for every unknown-role dispatch. I found this by tracing the
smoke test (`bash -x`), not by inspection, and fixed it by appending `|| true` inside the helper
(mirroring the file's own established pattern, e.g. line 79's
`... | sed 's/^# @//' || true` for the identical reason). Verified the fix directly: the
`unknown`-role smoke test now writes a clean record every time.

## Staged GH commands
None. This step required no `gh` write and no git write of any kind (per `[PROTOCOL-REMINDERS]`,
custody of staging/committing these two files belongs to the dispatcher, not me).

## Notes

**What "observed" means in a script context, and the boundary of what I could build here (per
`[ACTIONS]` 1's explicit ask).** A `PreToolUse(Agent|Task)` hook — `agent_invocation_tagger.sh` —
fires *before* the dispatched role's own session exists. It has no live introspection API to call;
nothing running as a static shell script does (confirmed by grepping the codebase — the only
precedent, `shepherd_mcp_available()` in `_lib.sh`, probes an *external* MCP server over the
`claude` CLI, not a session's own tool list, and even that comment explicitly says "no per-session
tool manifest — no such file/env var exists, checked live, v6.4.5"). So "observed" from a script's
vantage point can only ever mean one of two things: (a) a maintained, hand-curated table of
facts measured by a human/agent reading real transcripts, or (b) a schema + convention that lets
the *actual* dispatched session (the only party with real introspection, per
`skills/harness/SKILL.md §Tool presence`: "The agent itself, not any hook, is the authoritative
check") write its own finding back later. I deliberately built (b), not (a): hardcoding a table
like `engineer: absent Workflow,Glob,Grep` sourced from the brief's evidence blurb risked baking in
a stale or substrate-conditional fact as permanent truth — `skills/harness/SKILL.md`'s own
`#263`-era doctrine treats `Workflow` presence as SUBSTRATE-conditional (present on a live
Agent-Teams teammate substrate, absent on an Agent-tool subagent substrate), so a flat "engineer
never sees Workflow" constant would be actively WRONG on one of the two substrates and would fight
the very doctrine it's citing. Design (b) instead: `agent_invocation_tagger.sh` now writes
`declared_tools`/`declared_source` (derived exactly as this lint already derives them — same
`tools:`-line parse) plus an explicit `observed_tools: null, observed_at: null, observed_source:
"self-report-pending"` placeholder at every dispatch, and `lint_agent_capabilities.sh` reads
whatever `observed_tools` any record on disk actually carries and diffs it. Today that is
zero records everywhere (verified against both this worktree and, structurally, the empty
`.shepherd/runs/v645/dispatch/` tree in the main repo) — an honest, correctly-non-fatal "no data
yet" state that itself restates DF-17's finding as a live, checkable fact instead of prose.

**The concrete next gap, explicitly out of my `[FILE-SCOPE]`.** Wiring an actual self-report needs
one more piece I could not build here: `agents/*.md` is read-only in this step, so I could not add
the instruction telling a dispatched role to run its own tool-presence probe (the
`WORKFLOW-VEHICLE-PROBE`-style check `skills/harness/SKILL.md` already mandates for the `Workflow`
token specifically) and then PATCH its own capability record. I designed the record to be
addressable for that: I added a `session_id` field (from the hook's own `PreToolUse` input) as the
intended lookup key, and documented in the file header exactly why `tool_use_id` — the record's own
filename key — is NOT viable for this: that identifier is never surfaced back into the dispatched
session's own context, so the session has no way to find "its own" record by that key. Whether a
running session can reliably read back its own `session_id` from within its own context is itself
an unverified-capability question in the same DF-17 family — I did not assume an answer, only
built the addressing convention so a future wave can test it. This is a `BRIEF-AMENDMENT`-shaped
follow-up (touches `agents/*.md`), not something I attempted to close.

**`skills/harness/SKILL.md` doc edit — deferred as instructed, and apparently already in flight.**
Per `[ACTIONS]` 3 I checked whether `skills/harness/SKILL.md` needs a new section documenting
"`tools:` is declared intent, not a runtime guarantee, and roles must probe" before touching it —
it is outside my `file_scope.exclusive` regardless, so I did not edit it either way. Concretely,
the edit I would have proposed: a short passage under `## Tool presence` stating plainly that
*any* role's `tools:` frontmatter (not only the `Workflow` token this section currently covers)
is DECLARED intent, cross-referencing the new `declared_tools`/`observed_tools` record schema in
`agent_invocation_tagger.sh` as the mechanical detector. While working this step I observed
`skills/harness/SKILL.md` change under me in the shared worktree (I did not author this — confirmed
via `git diff`, my only interaction with the file was `Read`): a new "DF-E1 — `tools:` frontmatter
is not authoritative, measured live (this sprint)" section landed, generalizing the exact
`Workflow`/`Glob`/`Grep`-for-engineer evidence this brief also cites, with a `WORKFLOW-VEHICLE-PROBE`-first
directive. That appears to be a concurrent process (plausibly the conductor or another live wave)
already closing the doc gap I would otherwise have flagged — I'm reporting it as an observation,
not claiming credit, and not filing a duplicate `BRIEF-AMENDMENT` for work that looks already done.
Worth a conductor sanity check at wave-review: confirm that landed text also references this step's
`declared_tools`/`observed_tools` record convention as the *mechanical* enforcement, since prose-only
doctrine is exactly the failure mode DF-17 is about.

**`[SKILLS]` correction confirmed working as intended.** The re-dispatch's stated fix — dropping
the erroneous `shell` entry, keeping only `code-style` — worked cleanly this run: `code-style`'s own
`SKILL.md` explicitly instructs "If no file exists for the language, apply the shared principles
below and note the gap" when no per-language file exists (confirmed: `~/.claude/skills/code-style/`
contains only `rust.md`, no `shell.md`), so I followed the shared principles (truth over politeness,
delete-don't-comment-out, explain the why) rather than halting a second time on an already-diagnosed
issue. Flagging only as a genuine gap for the operator, not a blocker: Joe may want a
`code-style/shell.md` eventually, matching the `rust.md` ledger for the same bash-3.2-heavy hooks
codebase this repo leans on constantly.

**Bash 3.2 portability caught one real bug beyond the `set -e`/pipefail one above.** My first draft
of the observed-vs-declared scan loop in `lint_agent_capabilities.sh` used a `shopt -s nullglob`
array (`capability_records=(...)`); under this repo's target shell — macOS's system `/bin/bash`
3.2.57, per `[USER-STYLE]` — an array that glob-expands to zero elements is genuinely unset for
`"${arr[@]}"` purposes, and `set -u` (which this file carries) turned that into a hard
`unbound variable` failure on every clean run (caught immediately by actually running the
acceptance command, not by inspection). Replaced with the `find | while read` idiom this codebase
already uses elsewhere (`_lib.sh`'s `cfg_get()`), which is bash-3.2-safe and, as a bonus, is a
single pattern (`-path '*/dispatch/*/*.json'`) that covers both dispatch-directory conventions this
codebase actually uses (`<ns>/dispatch/<sprint>/*.json` when `SHEPHERD_WORKDIR` is unset, and
`<ns>/runs/<run>/dispatch/<sprint>/*.json` when it points at a run-scoped namespace) without
needing two separate glob patterns.

## Reporter
coder-v645-l5-harness-W0-S11 @ 2026-08-13T00:55:00Z
