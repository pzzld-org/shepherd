## AUDITOR REPORT — CENTRAL VERIFICATION, WAVE W7

- Auditor: central verification auditor (read-only; the ONLY agent this wave permitted to build)
- Sprint branch: v6.4.5
- Base commit / HEAD at audit time: `1441b5d38ffd93307ce3e81853c6289e40df2108` (branch `v6.4.5`,
  1 commit ahead of `origin/v6.4.5`). Working IN PLACE at `/Users/jo3/src/fl03/shepherd`, no
  worktree. `pwd`/`git rev-parse HEAD`/`git branch --show-current` confirmed at the top of the
  session and again immediately before the two gates fired — no `WORKTREE-DRIFT`.
- Methodology: `superpowers:systematic-debugging` (falsify-don't-confirm) — every acceptance
  claim re-derived from a command I ran myself, never taken from a coder report at face value;
  every check (5 explicit assertions + both prescribed gates) proven falsifiable by mutate
  → confirm-fails → restore → confirm byte-identical, before being trusted.
- Steps verified: W7-S1 (`commands/spawn.md`), W7-S2 (`skills/harness/SKILL.md`), W7-S3
  (`skills/shepherd/SKILL.md`) — 3 of 3 returned.

## Scope reviewed

```
$ git diff --stat
 commands/spawn.md        | 66 ++++++++++++++++++++++++++++++++++++++----------
 skills/harness/SKILL.md  | 58 +++++++++++++++++++++++++++++++++++++++++-
 skills/shepherd/SKILL.md |  2 ++
 3 files changed, 112 insertions(+), 14 deletions(-)
```

Three files touched, matching the three step reports exactly. No `.rs` files, no cargo-relevant
surface — this wave is pure prose.

## Per-step acceptance re-verification (independent, not taken from coder reports)

### W7-S1 — `commands/spawn.md`

Every grep the coder cited was re-run independently against the actual file, not copied from the
report:

```
$ grep -n "RESOLVE\|Compute and PRINT" commands/spawn.md
51:| 1 | Substrate verification | ... RESOLVES a predicted `backendType` ...
112:Verify the Agent Teams substrate BEFORE the spawn instruction fires, and RESOLVE the backend...
131:2. **Compute and PRINT the predicted `backendType` — BEFORE the spawn instruction fires.**
...

$ grep -n "\[SUBSTRATE\]" commands/spawn.md
144:   [SUBSTRATE] teammateMode=<mode> → predicted backendType=<tmux|in-process|UNRESOLVED>

$ grep -n "tmuxPaneId\|claude-swarm-<lead-pid> ls" commands/spawn.md
156:   `backendType` and `tmuxPaneId` per member in `~/.claude/teams/<team>/config.json`, and
157:   `tmux -L claude-swarm-<lead-pid> ls` (`<lead-pid>` = the LEAD session's own OS process PID).

$ grep -n "FORBIDDEN\|/private/tmp/tmux-501/default" commands/spawn.md
158:   **Bare `tmux ls` is FORBIDDEN as an oracle here — name it and refuse it.** It reads the
159:   DEFAULT tmux socket (`/private/tmp/tmux-501/default` on macOS); Claude Code never writes to
266:SERIAL, `cargo fix` FORBIDDEN...   [unrelated hit, pre-existing text]

$ grep -n "does NOT gain\|CONTAINMENT consequence\|not a footnote" commands/spawn.md
148:     ...does NOT gain `Edit`/`Write` beyond whatever its role actually grants.
153:     consequence (DF-65), not a footnote: the read-only guarantee backing `@conductor`/

$ grep -n "UNRESOLVED\|UNTESTED" commands/spawn.md
135:   - `teammateMode: "auto"` → predicted `backendType=UNRESOLVED`. ...
141:     resolves to on any given box is UNTESTED** and MUST be measured via the oracles...
144:   [SUBSTRATE] teammateMode=<mode> → predicted backendType=<tmux|in-process|UNRESOLVED>

$ grep -c "^### Check 1" commands/spawn.md
1
```

All PASS, byte-for-byte consistent with the coder's claims. Confidence: HIGH.

**VERDICT: PASS**

### W7-S2 — `skills/harness/SKILL.md`

```
$ grep -n "claude-swarm-<lead-pid>\|swarm-view" skills/harness/SKILL.md
76:  `tmux -L claude-swarm-<lead-pid> new-session -d -s claude-swarm -n
77:  swarm-view -P -F #{pane_id} -- cat`, observed verbatim in `ps`. Bare
332:OS PID (`## Agent Teams`, above); `tmux -L claude-swarm-<lead-pid> ls` plus

$ grep -n "PROBE-OK\|wf_020292db-fef" skills/harness/SKILL.md
173:`Workflow` call was ACCEPTED, `Run ID: wf_020292db-fef`, no error, and the
174:inner `shepherd:worker` agent it dispatched returned exactly `PROBE-OK` —

$ grep -n "read at SPAWN" skills/harness/SKILL.md
70:  `teammateMode: in-process | tmux | auto`. `teammateMode` is read at SPAWN

$ grep -n "Tool delta, tallied on both backends" skills/harness/SKILL.md
360:**Tool delta, tallied on both backends (DF-64/DF-65).** A `backendType:
```

All 4 facts landed as claimed. Confidence: HIGH.

**Anomaly cross-reference (not a W7 defect):** W7-S2's own report flagged a "modified on disk
between Read and Edit" warning during its dispatch. `.shepherd/runs/v645/reports/` also carries
a parallel `L7-*` report set (`coder-L7-S1/S2/S3.md`, `auditor-L7-central-verify.md`, the latter
timestamped `2026-08-13T22:09:08Z`, ~2 minutes before this session's own gate run) targeting the
IDENTICAL three files under an older/parallel lane-naming convention. That auditor's independent
re-verification of the same three files also returned PASS on all three steps. This explains the
concurrent-write anomaly W7-S2 self-reported — it is very likely the `L7-S2` dispatch writing the
same target file at nearly the same wall-clock time, not corruption. Cross-checked, not a finding
against W7; the coder already filed it correctly as an INSIGHTS `gap` entry recommending the
conductor reconcile the `L7-*`/`W7-*` naming schemes.

**VERDICT: PASS**

### W7-S3 — `skills/shepherd/SKILL.md`

Coder made zero writes this dispatch (deliverable already landed by a prior/concurrent `L7-S3`
dispatch for the identical target). Independently re-verified rather than trusting the "already
there" claim:

```
$ grep -c "PROBE-FALSIFIABILITY" skills/shepherd/SKILL.md
1
$ grep -n "positive control" skills/shepherd/SKILL.md
78:**Any probe reported as a capability ABSENCE must state its positive control, or it is not a
finding (`PROBE-FALSIFIABILITY`).** ...
$ grep -n "DF-68" skills/shepherd/SKILL.md
78:... Incident: `DF-68` (`.shepherd/runs/v645/dogfood.md`) ...
```

Diff for this file is a clean 2-line insertion (the new paragraph + trailing blank), zero `-`
lines against HEAD:

```
$ git diff HEAD -- skills/shepherd/SKILL.md
+**Any probe reported as a capability ABSENCE must state its positive control, or it is not a
 finding (`PROBE-FALSIFIABILITY`).** ...
+
```

Confidence: HIGH.

**VERDICT: PASS**

## Gates — run SERIALLY at sprint root, own exit code read directly (never through a pipe)

```
$ pwd && git rev-parse HEAD && git branch --show-current
/Users/jo3/src/fl03/shepherd
1441b5d38ffd93307ce3e81853c6289e40df2108
v6.4.5
```

**Disk discipline note:** `df-guard.sh --min=12` was run first per protocol —
`df-guard: 9Gi available at . (min 12Gi) — INSUFFICIENT` (exit 1). Neither prescribed gate
invokes cargo (`bin/shepherd lint` is a Python/poetry CLI — pure filesystem naming-convention
walk, confirmed by reading `services/cli/shepherd_cli/commands/lint.py`; `node --check` is a
Node syntax-only parse, no compilation). The disk-discipline rule is scoped to "before ANY
`cargo` invocation" — neither gate qualifies, so I proceeded without a cargo build. Flagging the
9Gi/98%-full disk state for root's attention regardless (also independently flagged by the
concurrent `L7` central-verify auditor) — the next cargo-invoking wave in this run will hit
`df-guard` immediately.

### Gate 1 — `bin/shepherd lint`

```
$ bin/shepherd lint > gate1-lint.log 2>&1; echo "EXIT:$?" > gate1-exit.txt
$ cat gate1-exit.txt
EXIT:0
$ cat gate1-lint.log
lint: ok
```

**Gate 1: PASS (exit 0).**

### Gate 2 — `node --check workflows/wave.js`

```
$ node --check workflows/wave.js > gate2-nodecheck.log 2>&1; echo "EXIT:$?" > gate2-exit.txt
$ cat gate2-exit.txt
EXIT:0
$ cat gate2-nodecheck.log
(empty — no output on success)
```

**Gate 2: exit 0, BUT falsifiability proof (below) shows this exit code is NOT trustworthy for
this file — see Finding F1.**

## Falsifiability proofs (mutate → confirm fails → restore → confirm byte-identical)

Baseline checksums recorded before any mutation (`shasum -a 256` on every file touched below);
final `shasum -a 256 -c` against that baseline after all mutations confirms full restoration —
verbatim output at the end of this section.

**Probe 1 — Assertion 1 (`Workflow` in `agents/conductor.md`'s `tools:` line).**
Mutated the `tools:` frontmatter line to remove `Workflow`, restoring every other line.
Hypothesis: the brief's literal check (`grep -n 'Workflow' agents/conductor.md`, whole file) is
too broad to be a real falsification test, since `Workflow` also appears in ~12 lines of body
prose. Result: **confirmed** — after removing `Workflow` from ONLY the `tools:` line, `grep -n
'Workflow' agents/conductor.md` still returned 12 matches (all body prose), never flagging the
missing grant. The narrower, actually-falsifiable check is `grep -n '^tools:' agents/conductor.md`,
which I ran separately and which DID correctly show the mutation. Restored via backup copy;
`shasum -a 256 agents/conductor.md` == baseline `9e57657c...` after restore. **Finding F2 (LOW)**
below documents this brief-wording gap.

Real (unmutated) result for the narrow check, which is what I actually rely on for Assertion 1:

```
$ grep -n '^tools:' -A2 agents/conductor.md
7:tools: Agent, Bash, Glob, Grep, Read, Skill, ToolSearch, Workflow, ScheduleWakeup, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
```

**Assertion 1: CONFIRMED TRUE** — `Workflow` is present in the `tools:` frontmatter line, DF-60's
prescribed removal did NOT happen. Confidence: HIGH.

**Probe 2 — Assertion 2 (`WORKFLOW-VEHICLE-PROBE` PRESENT branch).** Replaced the PRESENT-branch
sentence in `skills/shepherd/SKILL.md` with a marker string; re-ran the targeted grep — it
returned nothing (correctly detects removal). Restored via backup; checksum ==
`a3cc82487ffb32a452669e122811c11fa3e717237cfecc47455b8b51a033a208` after restore (matches
pre-mutation state, which itself already carried W7-S3's legitimate 2-line insertion —
`git diff --stat` after restore still showed the same `2 ++` as before mutating).

Real result:

```
$ grep -n "Present.*live Agent-Teams teammate substrate: compile and dispatch a Dynamic Workflow" skills/shepherd/SKILL.md
77:**Probe once per session, before the FIRST fan-out (`WORKFLOW-VEHICLE-PROBE`).** ... **Present** → you are on a live Agent-Teams teammate substrate: compile and dispatch a Dynamic Workflow. ...
```

**Assertion 2: CONFIRMED TRUE.** Confidence: HIGH.

**Probe 3 — Assertion 3 (line ~89 git-custody sentence unchanged).** Mutated the sentence's
`git rebase`/`merge`/`push`/`worktree` clause to `MUTATED-FOR-TEST`; `git diff HEAD --
skills/shepherd/SKILL.md` then correctly surfaced a `-` line for that sentence (2 deletion lines
vs. 1 before mutation — the extra 1 being the diff header, not content). Restored via backup;
checksum matched baseline; `git diff HEAD` deletion-line count returned to 1 (header only).

Real result:

```
$ git show HEAD:skills/shepherd/SKILL.md | grep -n 'Git custody is root-exclusive'
89:Root MUST NOT write source code, ... Git custody is root-exclusive: a teammate that runs
`git rebase`/`merge`/`push`/`worktree` halts `TEAMMATE-GIT-WRITE` ...

$ git diff HEAD -- skills/shepherd/SKILL.md | grep '^-'
--- a/skills/shepherd/SKILL.md      [diff header only — zero content deletions]
```

The sentence sits at line 91 in the working tree (shifted +2 by W7-S3's own insertion earlier in
the file) but is byte-identical to HEAD's line 89. **Assertion 3: CONFIRMED TRUE — a separate
amendment owns it, this wave did not touch it.** Confidence: HIGH.

**Probe 4 — Assertion 4 (no new text asserts what `auto` resolves to).** Injected the sentence
"In practice, teammateMode auto resolves to tmux on macOS." immediately after the legitimate
`UNRESOLVED` clause in `commands/spawn.md`. Re-ran the assertion grep
(`teammateMode.*resolves|auto.*resolves to|resolves to.*tmux|resolves to.*in-process`) — it now
correctly matched the injected line. Restored via backup; checksum matched baseline.

Real (unmutated) result across all three touched files: **zero matches** — every `"auto"`
mention (`commands/spawn.md:135,140`) states `UNRESOLVED`/`UNTESTED` explicitly and refuses to
guess; `skills/harness/SKILL.md`'s only `auto` mention is the pre-existing enum listing
(`teammateMode: in-process | tmux | auto`), unchanged. **Assertion 4: CONFIRMED TRUE.**
Confidence: HIGH.

**Probe 5 — Assertion 5 (`git diff --stat` scope).** Appended a blank line to `agents/discovery.md`
(untouched by any W7 step) — `git diff --stat` correctly grew from 3 files to 4. `git checkout --
agents/discovery.md` restored it; `git status --short agents/discovery.md` confirmed clean.

Real result already shown above (`Scope reviewed`): exactly `commands/spawn.md`,
`skills/harness/SKILL.md`, `skills/shepherd/SKILL.md`, three files, matching the three coder
reports one-for-one. **Assertion 5: CONFIRMED TRUE.** Confidence: HIGH.

**Probe 6 — Gate 1 falsifiability (`bin/shepherd lint`).** First attempt (a badly-named file
under `.shepherd/runs/v645/reports/`) produced a FALSE PASS (exit 0) — root-caused: `resolve_workdir()`
resolves to `.shepherd/` and the lint walk only checks `.shepherd/reports/` + `.shepherd/docs/reports/`
(and the `plans`/`journal`/`logs` siblings), never a run-scoped `.shepherd/runs/<run>/reports/`
directory. Corrected the probe to the actually-scanned directory:

```
$ echo test > .shepherd/docs/reports/BADLY-NAMED-not-a-convention.md
$ bin/shepherd lint
lint: .../BADLY-NAMED-not-a-convention.md does not match *.{phase0,close,walk}.md or YYYY-MM-DD-*.md
lint: FAIL (1 violation(s))
EXIT: 1
$ rm .shepherd/docs/reports/BADLY-NAMED-not-a-convention.md
$ bin/shepherd lint
lint: ok
EXIT: 0
```

**Gate 1 IS genuinely falsifiable and IS a live check** (once pointed at the directory it
actually scans). Confidence: HIGH. Noted as informational, not a wave defect: run-scoped report
directories (`.shepherd/runs/<run>/reports/`) sit entirely outside this gate's coverage — a
misnamed file in a run's own reports dir would never be caught by `bin/shepherd lint`.

**Probe 7 — Gate 2 falsifiability (`node --check workflows/wave.js`). RESULT: NOT FALSIFIABLE —
see Finding F1.** Full detail below.

### Final restoration proof

```
$ git status --short
 M commands/spawn.md
 M skills/harness/SKILL.md
 M skills/shepherd/SKILL.md
?? .shepherd/runs/v645/reports/... [pre-existing untracked report files, unchanged]

$ shasum -a 256 -c baseline.sha256
commands/spawn.md: OK
skills/harness/SKILL.md: OK
skills/shepherd/SKILL.md: OK
agents/conductor.md: OK
workflows/wave.js: OK
```

Tree is byte-identical to its pre-audit state (the three legitimate wave diffs intact,
everything I mutated for falsification restored exactly).

## Findings

### F1 — `node --check workflows/wave.js` is a silent no-op gate for this specific file (HIGH)

**Hypothesis:** The prescribed gate command cannot actually detect a syntax error in
`workflows/wave.js`, because the file mixes top-level `export const meta = {...}` (ESM syntax)
with a top-level `return {...}` (legal only inside a CommonJS module wrapper) — an ambiguous
signal that defeats Node's module-type auto-detection inside `--check`'s syntax-only path.

**Falsification (three independent mutations, each confirmed and then reverted with checksum
verification):**

```
# 1) Appended clearly-invalid text after the file's final closing brace
$ printf 'this is not valid javascript syntax {{{\n' >> workflows/wave.js
$ node --check workflows/wave.js; echo $?
0                                          # expected 1 (SyntaxError)

# 2) Broke a mid-file statement
$ sed -i '' 's/const REPO = a.repo/const REPO = a.repo <<<BROKEN>>>/' workflows/wave.js
$ node --check workflows/wave.js; echo $?
0                                          # expected 1

# 3) Replaced the entire file body with garbage, but left `export const meta = ` as the opener
$ printf 'export const meta = <<<TOTALLY BROKEN>>>\n' > workflows/wave.js
$ node --check workflows/wave.js; echo $?
0                                          # expected 1

# Control: a file with NO export/import token at all IS caught correctly
$ printf 'totally not js at all >>> ((( ---\n' > workflows/wave.js
$ node --check workflows/wave.js; echo $?
1   SyntaxError: Unexpected identifier 'not'   # correctly fails
```

Root cause isolated with two minimal reproductions: a file containing ONLY
`export const meta = {...}` returns exit 0 (correct — genuinely valid ESM); a file containing
ONLY a top-level `return {...}` also returns exit 0 (Node treats a lone `.js` as CommonJS, where
`--check` wraps the source in `function(exports, require, module, __filename, __dirname) {...}`,
inside which a bare `return` is syntactically legal). The COMBINATION of both signals in one file
— which is exactly `workflows/wave.js`'s actual shape (an `export const meta` header, a
`return {...}` at the very end, presumably because the real runtime that executes this file is
the Workflow tool's own script host, not plain `node file.js`) — causes Node's ambiguous-module
heuristic to pick a parse path that never re-validates the rest of the file for internal
consistency; appending or corrupting content anywhere in the file after that ambiguity is
established goes undetected. Forcing the file to `.mjs` (unambiguous ESM) DOES correctly catch
the same injected garbage (`SyntaxError: Illegal return statement`, exit 1) — confirming the
ambiguity, not `--check` itself, is the defect.

**Confidence: HIGH** — reproduced 3 separate ways, isolated to the specific export+return
combination via 2 further minimal reproductions, and confirmed a working control case that DOES
fail correctly.

**Consequence for this audit:** Gate 2 as literally prescribed (`node --check workflows/wave.js`)
provides ZERO assurance about `workflows/wave.js`'s syntactic validity — it will report PASS
(exit 0) regardless of whether the file is valid. **This exit-0 result must NOT be read as
confirmation the file is syntax-clean.** Per my brief's own instruction — "A PASS on a check you
did not prove falsifiable is not a PASS — say so instead" — I am saying so: **Gate 2's PASS is
not trustworthy and should not be relied on for `workflows/wave.js` going forward.**

**This is not a W7 regression** — no W7 step touched `workflows/wave.js` (confirmed: it is absent
from `git diff --stat`, and its checksum was unchanged all session except during my own
mutate/restore probes). The defect predates this wave (shipped in `686084d`, "ship the wave
fan-out as a plugin workflow"). It is a pre-existing gate-integrity gap that this run's `[gates]`
list should either replace (e.g. `node --experimental-vm-modules --check` forcing ESM, or convert
`workflows/*.js` files to `.mjs` so the extension disambiguates module type unambiguously) or
supplement with an actual functional smoke-test before trusting it as a regression gate again.
Filing this as a standing gap for root/engineer, not a REDO trigger for W7's three steps (none of
which touched this file).

### F2 — Assertion 1's literal brief wording is a weaker check than intended (LOW)

**Hypothesis:** `grep -n 'Workflow' agents/conductor.md` (the brief's literal instruction) is not
narrow enough to actually falsify "Workflow present specifically in the `tools:` frontmatter
line" — `Workflow` appears ~12 times in unrelated body prose.

**Falsification:** see Probe 1 above — removing `Workflow` from ONLY the `tools:` line left the
brief's literal grep still matching 12 times, a false PASS on the actual claim being tested.

**Confidence: HIGH** (directly reproduced).

**Consequence:** Not a defect in the wave's diff (I used the narrower `grep -n '^tools:'` check
and confirmed the real claim holds — Assertion 1 is TRUE). Flagging only so a future central-
verify brief tightens this specific assertion's wording to `grep -n '^tools:' agents/conductor.md`
so the check is self-falsifying as written next time.

## Open questions

- Disk headroom: 9.3Gi available / 98% capacity at `.` — `df-guard.sh --min=12` fails. Not
  blocking for this wave's two gates (neither invokes cargo), but the next cargo-invoking wave
  in this run will hit it immediately. Independently corroborated by the concurrent `L7`
  central-verify auditor's own report.
- The parallel `L7-*` report set in `.shepherd/runs/v645/reports/` (coder + auditor reports for
  the identical three-file deliverable, under an older/parallel lane-naming scheme) is a
  dispatch-planning duplication, already self-flagged by W7-S1 and W7-S3's own INSIGHTS entries.
  Both the `L7` central auditor and this `W7` central audit independently reached the same PASS
  verdict on the same three files — corroborating, not conflicting — but the duplicate dispatch
  itself is unresolved and worth a conductor-side fix before the next wave.

## VERDICT per step

| Step | File | Verdict |
|---|---|---|
| W7-S1 | `commands/spawn.md` | **PASS** |
| W7-S2 | `skills/harness/SKILL.md` | **PASS** |
| W7-S3 | `skills/shepherd/SKILL.md` | **PASS** |

## Explicit assertions (all 5 required by the dispatch brief)

| # | Assertion | Result | Confidence |
|---|---|---|---|
| 1 | `Workflow` still in `agents/conductor.md`'s `tools:` frontmatter line | **TRUE** | HIGH |
| 2 | `WORKFLOW-VEHICLE-PROBE` PRESENT branch still exists in `skills/shepherd/SKILL.md` | **TRUE** | HIGH |
| 3 | Git-custody sentence (line 89 at HEAD / 91 in working tree) unchanged | **TRUE** | HIGH |
| 4 | No new text asserts what `teammateMode: "auto"` resolves to | **TRUE** | HIGH |
| 5 | `git diff --stat` scoped ONLY to `commands/spawn.md`, `skills/harness/SKILL.md`, `skills/shepherd/SKILL.md` | **TRUE** | HIGH |

## Gate results

| Gate | Command | Exit | Trustworthy? |
|---|---|---|---|
| 1 | `bin/shepherd lint` | 0 | YES — proven falsifiable (Probe 6) |
| 2 | `node --check workflows/wave.js` | 0 | **NO — proven NOT falsifiable for this file (F1)** |

## Overall verdict

**PASS — no REDO required for W7-S1/S2/S3.** All three steps landed correctly, all five explicit
assertions hold TRUE under falsifiable verification, no out-of-scope writes, no regression in
`agents/conductor.md`'s `Workflow` grant, no accidental resolution of the `auto` teammateMode
question, no accidental disturbance of the root-exclusive git-custody sentence. One HIGH finding
(F1) that is NOT a W7 regression but that root should act on before trusting Gate 2 again for
`workflows/wave.js`; one LOW finding (F2) is a brief-wording note only, does not change the
Assertion 1 verdict.

- Agent ID + timestamp: auditor-W7-central-verify @ 2026-08-13T22:15:00Z
