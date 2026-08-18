# v6.4.6 carry-forward — items for v6.4.7

Recorded by root during v6.4.6 execution. Every item was measured, not inferred, and each
names where the evidence lives. Nothing here is a nice-to-have: each is either a gate that
cannot fail, a defect this sprint proved real but scoped out, or a coordination hazard that
cost this run measurable time.

## 0. The SEED-GATE was never enforced on this sprint's own seed — HIGH

`shepherd seed verify .shepherd/runs/v646/seed.md` HARD-fails:

```
HARD  footprint 393 lines > cap 200 (kind=patch-seed)
FAIL: 1 hard failure(s), 0 warning(s)
```

The seed is nonetheless marked `status: ready-for-engineer`. Confirmed independently by the
harness lane. The cap was NOT tuned to accommodate it and the seed was NOT relabelled —
turning a red gate green by editing a label is the failure class this sprint exists to end.

The real question for v6.4.7 is which of two things is true, and it needs the operator:
either a 10-deliverable, 5-lane seed is not a `patch-seed` and the kind vocabulary is too
coarse, or the seed should carry the directive and leave the evidence in `mesh.md`, which is
the artifact for evidence. Do not resolve it by moving the number.

## 1. Nothing asserts the installed binary matches the built one — HIGH

Found independently by the distribution and harness lanes, from opposite directions, which
is why it is stated once here with two witnesses.

`~/.cargo/bin/shepherd` went stale TWICE in one session. Hooks invoke the bare name
`shepherd` through PATH, so a committed fix has no effect on live behaviour until
`cargo install --path crates/cli --locked --force`. The second incident silently blocked
five dispatched coders across four lanes — 18+ tool calls, zero files written, every one
returning a bare `BLOCKED` — because the installed binary predated the subagent-tool-call fix.

**`shepherd --version` cannot detect this.** Stale and fixed both print `shepherd-cli 6.4.6`.
Only the build timestamp against the commit log exposes it.

v6.4.6 addresses the diagnostic half: `shepherd doctor` now reports resolved path,
native-versus-launcher, and skew against the checkout. What is still missing is a GATE that
fails when the installed binary is older than the working tree, so the condition cannot
recur silently.

## 2. Write-scope narrowing is unavailable on Claude — MEDIUM

`SubagentStart` now records dispatched agents (v6.4.6), so role-scoped rules enforce. But no
host can declare a write scope — Claude Code has no mechanism to attach a `shepherd_dispatch`
block to an Agent call — so the synthesized binding records `**`. Identity binding and role
enforcement work; scope NARROWING does not.

That means the file-disjointness the multi-lane model rests on is enforced by brief, not by
gate. It held this sprint because the conductors honoured it, which is not the same as it
being enforced. See `crates/cli/src/cmd/native_hook.rs`.

## 3. Codex has no trusted spawn-to-child correlation — MEDIUM

`native_hook.rs` deliberately refuses Codex `SubagentStart`/`SubagentStop`, and
`crates/cli/tests/codex_hook_cli.rs:199-259` pins the refusal. v6.4.6 deliberately did NOT
delete it: fabricating correlation would mint the shadow identities `dispatch_cli.rs:199`
exists to prevent, and because `SubagentStop` routes errors to `block()`, registering it
would have blocked every Codex subagent stop event in the name of parity.

The real work is a correlation contract from the host. Until then the harness-parity table
carries it as a documented limitation, which is honest rather than padded.

## 4. Lanes should get their own git worktrees — MEDIUM

Raised by the distribution lane after root commits invalidated every in-flight coder's pinned
base simultaneously. With four lanes against one shared tree that is the default outcome of
any root commit, not a rare race. Cost on the first occurrence: five agents, ~240k tokens,
zero files written.

Deferred in v6.4.6 on disk grounds and the reasoning should be recorded: `target/` is 17G
against ~104 GiB free, so four worktrees would have consumed most of the operator's stated
100 GiB budget. A shared `CARGO_TARGET_DIR` across worktrees would resolve that, at the cost
of serializing cargo builds on the target lock. That trade is the design question.

The interim mitigation, now the run's rule, is the distribution lane's drift test:
`git diff --stat <briefed-base>..HEAD -- <that coder's own file scope>`, where a non-empty
diff is only drift if content the coder did NOT write replaced content it DID.

The general rule this run arrived at the hard way, after root disrupted lane work twice
(`git add -A` sweeping in-flight coder files, `git stash -u` splitting a coder's edit into
two complementary partial states) and the distribution lane did the same thing from the
other seat an hour later:

