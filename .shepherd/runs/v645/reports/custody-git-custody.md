---
title: Empirical audit — teammate-conductor git custody boundary
date: 2026-08-13
auditor: shepherd:auditor
sprint: v6.4.5 (run v645)
concern: git-custody (custom probe, root-dispatched)
mode: custody-probe (not a standard close/regression/wave-review mode)
methodology: superpowers:systematic-debugging (falsify-don't-confirm) + DF-68
  probe-falsifiability (every DENY paired with an ALLOW from the SAME instrument,
  and vice versa)
---

## Claim under test

"Lane commit and lane-branch push are the conductor's; only CROSS-LANE integration
(rebase / merge / cherry-pick onto dev, `branch -d`, worktree add/remove/prune) is
`TEAMMATE-GIT-WRITE` and denied."

## Scope reviewed

Read-only. Ran entirely at sprint root (`/Users/jo3/src/fl03/shepherd`, HEAD=`v6.4.5`,
`git status --short` unchanged by this audit — confirmed before and after). All executable
tests ran against a THROWAWAY git repo + sqlite fixture under
`/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-test/`
(`setup.sh`, `run_matrix.sh`, `run_positive_controls.sh`, `mkpayload.py`,
`summarize.py`, raw per-invocation `results/*.{payload,out,err,exit}` files — 99
invocations total). The REAL guard scripts under `/Users/jo3/src/fl03/shepherd/hooks/scripts/`
were executed unmodified (read-only) against that fixture; nothing under
`/Users/jo3/src/fl03/shepherd` was written, staged, committed, or pushed. One read-only
`SELECT` was run against the REAL `.shepherd/shepherd.db` (no INSERT/UPDATE) to check the
`teammates.session_id` population — reported below as Finding 4.

Files not touched (per the stated write-collision warning), read only where citing
declared text: `agents/conductor.md`, `skills/shepherd/SKILL.md`. `commands/spawn.md` was
deliberately NOT opened (l7-substrate is editing it); one claim below (self-registration
at teammate boot) is sourced instead from this sprint's own `.shepherd/runs/v645/dogfood.md`
ledger (DF-12) and from `skills/context/scripts/cmd_teammate.sh`'s inline comments, both of
which were safe to read.

## Guards actually wired to `PreToolUse(Bash)`

Read `hooks/hooks.json` directly (not inferred). The `"matcher": "Bash"` block wires SIX
scripts, first-match-wins is NOT in effect — Claude Code fires ALL of them per Bash call and
ANY deny wins:

```
hooks/scripts/bash_guard.sh
hooks/scripts/teammate_git_guard.sh
hooks/scripts/coder_git_guard.sh
hooks/scripts/worktree_teardown_guard.sh
hooks/scripts/release_trigger_guard.sh
hooks/scripts/conductor_write_guard.sh
```

All six were tested. Matching logic read directly from source (file:line cited inline).

- **`teammate_git_guard.sh`** — the guard that actually implements the claim under test.
  Fires only when `session_id` matches a `teammates` row with `status NOT IN
  ('retired','crashed')` (lines 106-109). Verb detection (lines 90-91):
  ```
  FORBIDDEN_PATTERN='(^|[[:space:];|&])git[[:space:]]+(merge|rebase|cherry-pick)[[:space:]]?'
  FORBIDDEN_WORKTREE_PATTERN='(^|[[:space:];|&])git[[:space:]]+worktree[[:space:]]+(add|remove|prune)([[:space:]]|$)'
  ```
  Anything NOT matching one of these two patterns exits at the fast-path (line 92-96)
  **before the DB is even queried** — i.e. `add`/`commit`/`push`/`branch -d`/`reset --hard`
  never reach the teammate-detection logic at all; they pass regardless of who is running
  them.
- **`bash_guard.sh`** Check 1 (lines 60-68) — a DIFFERENT, narrower guard: denies `git
  commit` only when the INVOKING SHELL'S OWN `HEAD` (not a `-C <path>` target) is on a branch
  matching `^(agent-|lane-)`. Role-agnostic; not DB-driven.
- **`coder_git_guard.sh`** — denies git writes only for `role=coder` (resolved via a dispatch
  tag file, not session identity). Irrelevant to a teammate-conductor's own Bash calls unless
  it is itself tagged as a coder dispatch (never observed).
- **`worktree_teardown_guard.sh`** — denies `worktree prune` and BLANKET `worktree remove`
  (no `.worktrees/` path, or combined with `worktree list`) whenever `v_teammates_live` > 0,
  for ANY session (teammate or not). Explicitly ALLOWS a scoped `git worktree remove
  .worktrees/<slug>` — a materially different rule from `teammate_git_guard.sh`, which
  blocks ANY worktree remove (scoped or not) from a teammate.
- **`conductor_write_guard.sh`** — per its own v6.3.1 comment, git is deliberately NOT in its
  deny-list at all ("commits AND your lane's push are yours ... dispatching @worker for two
  git commands is wasteful"). Only Edit/Write and non-git FS mutation are denied.
- **`release_trigger_guard.sh`** — only fires on a `…-dev.N` branch token at/above
  `sprints_per_patch`; irrelevant to any command in this probe (none referenced a `dev.N`
  branch).

## Test matrix — real command strings through the real guards

Fixture: throwaway repo, HEAD=`v6.4.5` (sprint-root simulation), `.shepherd/shepherd.toml` +
`.shepherd/shepherd.db` (mirrors the real repo's canonical namespace layout exactly).
`teammates` table seeded with one **active** row (`session_id=sess-tm-l7`, mirroring a live
teammate-conductor for lane `l7-substrate`), one **retired** row, and one **unregistered**
"root" session — the same three-way split `hooks/tests/test_teammate_git_guard.sh` (the
guard's own test author) uses, so the fixture matches the guard's documented ground truth.
Lane worktree = `.worktrees/v645-l7-substrate`, lane branch = `agent-v645-l7-substrate`
(matches the REAL repo's observed naming: `git worktree list` shows all six live lanes on
`agent-v645-l<N>-<name>` branches).

Every invocation: JSON payload built by `mkpayload.py`, fed via `<` stdin redirection (never
a pipe) directly to `bash "$HOOKS/$guard"`, stdout/stderr captured to files, `$?` read
**immediately** after the subshell into its own file (never through `tail`/`head`). Full
per-invocation evidence lives at `.../custody-test/results/*.{payload,out,err,exit}`.

**Structural fact, stated up front because the task asked for "the guard's own exit code"
explicitly**: across all 99 invocations run for this audit (`sort -u` over every
`*.exit.txt` → `{0}` only), every guard exits **0** regardless of ALLOW or DENY — the Claude
Code PreToolUse hook contract signals the decision exclusively via stdout JSON
(`{"permissionDecision":"deny",...}` vs empty stdout for silent pass), confirmed by direct
read of `hooks/scripts/_lib.sh`: `emit_deny()`/`pass_silent()`/`emit_context()` all end in
`exit 0`. Stderr was empty in all 99 cases. Reading "DENY" off a nonzero exit code would be
categorically wrong for this instrument — the decision is in the JSON body, not `$?`.

### `teammate_git_guard.sh`, registered ACTIVE teammate (`session_id=sess-tm-l7`)

| # | Command | Exit | Decision | Halt code |
|---|---|---|---|---|
| A1 | `git -C .worktrees/v645-l7-substrate add -A` | 0 | **ALLOW** (silent) | — |
| A2 | `git -C .worktrees/v645-l7-substrate commit -m x` | 0 | **ALLOW** (silent) | — |
| A3 | `git -C .worktrees/v645-l7-substrate push origin agent-v645-l7-substrate` | 0 | **ALLOW** (silent) | — |
| D1 | `git rebase v6.4.5` | 0 | **DENY** | TEAMMATE-GIT-WRITE |
| D2 | `git merge agent-v645-l7-substrate` | 0 | **DENY** | TEAMMATE-GIT-WRITE |
| D3 | `git cherry-pick abc1234` | 0 | **DENY** | TEAMMATE-GIT-WRITE |
| D4 | `git branch -d agent-v645-l7-substrate` | 0 | **ALLOW** (silent) — **unexpected, see Finding 1** | — |
| D5 | `git worktree add .worktrees/v645-l7-substrate main` | 0 | **DENY** | TEAMMATE-GIT-WRITE |
| D6 | `git worktree remove .worktrees/v645-l7-substrate` | 0 | **DENY** | TEAMMATE-GIT-WRITE |
| D7 | `git push --force` | 0 | **ALLOW** (silent) — **unexpected, see Finding 2** | — |
| D8 | `git reset --hard` | 0 | **ALLOW** (silent) — **unexpected, see Finding 3** | — |
| D9 (added) | `git push origin v6.4.5` (shared sprint branch, NOT the lane's own) | 0 | **ALLOW** (silent) — **see Finding 2** | — |

Verbatim DENY message (D2, representative — D1/D3/D5/D6 identical shape, different
`Command`/`Verb(s)` lines):
```
[shepherd] TEAMMATE-GIT-WRITE — teammate may not integrate to the dev branch.
  Session    : sess-tm-l7
  Command    : git merge agent-v645-l7-substrate
  Verb(s)    : git merge
Integration is ROOT-EXCLUSIVE (LANE-INTEGRATE seam). Teammate-conductors own
their lane worktree: git add + git commit + git push (their OWN lane branch).
Merging, rebasing, cherry-picking onto dev, and worktree add/remove/prune are
root-tier decisions — they require a diff review or explicit root orchestration.
Action: surface SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE) and
describe the integration you need. Root will execute LANE-INTEGRATE.
See skills/shepherd/references/pipeline.md §CLOSE-FINALIZE + agents/shepherd.md LANE-INTEGRATE.
```

### PROBE-FALSIFIABILITY — positive/negative controls (DF-68)

Every ALLOW above is paired with a DENY from the exact same instrument+session (D1/D2/D3/D5/
D6 above), proving the guard is live and capable of returning DENY in this fixture — the ALLOW
rows for A1-A3/D4/D7/D8/D9 are not silence from a broken harness. Additionally:

- **Same command set through the NON-teammate ("root") session** (`sess-root-01`, no
  matching `teammates` row): ALL 11 commands, including D1/D2/D3/D5/D6, returned ALLOW
  (silent). This is the guard's documented scope — it targets registered teammates only —
  and confirms the DB lookup itself is reachable and discriminating (a session either does or
  does not match), not merely always-pass.
- **Same command set through the RETIRED-teammate session** (`sess-tm-retired`,
  `status='retired'`): ALL 11 commands ALLOW (silent) — confirms the `status NOT IN
  ('retired','crashed')` filter is live, matching the guard's own documented rule.
- **`bash_guard.sh` positive control**: `git commit -m x` with HEAD genuinely checked out on
  `agent-v645-l7-substrate` (not `-C`-scoped — the actual shell HEAD) → **DENY**
  (`"[shepherd] git commit BLOCKED — HEAD is on agent lane 'agent-v645-l7-substrate'."`).
  `git status` under the identical HEAD → **ALLOW** (silent). Confirms this guard is a live,
  working instrument for its own (narrower, cwd-branch-based) rule — it is simply not the
  mechanism that governs `-C`-scoped lane commits, which never touch the shell's own HEAD.
- **`coder_git_guard.sh` positive control**: tagged the session's `tool_use_id` as a
  `role=coder` dispatch, then `git commit -m x` → **DENY** (`CODER-GIT-WRITE`); `git status`
  → **ALLOW**. Confirms the guard fires correctly for its actual population (role=coder), even
  though it never fires for a teammate-conductor's own turn (role resolves to `conductor`
  there, by design).
- **`worktree_teardown_guard.sh` positive control**: `git worktree prune` → **DENY**
  (`WORKTREE-TEARDOWN-LIVE`, reason=`prune`); a blanket sweep
  (`git worktree list | grep worktrees | xargs -n1 git worktree remove`) → **DENY**
  (reason=`blanket-remove`); `git worktree remove badpath-no-dotworktrees-prefix` → **DENY**
  (reason=`blanket-remove`, no `.worktrees/` prefix). All three confirm the guard is live and
  discriminates scoped-vs-blanket correctly — the scoped D6 ALLOW in the main matrix is its
  documented correct behavior, not a gap in this guard specifically.
- **`conductor_write_guard.sh` positive control**: an `Edit` call (not git) under the same
  teammate session with `SPRINT_OPEN` genuinely true (verified via the same `teammates` row)
  → **DENY** (`CONDUCTOR-WRITE-DENIED`). Confirms the guard's `SPRINT_OPEN` leg is genuinely
  reached in this fixture, so its SILENT-PASS on every git command in the main matrix is the
  documented v6.3.1 "git is not blocked here" design, not a fixture artifact letting it exit
  early for an unrelated reason.

No DENY was asserted anywhere in this report without a paired ALLOW from the same
instrument, and no ALLOW was asserted as meaningful without a paired DENY proving the
instrument can fire. Where a guard returned only ALLOW for the whole main matrix
(`bash_guard.sh`, `coder_git_guard.sh`, `worktree_teardown_guard.sh`,
`conductor_write_guard.sh`, `release_trigger_guard.sh`), a dedicated positive control was run
per guard (above) rather than treating the null result as a finding on its own.

## DECLARED vs OBSERVED

Two prose sites contradict each other on `push`, as flagged by the brief:

**`agents/conductor.md`** (four sites, all consistent with each other):
- L79: "...INTEGRATION AUTHORITY (cross-lane rebase/merge deferred to root; you commit and
  push your OWN lane branch — `TEAMMATE-GIT-WRITE` covers cross-lane integration, not your
  lane commit/push)."
- L160 (Hard prohibition #1): "**Commits AND your lane-branch push are yours** — stage +
  commit your lane and push your OWN lane branch directly (`git -C <path>`) ... cross-lane
  rebase/merge/cherry-pick and worktree lifecycle stay root's (#3)."
- L162 (Hard prohibition #3): "In-lane commits and your lane-branch push are yours (#1);
  `TEAMMATE-GIT-WRITE` covers cross-lane integration (rebase/merge/cherry-pick onto dev) +
  worktree add/remove/prune, NOT your lane commit/push."
- L187 (Side-effect boundary): "Cross-lane git integration (rebase/merge/cherry-pick onto
  dev, `branch -d`, worktree add/remove/prune) and the registry lock are root-exclusive after
  all lanes close (`TEAMMATE-GIT-WRITE`, ...); you commit and push your OWN lane branch
  (#222)."

**`skills/shepherd/SKILL.md`** L89: "Git custody is root-exclusive: a teammate that runs
`git rebase`/`merge`/`push`/`worktree` halts `TEAMMATE-GIT-WRITE`..." — lists `push` as a
blocked verb, contradicting all four `conductor.md` sites above.

**Verdict, resolved by what the guard does, not by which doc reads more authoritative:**

- On `push`: the runtime implements **`conductor.md`'s** model, not
  `skills/shepherd/SKILL.md:89`'s. `teammate_git_guard.sh`'s own source comment (lines 12-30)
  explicitly documents the #222 rationale for allowing push, `push` never appears in
  `FORBIDDEN_PATTERN` (line 90), and A3/D7/D9 above all empirically ALLOW — including a push
  that is neither the lane's own branch (D9) nor a plain push (D7, `--force`).
  `skills/shepherd/SKILL.md:89` is **not what is shipped**; it is stale/wrong relative to the
  guard `teammate_git_guard.sh` actually enforces.
- On `branch -d`: **neither** doc's implementation claim fully holds. `conductor.md:187`
  explicitly lists `branch -d` alongside rebase/merge/cherry-pick/worktree as root-exclusive
  — but D4 above shows the guard does not check `branch` at all (it is absent from both
  `FORBIDDEN_PATTERN` and `FORBIDDEN_WORKTREE_PATTERN`). So even the doc identified as
  "the one the runtime implements" is only PARTIALLY implemented — a mechanical gap in
  `conductor.md`'s own claim, not a second doc/runtime mismatch.
- `git push --force` and `git reset --hard` are not addressed as special cases by EITHER doc
  or by any of the six wired guards; both pass as ordinary, unrestricted git for a registered
  teammate session (D7, D8).

## Findings

### Finding 1 — HIGH: `git branch -d <lane>` is declared root-exclusive but unenforced

**Hypothesis:** `teammate_git_guard.sh`'s verb-detection regex does not include `branch`, so
a teammate-conductor deleting a lane branch passes silently despite `conductor.md:187`'s
explicit inclusion of `branch -d` in the root-exclusive list.

**Falsification:** Source read of `FORBIDDEN_PATTERN`/`FORBIDDEN_WORKTREE_PATTERN` (lines
90-91) confirms `branch` is absent from both. Empirical: D4 (`git branch -d
agent-v645-l7-substrate`) under the registered-active-teammate session → ALLOW (silent, exit
0). Positive control on the same session/instrument: D2/D5/D6 (merge/worktree add/worktree
remove) → DENY. The guard demonstrably can deny for this session; it simply never evaluates
`branch -d` as a candidate at all (the fast-path at lines 92-96 exits before the DB lookup
even runs for this verb).

**Confidence:** HIGH — direct source read plus two-sided empirical confirmation.

### Finding 2 — HIGH: `git push` has zero destination/flag awareness — not scoped to "own lane branch"

**Hypothesis:** The guard's push exemption is implemented as "push is simply never
inspected," not as "push is inspected and permitted only when the target is the teammate's
own lane branch" — so a force-push or a push to the shared sprint branch is indistinguishable
from a legitimate own-lane publish.

**Falsification:** A3 (`push origin agent-v645-l7-substrate`, the lane's own branch), D7
(`push --force`, no destination named), and D9 (`push origin v6.4.5`, the SHARED sprint
branch — never the teammate's own lane) all produced the identical outcome: ALLOW, silent,
exit 0, empty stderr. Source confirms why: `push` does not appear anywhere in
`FORBIDDEN_PATTERN` (line 90) — there is no destination-matching logic to have distinguished
D9 from A3, and no flag-matching logic to have distinguished D7 from a plain push.

**Confidence:** HIGH — the three cases are byte-for-byte identical decisions from the same
guard/session, and the source contains no code path that could have differentiated them.

### Finding 3 — MEDIUM: `git reset --hard` has no coverage in any wired guard for a teammate/conductor turn

**Hypothesis:** None of the six `PreToolUse(Bash)` guards treat `reset --hard` as a checked
verb for a teammate-conductor's own turn (as opposed to a `role=coder` dispatch, where
`coder_git_guard.sh`'s `WRITE_VERBS` list — `hooks/scripts/coder_git_guard.sh:162` — does
include `reset`).

**Falsification:** D8 (`git reset --hard`) → ALLOW across all six guards for the registered
teammate session. `conductor_write_guard.sh`'s FS_WRITE_PATTERN (line 170) checks
`rm|mv|sed -i|touch` only, never git; `teammate_git_guard.sh`'s pattern (line 90) omits
`reset`; `bash_guard.sh` only inspects `git commit`. Rated MEDIUM rather than HIGH because
neither `conductor.md` nor `skills/shepherd/SKILL.md` declares `reset --hard` as a
restricted verb in the first place (unlike `branch -d`/`push`, which ARE declared and then
diverge from the runtime) — this is an absent guard for an UNDOCUMENTED expectation, not a
guard contradicting a stated contract.

**Confidence:** MEDIUM (source read is HIGH-confidence; the severity judgment rests on the
docs genuinely being silent on this verb, which is a negative claim I cannot exhaustively
prove beyond grepping the two cited files for "reset").

### Finding 4 — CRITICAL (systemic, corroborated): the teammate-detection mechanism itself is non-functional in the LIVE v6.4.5 sprint right now, independent of which verbs the regex covers

**Hypothesis:** `teammate_git_guard.sh` gates entirely on `SELECT count(*) FROM teammates
WHERE session_id='${SESSION}' AND status NOT IN ('retired','crashed')` (lines 106-109). If no
currently-registered teammate row carries a populated `session_id`, this guard is fail-open
for EVERY real teammate in this sprint, for EVERY verb it would otherwise catch (rebase,
merge, cherry-pick, worktree add/remove/prune included) — not just the gaps in Findings 1-3.

**Falsification:** Read-only query against the REAL, currently-running
`/Users/jo3/src/fl03/shepherd/.shepherd/shepherd.db`:
```
sqlite3 .shepherd/shepherd.db "SELECT count(*), count(NULLIF(session_id,'')) FROM teammates;"
→ 6|0
```
All six currently-registered teammate rows (`shepherd-conductor-v645-l1-engine` through
`l6-guards`, `shepherd-engineer-v645`) have an EMPTY `session_id`. A string-equality WHERE
clause against an empty column can never match a real Claude session UUID, so
`TEAMMATE_COUNT` is 0 for any real teammate's actual session — the guard takes the
"pass_silent — not a registered teammate" branch (line 111-114) for every git command that
teammate ever runs, regardless of verb.

This is independently corroborated, not a novel isolated finding: this sprint's own
`.shepherd/runs/v645/dogfood.md` already logs it as **DF-12, HIGH, status FIX-THIS-RUN**
(line 71): root cannot learn a spawned teammate's own session uuid at spawn time, and
`commands/spawn.md §Register teammates` documents `--session` as optional with native-Agent
teammates stated to "boot fresh and do NOT self-register" (cited from the dogfood ledger, not
independently re-read from `commands/spawn.md` itself per the write-collision avoidance
above). `git log --oneline -- hooks/scripts/teammate_git_guard.sh
skills/context/scripts/cmd_teammate.sh` shows neither file has been touched since the
v6.3.9-era commits, i.e. as of this audit DF-12 has not yet landed a fix on this branch.

**Confidence:** HIGH for the DB state (directly queried, read-only, against the real running
project registry, not the synthetic fixture) and for the guard's WHERE-clause mechanics
(direct source read). The DF-12 corroboration is HIGH-confidence as an independent
cross-check (same root cause, same symptom, logged by a different audit pass earlier in this
same sprint) but is cited, not re-derived from `commands/spawn.md` directly, per the
write-collision constraint.

**Impact on this report's other findings:** Findings 1-3 describe gaps in WHICH verbs the
regex covers. Finding 4 describes a gap in WHETHER the guard ever reaches that regex for a
real session at all, in the sprint currently executing. Both are real and independent; Finding
4 is the more severe of the two because it silently defeats the parts of the contract that ARE
correctly regex-covered (D1/D2/D3/D5/D6 in the matrix above) whenever the session triggering
them is a genuine live teammate rather than my seeded fixture row.

## Verifications (claims checked and NOT falsified — i.e. confirmed as declared/observed)

1. `git -C <lane-worktree> add -A` / `commit -m x` / `push origin <lane-branch>` are ALLOWED
   for a registered active teammate — matches `conductor.md`'s declared lane-custody
   exemption (assuming Finding 4 is resolved so the guard actually recognizes the session).
2. `git rebase`, `git merge`, `git cherry-pick`, `git worktree add`, `git worktree remove` are
   DENIED with halt code `TEAMMATE-GIT-WRITE` for a registered active teammate — matches the
   claim under test for these five verbs specifically.
3. A retired teammate and a non-teammate ("root") session are correctly exempted from
   `teammate_git_guard.sh` entirely (by design — it is a teammate-only guard) — confirmed
   both status filters are live, not merely present in source but dead in practice.
4. `worktree_teardown_guard.sh` correctly distinguishes a scoped single-lane
   `git worktree remove .worktrees/<slug>` (ALLOW) from a blanket sweep or bare `prune`
   (DENY, `WORKTREE-TEARDOWN-LIVE`) — this guard's own narrower contract is intact and its
   ALLOW on the scoped case in the main matrix is correct, not a gap.
5. `bash_guard.sh`'s Check 1 (`git commit` while shell HEAD is literally on an
   `agent-*`/`lane-*` branch) is a live, functioning, DIFFERENT mechanism from
   `teammate_git_guard.sh` — confirmed it does not fire for `-C`-scoped lane commits (which
   never move the invoking shell's own HEAD), and does fire when HEAD itself is on a lane
   branch. Both behaviors match its documented scope exactly.

## Open questions

- Whether a teammate self-registers `--session=$CLAUDE_SESSION_ID` at boot via
  `commands/spawn.md` (which would resolve Finding 4) was deliberately NOT verified
  first-hand in this pass, to avoid touching a file under concurrent edit by l7-substrate. The
  DF-12 ledger entry (already logged, HIGH, FIX-THIS-RUN, in this same sprint) states no such
  self-registration currently happens; this report treats that as sourced-not-derived
  evidence, one level less direct than the rest of this report's claims.
- Whether `git push --force-with-lease` or other push-flag variants are handled any
  differently from plain `push`/`push --force` was not separately tested — the source
  (`FORBIDDEN_PATTERN`, teammate_git_guard.sh:90) contains no flag-matching for `push` at
  all, so by construction every push variant should behave identically to D7/D9 above, but
  this was not independently re-run per flag.

## Reproducing this audit

```
/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-test/setup.sh <repo-path>
/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-test/run_matrix.sh
/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-test/run_positive_controls.sh
python3 /private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/custody-test/summarize.py
```
All raw per-invocation payload/stdout/stderr/exit-code files are under
`.../custody-test/results/`. Nothing under `/Users/jo3/src/fl03/shepherd` was modified to
produce this report.

## AUDITOR REPORT

- Concern: git-custody (custom probe)
- Mode: custody-probe
- Guards inspected: 6 (all `PreToolUse(Bash)` entries in `hooks/hooks.json`)
- Command strings tested: 11 base + 1 added (D9) × up to 3 session contexts each, plus 9
  dedicated positive-control invocations = 99 total guard invocations
- Findings: CRITICAL=1, HIGH=2, MEDIUM=1, LOW=0
- Verifications (confirmed, not falsified): 5
- Open questions: 2
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/custody-git-custody.md
- Agent ID + timestamp: shepherd:auditor @ 2026-08-13T17:10:00Z
