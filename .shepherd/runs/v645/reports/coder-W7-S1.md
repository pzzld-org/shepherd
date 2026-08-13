## CODER REPORT
- Lane: W7-S1
- Skills loaded: code-style (no markdown-specific language skill exists in the installed set;
  `commands/spawn.md` is prose/doctrine, not source code — code-style's general discipline
  (no TODO/FIXME, SUBTRACT over append, precise citation) applied throughout)
- Files touched (created/modified/deleted): `/Users/jo3/src/fl03/shepherd/commands/spawn.md` (modified)
- LOC delta: +53 / -13 vs base commit `2fea02d` (markdown doc file; not part of any `*.rs` LOC budget)
- Acceptance grep results:
  - `grep -n "RESOLVE\|Compute and PRINT" commands/spawn.md` → table row 1 ("RESOLVES a predicted
    `backendType`... never just reads the flag and stops") + Check 1 intro + step 2 header — PASS
    (Check 1 resolves a backend rather than reading a config key and stopping)
  - `grep -n "\[SUBSTRATE\]" commands/spawn.md` → step 2's print line
    `[SUBSTRATE] teammateMode=<mode> → predicted backendType=<tmux|in-process|UNRESOLVED>` — PASS
    (predicted backendType computed and printed BEFORE the spawn instruction fires)
  - `grep -n "tmuxPaneId\|claude-swarm-<lead-pid> ls" commands/spawn.md` → step 4 names both
    post-spawn oracles verbatim — PASS
  - `grep -n "FORBIDDEN\|/private/tmp/tmux-501/default" commands/spawn.md` → step 4: "Bare `tmux
    ls` is FORBIDDEN as an oracle here — name it and refuse it" + the literal default-socket path
    — PASS (bare `tmux ls` named and refused with the exact wrong-socket path DF-68 measured)
  - `grep -n "does NOT gain\|CONTAINMENT consequence\|not a footnote" commands/spawn.md` → step 3's
    tmux/in-process capability statements, DF-65 framed as "a CONTAINMENT consequence... not a
    footnote" — PASS
  - `grep -n "UNRESOLVED\|UNTESTED" commands/spawn.md` → step 2's `auto` branch: predicted
    `backendType=UNRESOLVED`, explicit "resolves to on any given box is UNTESTED", no
    `$TMUX`/`$TERM_PROGRAM` heuristic used to assert an outcome — PASS
  - `grep -c "^### Check 1" commands/spawn.md` → 1 — PASS (single section, SUBTRACT not append)
- Halts encountered: none
- Summary: Rewrote Preflight table row 1 and the "### Check 1 — substrate verification" subsection
  in `commands/spawn.md` per DF-66/DF-68, reusing this repo's existing structure (SUBTRACT in
  place, one Check 1 section). On dispatch, `commands/spawn.md` already carried an uncommitted
  prior-pass rewrite (a superseded `L7-S1` report from an earlier naming convention sits at
  `reports/coder-L7-S1.md` for the same brief) — treated as REDO state per the coder contract
  ("a REDO simply re-runs you over the same files") and corrected rather than discarded. The one
  substantive defect in that prior pass: its step 2 computed the `auto`-mode prediction by
  checking `$TMUX`/`it2`-on-PATH in the LEAD session's own environment and asserted a concrete
  `tmux`/`in-process` guess from it — precisely the inference DF-66's own appended
  self-correction calls UNSOUND (Claude Code spawns teammates on a private tmux socket keyed to
  the lead's PID, independent of whatever the lead's own `$TMUX` says). Fixed by making the
  `auto` branch predict `backendType=UNRESOLVED` and state explicitly that the resolution is
  untested on any given box, deferring to the step-4 oracles rather than guessing. Also added the
  literal wrong-socket path (`/private/tmp/tmux-501/default`) to the bare-`tmux ls` refusal,
  since the dispatch brief named it explicitly and it matches DF-68's measured evidence and the
  sibling `skills/harness/SKILL.md` wording (that file is out of scope here, read-only for
  cross-check). Final Check 1 shape: (1) env-var check, necessary-not-sufficient, unset →
  DOWNGRADE, with the original probe-note detail preserved; (2) compute+print predicted
  `backendType` from `teammateMode` — trivial for explicit `tmux`/`in-process`, `UNRESOLVED` +
  untested-disclaimer for `auto`; (3) states plainly what tmux (separate CLI process, MAIN
  session, keeps `Workflow`+`ScheduleWakeup`, no ungranted write tools) and in-process (subagent,
  loses `Workflow`+`ScheduleWakeup` even when granted, OBSERVED GAINING ungranted
  `Edit`/`Write`/`Artifact` on read-only `shepherd:conductor` — DF-65 framed as containment, not a
  footnote) each carry; (4) names the correct post-spawn oracles (`backendType`/`tmuxPaneId` in
  `~/.claude/teams/<team>/config.json`, `tmux -L claude-swarm-<lead-pid> ls`) and forbids-by-name
  bare `tmux ls` with the literal wrong-socket path and the "cost this run a day" consequence;
  (5) keeps the permission-mode-inheritance point and the "failed verification → DOWNGRADE to
  `/shepherd:start`" closing line unchanged. No new HARD-gating logic added — the only refusal
  branch remains the pre-existing unset-env-var → downgrade path; backend resolution stays
  VERIFY/advisory (print + inform, never a silent assertion). Did not touch `skills/harness/SKILL.md`
  or `skills/shepherd/SKILL.md`, both of which show as modified in `git status` from concurrent
  wave-siblings, not from this edit — confirmed via `git diff -- commands/spawn.md` showing only
  this file's hunk, and `git diff --stat` showing the other two files' hunks are disjoint from
  mine.
- Reporter: coder-W7-S1 @ 2026-08-13T22:04:58Z

## INSIGHTS
- kind: gap — this brief's pointer (`.shepherd/runs/v645/dogfood.md §W7-S1`) does not resolve:
  `dogfood.md` is a flat findings ledger with no `W7-S1` heading or bracketed `[SKILLS]`/
  `[FILE-SCOPE]`/etc. brief block anywhere in it. The dispatch message itself carried the full
  operative brief inline instead. Worth a mesh/pipeline note: once a run moves past its planned
  waves into ledger-driven FIX-THIS-RUN dispatches, the brief pointer convention silently stops
  matching reality, and a coder has to reconstruct brief-validity by cross-reading the cited DF
  rows rather than a single `§<step-id>` anchor.
- kind: duplication — a second dispatch of the identical brief landed on an already-modified
  file scope (`reports/coder-L7-S1.md` existed for what is functionally the same task under an
  earlier lane-naming convention, `L7-S1` vs `W7-S1`). The uncommitted work was still on disk and
  correct to build on, but nothing marked it as superseded before this dispatch fired — worth
  reconciling the `L7-*`/`W7-*` step-id schemes so a re-dispatch doesn't have to infer the
  relationship from report content.
