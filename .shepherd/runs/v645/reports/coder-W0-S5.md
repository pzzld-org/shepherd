## CODER REPORT

- Lane: l5-harness
- Step: W0-S5 — dispatch doctrine matches the platform that actually ships (DF-02, DF-11, DF-E1)
- Skills loaded: code-style (mandatory minimum; both target files are `.md`, no additional
  language skill applies to `[FILE-SCOPE]`)
- Files touched (created/modified/deleted): modified
  - `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/commands/spawn.md`
  - `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/skills/harness/SKILL.md`
- LOC delta: +72 / -19 (commands/spawn.md: +23/-10; skills/harness/SKILL.md: +49/-9)

## Files changed

- `commands/spawn.md`
  - `### Pre-spawn tool check` — replaced "`Agent` spawns subagents, NOT teammates" with the
    corrected fact: `Agent(subagent_type, name)` **is** the teammate-spawn primitive; `name` is
    the live discriminator; a teammate dispatching its own sub-flock MUST omit `name` (flat
    roster) or is refused outright.
  - `## Spawn dispatch` — replaced "native teammate-spawn" framing with the mechanism it
    actually resolves to: one `Agent(subagent_type: "shepherd:conductor", name: ...)` call per
    lane; `team_name` called out as dead alongside `TeamCreate`.
  - `### Self-contained engineer` (intro line) — same correction for the engineer teammate
    spawn: `Agent(subagent_type: "shepherd:engineer", name: <teammate-name>)`.
  - `### Self-contained engineer` (`ENGINEER-TOPOLOGY-MISMATCH` line) — corrected the
    triggering condition from "dispatched as an Agent/Task subagent" (implying a different
    tool) to "dispatched via `Agent(...)` WITHOUT `name`" (the actual discriminator).
- `skills/harness/SKILL.md`
  - `## Agent Teams` MUST-know constraints — added three new bullets: (1) `Agent(subagent_type,
    name)` is the teammate-spawn primitive, no separate "native" path; (2) flat-roster
    constraint — a teammate passing `name` to dispatch its own sub-flock is refused outright;
    (3) async `Agent()` notification routing goes to the task-tree owner, not the dispatcher,
    measured with `Workflow` itself absent (not Workflow-specific).
  - `## Workflow tool` → `**Fan-out vehicle is SUBSTRATE-conditional...**` — corrected the
    "Agent-Teams teammate: `Workflow` WORKS" claim to "`Workflow` MAY work — run the probe, act
    on it, never on frontmatter"; documented that a negative probe result on a genuine teammate
    is now the EXPECTED outcome (DF-02/DF-11), not an anomaly, backed by this sprint's live
    measurement against `@conductor`'s/`@engineer`'s own frontmatter grant.
  - `## ToolSearch` item 1 — corrected "`Agent({subagent_type})` or the native teammate-spawn
    instruction" (implying two mechanisms) to one primitive, `name` present/absent.
  - `## Tool presence` — added a new `DF-E1` paragraph documenting that `tools:` frontmatter is
    not authoritative (measured: `agents/engineer.md:7` grants `Workflow`/`Glob`/`Grep`, none
    present in the live tool list, reproduced 3x this sprint) and that `WORKFLOW-VEHICLE-PROBE`
    exists precisely because the grant cannot be trusted.

`WORKFLOW-VEHICLE-PROBE` itself was NOT retired — only its expected outcome for a teammate
changed, per `[NON-GOALS]`. The tier model (root/conductor/flock) was not touched.

## LOC delta

+72 / -19 across the two files (net +53). Both are Markdown/prose, not `*.rs`; the ONE-LOC
rule's deterministic counter is Rust-specific, so this delta is reported for transparency only,
well inside the ~130 estimate either way.

## Acceptance outputs

```
$ rg -c 'NEVER the Agent/Task tool' commands/ skills/ agents/ ; test $? -eq 1
(no output — rg found zero matches, exit 1)
FINAL_EXIT=0
```

```
$ rg -q 'roster is flat|cannot spawn other teammates' skills/harness/SKILL.md
FINAL_EXIT=0
```

```
$ rg -q 'task-tree owner' skills/harness/SKILL.md
FINAL_EXIT=0
```

All three PASS.

## Deviations

- **DO-NOT-DUPLICATE scope clarification (documented, not a halt).** The brief's grep as
  literally written (`rg -n 'native teammate-spawn' commands/ skills/ agents/`) returns 14
  hits tree-wide, not the stated "expected 3" — but restricted to `[FILE-SCOPE]`
  (`commands/spawn.md` + `skills/harness/SKILL.md`, the only files I may write), the pre-edit
  count was exactly 3: `commands/spawn.md:251`, `skills/harness/SKILL.md:110`,
  `skills/harness/SKILL.md:200`. I corrected all three in place and added zero new locations
  describing the mechanism elsewhere (verified post-edit: only one `native teammate-spawn`
  string remains in scope, and it now reads "there is no separate 'native teammate-spawn'
  tool" — a negation, not a new description). The other 11 tree-wide hits
  (`agents/shepherd.md`, `agents/conductor.md`, `skills/shepherd/SKILL.md`,
  `skills/shepherd/references/*`, `skills/context/*`) are outside `[FILE-SCOPE]` /
  `[MUST-NOT-TOUCH]`-adjacent and were left untouched; they remain compatible with the
  correction (the phrase "native teammate-spawn" itself is not wrong, only the
  "NEVER the Agent/Task tool" pairing was).
- Also corrected `### Pre-spawn tool check`'s "`Agent` spawns subagents, NOT teammates"
  parenthetical, immediately adjacent to and part of the same DF-02 doctrine the ACTIONS
  targeted at `commands/spawn.md:250,344` — leaving it unfixed would have left a directly
  contradictory claim two paragraphs above the corrected "Spawn dispatch" section, in the same
  file, same `[FILE-SCOPE]`.
- No `BRIEF-AMENDMENT`, `SCOPE OVERFLOW`, `CONTEXT-INVENTORY STALE`, or `BASE-DRIFT` triggered.
  No git command run (guard untouched).

## Staged GH commands

None — no GitHub writes performed or required for this step.

## Notes

- Step 0.5 verified: `git rev-parse HEAD` = `5be42280615c8dc5321061798240f476dffed645`,
  matching `[BASE-COMMIT-EXPECTED]` exactly, before any edit.
- `commands/spawn.md` was read fresh before editing; W0-S2's uncommitted Preflight Check 4b row
  (`| 4b | Registry DB | ... |`) was confirmed present and left untouched by my edits (visible
  in the diff as a pre-existing hunk, not something I introduced).
- Fenced code-block balance verified post-edit (`commands/spawn.md`: 20 backtick-fences, even;
  `skills/harness/SKILL.md`: 0, even) — no broken Markdown.
- No cargo, no build, no lint invoked. No files touched outside `[FILE-SCOPE]`.
- Reporter: shepherd:coder (W0-S5, l5-harness) @ 2026-08-13T00:46:14Z
