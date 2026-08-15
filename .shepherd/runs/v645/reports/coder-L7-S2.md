## CODER REPORT

- Lane: L7-S2
- Skills loaded: code-style (markdown/prose conventions from operator ledger,
  applied generically — no dedicated `.md` file in `code-style`), shepherd:harness
  (self — the skill under edit, read in full before touching it)
- Files touched (created/modified/deleted): `skills/harness/SKILL.md` (modified)
- LOC delta: +44 / -1 (markdown doc; not subject to the `*.rs` LOC budget /
  ONE-LOC rule — no production Rust touched)
- Acceptance grep results (re-run at HEAD after edit):
  - `grep -n "claude-swarm-<lead-pid>" skills/harness/SKILL.md` — PASS, 2
    matches (`## Agent Teams` bullet citing the verbatim `ps` command; `##
    Tool presence` oracle restatement).
  - Every occurrence of literal `tmux ls` explains it is the WRONG oracle —
    PASS, both occurrences (line ~78, `## Agent Teams`; line ~327, `## Tool
    presence`) are inside sentences stating it reads the DEFAULT socket and
    returns a false negative by construction; neither recommends it.
  - `grep -n "teammateMode" skills/harness/SKILL.md` includes a spawn-time
    match — PASS: "`teammateMode` is read at SPAWN time, never at session
    start: changing it in `~/.claude/settings.json` mid-session takes effect
    on the very next spawn — no lead relaunch required (DF-68)."
  - `grep -n "separate.*CLI process\|separate.*claude.*process"` — PASS, 2
    matches (`## Agent Teams` bullet; `## Workflow tool` mechanism
    paragraph). Fixed once mid-task: an earlier phrasing split "CLI" and
    "process" across a markdown line-wrap, which the regex (line-scoped)
    could not match across the newline — reworded to keep the phrase on one
    line in both spots.
  - `grep -c "WORKFLOW-VEHICLE-PROBE" skills/harness/SKILL.md` >= 3 — PASS,
    4 occurrences, all pre-existing; none removed or edited (non-goal
    honored).
- Halts encountered: none
- Summary: Extended `## Agent Teams` (three new/extended bullets after the
  existing `teammateMode` enum bullet) with DF-68's measured mechanism: the
  private `claude-swarm-<lead-pid>` tmux socket and the verbatim spawn
  command, why bare `tmux ls` is a false-negative-by-construction oracle,
  the correct oracle (`tmux -L claude-swarm-<lead-pid> ls` +
  `backendType`/`tmuxPaneId` in team config), the separate-CLI-process /
  MAIN-session fact for `backendType: tmux` teammates, and the
  read-at-spawn-not-session-start semantics of `teammateMode`. Extended
  `## Workflow tool`'s SUBSTRATE-conditional block with the WHY behind "MAY
  work": a tmux-backed teammate sits outside the sub-agents-only tool
  filter documented at `/docs/en/sub-agents` (because it's a separate CLI
  process, i.e. a MAIN session) while an in-process teammate is a subagent
  that DOES hit that filter — `backendType`, not "is this nominally a
  teammate," is the controlling variable — citing `Run ID:
  wf_020292db-fef` ACCEPTED. Checked both sections for a blanket
  no-backend-qualifier claim that "all teammates uniformly lose/keep
  Workflow" per REQUIRED CHANGES item 3; found none — the existing
  "Agent-tool subagent ... Workflow is genuinely denied" bullet is already
  scoped to the substrate-absent case, not a blanket teammate claim, so no
  correction-in-place was needed. Did not touch `commands/spawn.md` or
  `skills/shepherd/SKILL.md` (sibling scope) and did not edit the
  `WORKFLOW-VEHICLE-PROBE`/`WORKFLOW-SELFCHECK-TOOLSEARCH` rule text itself
  in `## Tool presence` (non-goal); the file's `## Tool presence` section
  now also carries one short DF-68 paragraph tying the tmux-socket false
  negative to the same invalid-oracle class as the `ToolSearch`
  false-negative already documented there — purely additive, does not
  alter either named rule's text. No git operations performed (read-only
  `git status`/`diff` only, per coder git-custody boundary).
- Reporter: coder-L7-S2 @ 2026-08-13T00:00:00Z
