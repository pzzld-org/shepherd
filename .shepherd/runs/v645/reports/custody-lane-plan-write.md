---
title: Empirical probe — teammate-conductor lane-plan write exemption
date: 2026-08-13
auditor: shepherd:auditor (custody probe, ad-hoc empirical mode)
sprint: v6.4.5
concern: custody / write-guard boundary (conductor_write_guard.sh lane-plan exemption)
mode: empirical-probe (direct instruction-driven falsification task, not close/regression/carry-forward)
methodology: superpowers:systematic-debugging Phase 1 — instrument the guard's own decision boundary directly with a synthetic harness on both sides of the boundary, per DF-68 falsifiability rule (positive + negative control from the SAME instrument for every claim)
claim_under_test: "agents/conductor.md:160 — 'Exempt: your OWN {run_dir}/lanes/{lane}/ — the guard allows lane-plan custody writes there ... every other artifact write stays denied.'"
---

## Answer, up front

**The exemption works exactly as declared.** `hooks/scripts/conductor_write_guard.sh` was run directly, unmodified, at its real repo path, six times, with synthetic PreToolUse(Edit|Write) payloads shaped exactly like `hooks.json`'s wiring delivers them. A write to the session's OWN `runs/{run}/lanes/{lane}/` path passes silently (no `permissionDecision`); a write to the run's master `plan.md`, to a `reports/` file, to a lane-shaped path from a session with no teammate marker, and to a *different* lane's dir all come back `permissionDecision: deny`. Every invocation's own process exit code was `0` in all six cases — **the guard never fails-open or fails-closed via exit code; the allow/deny decision travels exclusively through the JSON on stdout** (empty stdout = no opinion/pass, `{"permissionDecision":"deny",...}` = blocked). This is a Claude Code hook-contract property, not a defect.

It does NOT fail open (it does not allow everything) and it does NOT fail closed on the lane plan (it does not deny the lane plan too). The guard runs for teammates — this is not a "decorative" no-op: architecturally it is wired into the SAME global `hooks.json` PreToolUse(Write)/PreToolUse(Edit) matchers as every other guard, no role-specific gating; and empirically, the live sprint's own `teammates` registry row for this exact session (`session-584d4292…`, `.shepherd/shepherd.db`) shows `last_seen_at` advancing past `spawned_at` by ~36 minutes — proof positive that PreToolUse hooks are firing on tool calls from inside this dispatched (teammate-tier) session, right now, in this sprint, not merely by design intent.