> On a shared worktree, any operation that reverts or stages state you did not author is
> unsafe regardless of which seat runs it, and falsification belongs to whoever currently
> owns the file.

Both recoveries were verified byte-for-byte and nothing was lost, but that was luck, not
process. A clean-tree baseline belongs in a throwaway clone; a fail-on-purpose edit waits
for the auditor.

## 4b. GATE-CAN-FAIL, as written, induces destructive edits on a shared tree — HIGH

The fourth instance of the shared-worktree class was caused by the sprint's OWN core
discipline, which makes it the most important one to fix.

GATE-CAN-FAIL requires every gate be shown to fail on purpose. The natural way a coder
produces that evidence is to revert the file under test, capture the red, and restore:

```
git checkout -- <the live file>     # capture red, then restore
```

On a worktree four lanes share, that reverts an in-flight file for as long as the cycle
takes, and a botched restore loses the work outright. The config lane identified it in its
own brief before it caused damage, and correctly declined to intervene mid-cycle on the
grounds that re-dispatching while a coder may be holding the file is how a recoverable state
becomes a real loss.

It also makes the tree unreadable from outside. Root sampled `loader.rs` at 542 lines
mid-revert; the conductor sampled it pristine at 415 lines minutes later; the finished file
is 576. All three readings were correct at the instant taken, and any two of them compared
naively suggest lost work.

**The fix is procedural and belongs in the next seed alongside GATE-CAN-FAIL itself:**
falsification runs against a COPY under `/tmp`, never `git checkout` on a live file. State
it as part of the requirement, because a discipline that demands evidence without naming a
safe way to produce it will keep teaching agents the unsafe way.

Corollary for anyone reading a shared tree: a single `git status` or `cargo fmt --check`
sample is a snapshot of a moving target, not a fact about a lane's work. Attribute from
artifacts and from the owning lane, not from one reading.

## 5. A refusal that never reaches the dispatching lead reads as incompetence — MEDIUM

Harness lane's finding, and it generalizes past this sprint. A worker spent 49 tool calls and
253k tokens retrying against a guard denial and reported the single word `BLOCKED`. From the
outside that is indistinguishable from a flaky agent. The defect disguised itself as model
failure twice in one session.

Worth a gate of the shape the harness lane proposed: assert that a teammate-shaped
`PreToolUse` payload reaches a REAL verdict — allow or deny — rather than an unresolved
fail-open. That check would have caught the entire v6.4.6 dispatch-ledger class on day one.

## 6. `version-bump.py` has no classification for prose version surfaces — LOW

A single literal `v6.4.6` in `docs/cargo-distribution.md` turned two gates red at once:
`version-bump.py check` (rc=2, `unclassified 6.4.6 version surface`) and the Cargo publisher
recovery contract that shells out to it. Resolved in v6.4.6 by removing the version from the
prose. The general question is whether documentation should be allowed to carry a
version-specific statement at all, and if so, how the tool rewrites it on bump.

## 6b. Pin tests and helpers against a SYNTHETIC version, never the current release — HIGH

Three independent coders, in three unrelated files, each wrote the current release literal
into a file `version-bump.py` scans, and each time it reddened TWO gates because
`test-cargo-publish.py` shells out to it:

- `docs/cargo-distribution.md:79` — a transitional prose note
- `scripts/lib/release-package-names.sh:104` — `local pinned_version='6.4.6'`
- a third in the same package-name work

The tool behaved correctly every time. The pattern is that "write the version you are
working on into the thing you are writing" is a completely natural reflex and nothing warns
you until a gate fires several steps later, in a file you did not touch.

The distribution lane's rule, which belongs in the next seed rather than in a review comment:

> In tests and helpers, pin against a SYNTHETIC version (`1.2.3`), never the current release.

It is strictly better ground truth — it proves the logic is version-agnostic instead of
agreeing with today's number by accident — and it never needs editing at bump time.

## 7. Deliberately still out of scope

- The 20 open SQL-injection and guard issues (#284-#298). Real, not on the delivery chain.
- Retiring the remaining tracked `.py` files. `scripts/version-bump.py` is load-bearing on
  the release path this sprint could not destabilize. The operator has since restated the
  preference for Rust-native tooling, so this is the natural v6.4.7 target.
- `crates/cli/tests/wave_b1_status_handoff_cli.rs` flake. A self-contending SQLite handle was
  corrected in v6.4.6, but the failure was never reproduced across five clean full-workspace
  runs, so it is a corrected hazard rather than a demonstrated repair. If it recurs, it is
  open again.
