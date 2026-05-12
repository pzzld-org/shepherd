# Auditors are read-only — applying fixes is a process violation

Auditors REPORT findings. They do NOT apply fixes. If an auditor catches a bug and patches it inline, that is a process violation regardless of how correct the patch turns out to be.

## Why

Auditors are read-only by design because:

- **Independence of judgment** — once an auditor has touched the code, its subsequent assessment of that code is biased.
- **Scope safety** — auditors run in parallel with each other and with coders. If an auditor patches a file another coder is editing, the patches collide.
- **Reproducibility** — audit findings should be reproducible from the report. If the auditor patched the issue away, future review can't see what was wrong.
- **Process clarity** — the conductor dispatches hot-fix coders to address findings. That separation is the audit trail.

## What auditors DO

| Action | OK |
|---|---|
| Read source files via `Read` | ✅ |
| Run greps via `Bash` (read-only) | ✅ |
| Query datastores via MCP (read-only queries) | ✅ |
| Read git history | ✅ |
| Read deploy state | ✅ |
| Write audit reports to `{paths.reports}/<date>-audit-<concern>.md` | ✅ — this is the auditor's only write |
| File GH issues for findings via GH MCP | ✅ — issue creation is part of the report |

## What auditors DO NOT

| Action | NOT OK |
|---|---|
| Edit source files | ❌ — that's a coder's job |
| Edit config files | ❌ |
| Run migrations | ❌ |
| Apply fixes inline | ❌ — even if "obviously correct" |
| Modify other auditors' reports | ❌ |
| Update memory or doctrines | ❌ — that's the planter or conductor |
| Touch the project's state in any non-report way | ❌ |
| Run gates from a worktree | ❌ — see `WORKTREE-DRIFT` halt below |

## Where auditors RUN

Auditors invoke gates (`cargo`, `pnpm`, `pytest`, etc.) AT SPRINT ROOT —
the path where `shepherd.toml` lives. Running a gate from inside a coder
worktree picks up that worktree's uncommitted changes and produces
FALSE-CRITICAL findings.

The brief carries `[SPRINT-ROOT]` and `[SPRINT-BRANCH]` lines. The auditor
verifies on entry:

```bash
HEAD=$(git rev-parse HEAD)
expected=$(git -C "$SPRINT_ROOT" rev-parse "$SPRINT_BRANCH")
[[ "$HEAD" == "$expected" ]] || halt "WORKTREE-DRIFT — auditor must be at sprint root, not a worktree"
```

Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5 §2).
A Wave-1 dependency-topology auditor reported "axiom-node serve+native
FAILS at HEAD with 14 E0308 errors" and recommended an immediate hot-fix
lane. Conductor verified directly at sprint root: GREEN. The auditor was
running gates from a coder worktree where pending Lane 4b changes hadn't
been committed yet. Cost: ~30 minutes of conductor side-quest before
classifying as FALSE-ALARM.

Every gate finding cites the gate's `Finished` or `error:` line verbatim
as evidence. Bare claims ("compile failed") are conjecture, not findings.

## When an auditor finds something the auditor "knows how to fix"

The right response: file the finding in the audit report with severity + recommendation. The conductor reads the report, decides whether to dispatch a hot-fix coder, and that coder (which IS allowed to edit code) applies the fix.

```
[auditor's report]
## Finding A-3 (HIGH) — DriftCircuit::tick double-borrows state

Location: crates/circuits/src/drift.rs:142

Pattern: `&mut state` borrowed at line 142 then re-borrowed at line 168.
Compiles today because line 168's borrow scope ends at line 175, but the
extension proposed in this sprint's Lane 2 will extend that scope past
line 142's use.

Recommendation: refactor to extract `let snapshot = state.clone()` at line
142 and operate on the clone for the read-only portion.

Suggested hot-fix lane: file scope `crates/circuits/src/drift.rs` only;
acceptance grep `rg -n 'state\.borrow_mut' crates/circuits/src/drift.rs → 1`.
```

The conductor reads this and dispatches:

```
Agent({
  description: "@coder: hot-fix A-3 (drift.rs double-borrow)",
  model: "sonnet",
  prompt: "<coder system prompt>\n\nTASK BRIEF: <brief built from auditor's recommendation>"
})
```

## Why exceptions are still violations

A canonical exception that has come up: "the auditor caught a 1-line typo in the brief, of course it's safe to fix inline".

It's still a violation. Reasons:

- The typo lives in the brief — that's a conductor-authored artifact. The auditor patching it skips the conductor's review.
- The signal "auditors apply fixes" once accepted erodes the read-only contract for everything else.
- The cost of dispatching a 1-line hot-fix coder is trivial. The cost of normalized auditor-edits is process drift.

If a 1-line typo is genuinely below hot-fix-coder threshold, the conductor can fix it inline (the conductor IS allowed to edit `.md` files and briefs). The auditor surfaces it; the conductor edits.

## Auditor-system-prompt enforcement

The auditor agent's system prompt (in `${CLAUDE_PLUGIN_ROOT}/agents/auditor.md`) includes:

> You are READ-ONLY. You do NOT call Edit, Write, or NotebookEdit. You do NOT run shell commands that modify state. Your tools are Read, Grep, Bash (read-only commands like git log, ls, rg, gh issue list), MCP query tools, and Write — Write is exclusively for your audit report at `{paths.reports}/<date>-audit-<concern>.md`. Any fix you would apply, file as a finding instead.

The conductor verifies the auditor's tool list at dispatch and rejects any auditor brief that grants write access outside the report path.

## See also

- `pattern-b-overlap.md` — auditors run concurrently with Wave 2 coders
- `chain-repair.md` — auditor findings can trigger seed amendments
