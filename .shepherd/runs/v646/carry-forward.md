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

## 0b. `required-features` targets are silently skipped, and the gate never noticed — HIGH

Fixed in v6.4.6 (`04c500a` adds a feature-gated step to `scripts/gate.sh`), recorded because
the PATTERN will recur and because the scale is worth stating plainly.

`cargo test --workspace` builds each member with its DEFAULT features, and Cargo omits any
target whose `required-features` are unmet — not "fails", not "reports skipped", omits
entirely, and the run is green. `shepherd-core` defaults to `["std"]`:

```
[[test]] guard             required-features = ["std", "parse", "json"]   -> SKIPPED
[[test]] dispatch          required-features = ["std", "json"]            -> SKIPPED
[[test]] portable_dispatch required-features = ["std", "json"]            -> SKIPPED
[[test]] run_state         required-features = ["std", "json"]            -> SKIPPED

cargo test -p shepherd-core --locked                 ->   3 tests
cargo test -p shepherd-core --locked --all-features  -> 126 tests
```

**The repo's gate ran 3 of 126 core tests, including NONE of the guard engine's 66** — the
security-critical component, modified twice during this very sprint. `shepherd-render` was
3 of 10. `crates/core/tests/loader.rs` additionally carries its own
`#![cfg(all(feature = "config", feature = "std"))]`, so it ran zero tests even when built,
which is how the config lane found it: its gate for deliverable 6's primary acceptance
criterion had never executed.

Two shapes, both indistinguishable from success:
- a skipped target prints NOTHING;
- a cfg'd-out target prints `test result: ok. 0 passed`.

`check-features.sh` does not cover this, and a comment in `gate.sh` asserting it did is why
the gap survived. That script runs `cargo check` — it proves the feature graph resolves, not
that feature-gated tests run.

**The rule this forces on GATE-CAN-FAIL itself, and it is the sharpest thing to come out of
this sprint:**

> A gate is not proven by a red test. The test must be shown to RUN, and then shown to go red.

`test result: ok. 0 passed` survives every "did it go red?" check ever devised, because a
suite that never executes never goes red either. Proving falsifiability without first
proving execution is exactly the inert-gate class one level further out — and it is what
hid 22 loader tests behind an unset `config` feature while the lane believed it had a
working gate on its primary acceptance criterion.

**The propagatable form, from the harness lane, and it generalizes past Rust:**

> Every gate must state how many things it checked, and fail when that number is zero.

The pattern already exists in this repo and was simply never generalized: `test_exec_bits.sh`
fails with `no path-invoked scripts matched — pathspec drift?` when zero paths match. That is
exactly the defence the Cargo test targets lacked. A gate that reports `ok` without a count
cannot distinguish "checked 126 things, all fine" from "checked nothing".

Applied during this sprint rather than merely filed: the harness lane probed all three gates
it shipped against empty input and all three failed loudly; its highest-risk case was the
harness-parity table, where a zero-row table would satisfy a naive regenerate-and-diff
perfectly because both sides of the diff are equally empty. Its test now derives the expected
row count from the three manifests.

**Carry forward:** (a) any new `[[test]]` with `required-features` must be added to the
feature-gated gate step, or it is born inert; (b) reviewing a test report means reading the
COUNT, not the word `ok`; (c) `parse` does not imply `config` — `parse = ["alloc",
"dep:nom", "dep:toml"]` — so a briefed feature list is not evidence a target ran.

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

**The fix is procedural and belongs INSIDE the GATE-CAN-FAIL requirement, not beside it as
a caveat.** The discipline is correct; the DEFAULT TECHNIQUE is what is unsafe. Written as
"prove the gate can fail", a coder reaches for `git checkout` every single time. Written as
"prove the gate red against a `/tmp` copy", it never does. So the requirement should carry
its own safe technique in the same sentence:

> Every gate is shown to fail on purpose, **proven against a copy under `/tmp`, never by
> reverting a live file.**

A discipline that demands evidence without naming a safe way to produce it will keep
teaching agents the unsafe way, and the agent is not wrong to have inferred it.

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

## 5b. The build panic that a `content/` edit causes does not name its remedy — LOW

Editing any `content/roles/*.md` makes `crates/compiler/build.rs:30` panic and the ENTIRE
workspace stop compiling, because the vendored `crates/compiler/package-content` projection
is asserted byte-identical to the authored tree. The panic says:

> generated compiler package content differs from authored root content

That is accurate and unactionable. It does not name the one command that fixes it —
`python3 scripts/generate-compiler-package-content.py --write` — so the reader has to
discover the generator, and a coder whose scope excludes `crates/**` reasonably concludes it
is blocked rather than one command from green. It cost the harness lane a diagnostic cycle
and would have cost the config lane another.

This is deliverable 4's own principle applied to the build script: an error should name the
actual failure and, where one exists, the remedy. Add the command to the assertion message.

Related: the coupling itself is undiscoverable from the edit site. `content/roles/*.md` has
nothing indicating that touching it breaks the build until a generator runs. A one-line
header comment in the authored files, or in `content/RECONCILIATION.md`, would remove the
surprise entirely.

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