**Secondary, unplanned finding, HIGH confidence:** while trying to get a second independent confirmation via the guard's own event log (it tags the exemption `"lane-custody-exempt"` at `_lib.sh` call site), I found the entire hooks JSONL audit trail (`<ns>/logs/hooks/*.jsonl`) is silently broken by a bash parameter-expansion bug in `log_event()` (`hooks/scripts/_lib.sh:500`), and confirmed the same breakage live in this repo's own `.shepherd/logs/hooks/2026-08-12.jsonl` and `2026-08-13.jsonl` (both 0 bytes despite an active sprint). This does not change the answer above (the guard's *decision* is sound — I verified it directly on stdout, not through the log) but it does mean nobody can currently use the hooks event log to retrospectively confirm *why* a decision fired. See Finding 4.

## Instrument

- Guard: `/Users/jo3/src/fl03/shepherd/hooks/scripts/conductor_write_guard.sh` (run unmodified, at its real path, sourcing its real `_lib.sh`).
- Wiring confirmed in `hooks/hooks.json`: registered under `PreToolUse` matchers `"Write"` (line 86) and `"Edit"` (line 111), receiving `{session_id, tool_name, tool_input.file_path, tool_use_id}` on stdin per the script's own header contract (lines 26–27).
- Decision mechanics read from source (`hooks/scripts/conductor_write_guard.sh:70–154`):
  1. `is_shepherd_project` gate (namespace `shepherd.toml` or legacy `.claude/shepherd.toml`) — else silent `exit 0`.
  2. Leg 1 — `current_role` must resolve `"conductor"` (i.e. NOT a tagged flock dispatch) — else silent `exit 0`.
  3. Leg 2 — a sprint must be "open": HEAD matches `v{X}.{Y}.{Z}-dev.{N}`, OR the session is a registered non-retired/non-crashed teammate row in sqlite — else silent `exit 0`.
  4. For `Edit`/`Write`: read `session_tier_marker()` (`<ns>/tmp/session-tier-<session>`, stamped by `user_prompt_submit.sh` at teammate boot — verified its real production shape at `hooks/scripts/user_prompt_submit.sh:58–64`, `{"tier":"teammate","dispatcher":...,"lane_plan":...,"stamped_at":...}`). Extract `.lane_plan`, regex out the `runs/<run>/lanes/<lane>` segment, and if the target `file_path` contains `/<that segment>/`, `pass_silent(...)` with the tag `"lane-custody-exempt"` (lines 128–139). Otherwise fall through to `emit_deny(...)` (lines 141–153).
  5. For `Bash`: separate deny-list, not exercised in this probe (task scope is Write/Edit).

## Harness (throwaway, scratchpad-only)

Built per instructions under `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-probe/` — never inside `/Users/jo3/src/fl03/shepherd`:

- `fakerepo/`: fresh `git init`, one commit, checked out to branch `v6.4.5-dev.1` (satisfies Leg 2's regex directly, no sqlite teammate-row dependency needed).
- `fakerepo/.shepherd/shepherd.toml`: empty file (satisfies `is_shepherd_project`).
- `fakerepo/.shepherd/tmp/session-tier-sess-custody-probe-1`: `{"tier":"teammate","lane_plan":".shepherd/runs/v645/lanes/l7-custody/plan.md"}` — matches the real marker's field shape exactly (verified against `user_prompt_submit.sh` above).
- The real guard script was invoked with `cd fakerepo && "$GUARD" < payload.json > out.stdout 2> out.stderr; echo $? > out.exitcode` for each payload — one file per stream, exit code read immediately after the command with no intervening pipe (per DF-68).

## Payloads and results (six invocations, same script, same repo, same branch, same session unless noted)

| # | tool | file_path | session has marker? | marker's OWN lane | own exit code | stdout | verdict |
|---|---|---|---|---|---|---|---|
| A | Write | `.shepherd/runs/v645/lanes/l7-custody/plan.md` (IN own lane) | yes (`l7-custody`) | `l7-custody` | `0` | *(empty)* | **ALLOW** (silent pass) |
| D | Edit | `.shepherd/runs/v645/lanes/l7-custody/plan.md` (IN own lane) | yes (`l7-custody`) | `l7-custody` | `0` | *(empty)* | **ALLOW** (silent pass) |
| B | Write | `.shepherd/runs/v645/plan.md` (master plan, OUTSIDE lanes/) | yes (`l7-custody`) | `l7-custody` | `0` | `{"permissionDecision":"deny","message":"[shepherd] CONDUCTOR-WRITE-DENIED …"}` | **DENY** |
| C | Write | `.shepherd/runs/v645/reports/custody-lane-plan-write.md` | yes (`l7-custody`) | `l7-custody` | `0` | `{"permissionDecision":"deny","message":"[shepherd] CONDUCTOR-WRITE-DENIED …"}` | **DENY** |
| E | Write | `.shepherd/runs/v645/lanes/l7-custody/plan.md` (lane-shaped path) | **no marker at all** (SOLO-like) | n/a | `0` | `{"permissionDecision":"deny","message":"[shepherd] CONDUCTOR-WRITE-DENIED …"}` | **DENY** |
| F | Write | `.shepherd/runs/v645/lanes/l3-other/plan.md` (a DIFFERENT lane) | yes (`l7-custody`) | `l7-custody` | `0` | `{"permissionDecision":"deny","message":"[shepherd] CONDUCTOR-WRITE-DENIED …"}` | **DENY** |

Full verbatim stdout for B (identical shape for C/E/F, only `Target` differs):

```
{"permissionDecision":"deny","message":"[shepherd] CONDUCTOR-WRITE-DENIED — conductor is read+dispatch only (v6.2.7).\n  Tool       : Write\n  Target     : .shepherd/runs/v645/plan.md\nThe conductor never Edits or Writes a file OUTSIDE its own lane dir. The one\ncarve-out (v6.4.1): a teammate-conductor owns runs/{run}/lanes/{lane}/ — its\nlane plan's checkboxes + '## Deviations' log (agents/conductor.md §Lane-plan\ncustody). For anything else, compose the exact content in your own reasoning\nand hand it to a @worker dispatch as a deterministic write-brief (exact path +\nexact content); read the worker's report back. The conductor's ONLY direct\nexternal mutation is opening/closing GitHub issues via\nmcp__plugin_github_github__issue_write. See agents/conductor.md\n§Hard prohibitions + §Side-effect boundary."}
```

stderr was empty for all six invocations; exit code was `0` for all six (verified via `echo "$?" > file` immediately after each guard invocation, one file per invocation — never through a pipe, per the DF-68 instruction).

## PROBE-FALSIFIABILITY — positive control stated explicitly

Per the binding DF-68 rule: every "denied" reported above (B, C, E, F) is paired with an "allowed" from the identical instrument (A, D), and vice versa. Specifically:

- A and B/C used the **exact same** session id, marker file, repo, branch, and tool (`Write`) — the only variable that changed was `file_path` (in-lane vs out-of-lane). Output flipped from silent-empty to explicit-deny-JSON solely as a function of that one variable, which is precisely the discriminator the exemption code (`conductor_write_guard.sh:128–139`) branches on. This rules out "the guard silently no-oped before reaching the Edit/Write logic at all" (e.g. an `is_shepherd_project`/Leg-1/Leg-2 early bail-out) as the explanation for A's silence — those early-exit checks (lines 78, 83–84, 93, 110) do not depend on `file_path`, so if they were the cause of A's silence, B would have been silent too. It was not.
- E (no marker) vs A (marker present) isolates the marker itself as necessary: same lane-shaped `file_path`, same repo/branch, only the presence/absence of the session-tier marker changed, and the result flipped from allow to deny. This falsifies "any lane-shaped path is allowed regardless of identity."
- F (marker present, but pointed at `l7-custody` while the write targets `l3-other`) isolates that the match is scoped to the session's OWN recorded lane, not lane-shaped paths in general. This falsifies "the exemption is a broad `lanes/**` allow."

No leg of this claim rests on a single-sided (allow-only or deny-only) observation.

## Findings

**Finding 1 — the declared exemption is real and precisely scoped (not fail-open, not fail-closed).**
- Hypothesis: `conductor_write_guard.sh` implements the lane-plan custody carve-out described at `agents/conductor.md:160` exactly — allow only inside the session's own recorded lane dir, deny everything else including the master plan, reports/, other lanes, and lane-shaped paths with no teammate identity.
- Falsification: six controlled invocations of the real script (table above) — 2 allows (A, D; both inside-own-lane, Write and Edit) and 4 denies (B: master plan.md, C: reports/, E: no-marker on a lane-shaped path, F: a sibling lane), differential-isolated per DF-68 above. Result: hypothesis holds in all 6 cases; not falsified.
- Confidence: HIGH (structurally verified — direct execution of the real, unmodified guard binary with the real `hooks.json` payload shape).

**Finding 2 — the guard runs for teammate sessions; the exemption mechanism is not decorative.**
- Hypothesis: `conductor_write_guard.sh` is actually invoked by the Claude Code harness inside a live teammate-tier session (not merely present in `hooks.json` but never triggered for that session type).
- Falsification: (a) `hooks.json` registers the guard under the global, role-agnostic `PreToolUse` matchers `"Write"`/`"Edit"` (lines 61–114) — no role-scoping exists in the wiring for ANY hook to exclude teammate sessions. (b) `teammate_heartbeat.sh` is a sibling hook under the SAME `PreToolUse` wiring, explicitly built and documented (`hooks/scripts/teammate_heartbeat.sh:2–25`) on the premise "fires on every tool call" inside a registered teammate to solve issue #193 (stall-guards false-firing). (c) Live field evidence, read-only query against `/Users/jo3/src/fl03/shepherd/.shepherd/shepherd.db`: `teammates` rows for `session-584d4292…` (this dispatched session's own id prefix) show `last_seen_at` advanced past `spawned_at` by up to 2,188,000 ms (~36 minutes) — i.e., the heartbeat hook has been firing repeatedly on this exact session's tool calls, in this exact live sprint, right now.
- Confidence: HIGH for "PreToolUse hooks fire in teammate-tier sessions in this sprint" (direct field evidence via (c), cross-checked with two independent lines: source-wiring (a) and a sibling hook's documented+operational premise (b)). MEDIUM-HIGH specifically for "conductor_write_guard.sh itself fires end-to-end inside a genuine Agent-Teams `Write`/`Edit` call" — I could not spawn a live in-process teammate from within this read-only auditor context to fire a real Edit/Write and watch the guard intercept it; that gap is closed by direct source execution (Finding 1) plus the same-matcher-list wiring, not by an end-to-end platform-level fire. Flagged in Open questions.

**Finding 3 — exit code carries no decision information; the discriminator is stdout JSON only.**
- Hypothesis: the guard signals allow/deny via its own process exit code, not solely via the `permissionDecision` field.
- Falsification: all 6 invocations (2 allow, 4 deny) returned exit code `0`. Falsified — the hypothesis is wrong; exit code is uniformly `0` and carries no signal. `emit_deny()` and `pass_silent()` (`_lib.sh:466–479`) both explicitly `exit 0` after doing their respective emission (or non-emission). This is consistent with the Claude Code hook JSON-contract convention documented in the script's own header (lines 27–31).
- Confidence: HIGH (directly observed, 6/6, no exceptions).

**Finding 4 (secondary, unplanned) — the hooks JSONL audit trail is silently and totally broken, live, in this repo, right now.**
- Hypothesis: `log_event()` in `hooks/scripts/_lib.sh` fails to append entries whenever it is called with a non-empty `fields_json` argument — which is every real call site (`emit_deny`, `emit_context`, `pass_silent` with an explicit fields payload, and even `pass_silent`'s own correctly-escaped `"{}"` default) — because of a bash parameter-expansion defect at `_lib.sh:500`: `--argjson fields "${fields_json:-{}}"`. Bash's parser closes the `${...}` construct at the FIRST unescaped `}` inside the default word `{}`, leaving a stray literal `}` appended after the substituted value whenever `fields_json` is non-empty. The correct, escaped form is used one line above at the parameter DEFAULT (`fields_json="${6:-{\}}"`, line 488) but NOT reused at the call site.
- Falsification (multi-layer):
  1. Isolated bash test: `fields_json='{"note":"manual-test"}'; echo "${fields_json:-{}}"` → `{"note":"manual-test"}}` (stray trailing `}`, invalid JSON). Confirmed deterministic across all non-empty inputs including the function's own default value `"{}"` (→ `"{}}"`).
  2. `jq -cn --argjson fields "${fields_json:-{}}" '$fields'` on that malformed string → `jq: invalid JSON text passed to --argjson`, exit code `2`; the surrounding call site swallows this via `2>/dev/null || true` (`_lib.sh:502`), so the failure is completely silent and the `>> "$log_file"` append is a no-op (jq produced no stdout to redirect).
  3. Same defect reproduced against the guard's actual runtime: ran `conductor_write_guard.sh` for payloads A–F in the scratchpad fakerepo; `fakerepo/.shepherd/logs/hooks/2026-08-13.jsonl` exists (created by `mkdir -p`) but is 0 bytes despite 4 `pass_silent`/`emit_deny` calls that should each have logged a line.
  4. Field corroboration in the REAL repo (read-only, no writes made): `/Users/jo3/src/fl03/shepherd/.shepherd/logs/hooks/2026-08-12.jsonl` and `.../2026-08-13.jsonl` are both 0 bytes, despite this being an actively-running v6.4.5 sprint with multiple concurrent lanes dispatching hooks throughout both days.
  5. `git blame -L 496,502 -- hooks/scripts/_lib.sh` → commit `d673d9bf`, 2026-05-17 — the defect has been present, unnoticed, for roughly three months at HEAD.
  6. The python3 fallback branch of `log_event` (used when `jq` is absent) passes the SAME malformed `"${fields_json:-{}}"` expansion as `sys.argv[7]` into `json.loads(sys.argv[7] or "{}")` (`_lib.sh:~403`), which will raise an uncaught `JSONDecodeError` before any `print()` runs — same silent total failure, not jq-specific.
- Impact on this task specifically: the guard's own `"lane-custody-exempt"` tag (`conductor_write_guard.sh:136`), meant to let an auditor later grep the JSONL trail and confirm *which* branch fired for a given decision, never reaches disk. I was still able to answer the primary question with HIGH confidence by reading the guard's stdout directly (Finding 1) rather than relying on the log — but the log itself, as an independent corroborating instrument, is currently inert.
- Confidence: HIGH (structurally verified via isolated bash reproduction + live-repo field corroboration, two independent lines of evidence, fully deterministic).

## Open questions

- Whether `conductor_write_guard.sh` fires end-to-end when a genuine Agent-Teams in-process teammate issues a real `Write`/`Edit` tool call (as opposed to: direct script execution with a synthetic payload, which is what this probe did, plus indirect field evidence from a sibling hook on the same matcher list). I could not spawn a live teammate from this read-only auditor context to test this directly. LOW-confidence item; not a finding, listed here per contract.
- `log_event`'s breakage (Finding 4) likely also silently defeats every OTHER hook's audit trail across the whole plugin (any hook that calls `emit_deny`/`emit_context`/`pass_silent` with a hook name), not just this guard's — I did not enumerate every caller; scope of this probe was the lane-plan custody question. Worth a follow-up sweep, out of scope here (auditor is read-only and does not file the fix).

## Reproduction

All artifacts live under `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-probe/` (fakerepo/, payloads/, results/) — nothing was written, staged, committed, or pushed inside `/Users/jo3/src/fl03/shepherd` by this probe except this report file itself.

```
GUARD=/Users/jo3/src/fl03/shepherd/hooks/scripts/conductor_write_guard.sh
cd .../custody-probe/fakerepo   # git repo on branch v6.4.5-dev.1, .shepherd/shepherd.toml present,
                                 # .shepherd/tmp/session-tier-sess-custody-probe-1 stamped with lane_plan
"$GUARD" < payloads/A_allow_lane.json        > results/A.stdout 2> results/A.stderr; echo $? > results/A.exitcode
"$GUARD" < payloads/B_deny_masterplan.json   > results/B.stdout 2> results/B.stderr; echo $? > results/B.exitcode
"$GUARD" < payloads/C_deny_reports.json      > results/C.stdout 2> results/C.stderr; echo $? > results/C.exitcode
"$GUARD" < payloads/D_allow_lane_edit.json   > results/D.stdout 2> results/D.stderr; echo $? > results/D.exitcode
"$GUARD" < payloads/E_solo_nomarker_lanepath.json > results/E.stdout 2> results/E.stderr; echo $? > results/E.exitcode
"$GUARD" < payloads/F_crosslane_deny.json    > results/F.stdout 2> results/F.stderr; echo $? > results/F.exitcode
```
