# L4-S1 pre-fix evidence -- #315, #314, #306, #331

Base commit: `b0ad8aa` (this worktree's HEAD; working tree clean at dispatch
time).

Two binaries are on the record here, both exercised by the lane conductor
from `/Users/jo3/src/pzzld/shepherd/.worktrees/v651-l4-diagnostics`:

- **pre-fix**: `shepherd-cli 6.5.1`, built from `b0ad8aa` before this lane's
  fixes landed and kept outside the tree. Identity confirmed by string
  inspection: it carries the old `Repair with ` banner and none of
  `this session is not bound to a shepherd run`,
  `root session already bound to run`, `list existing runs with`.
- **post-fix**: `target/debug/shepherd`, built from this working tree with
  `cargo build --locked -p shepherd-cli --bin shepherd`. It carries all three
  of those new strings and not the old banner.

Two reading conventions, stated once:

- Rust line citations are line numbers in this worktree's current tree, which
  carries this lane's fixes, unless the citation says "at base `b0ad8aa`".
  Where a mechanism describes pre-fix behavior that this lane has since
  changed, its citations are marked as base.
- Every harness probe runs inside a fresh `mktemp -d` scratch directory whose
  absolute path varies run to run. `<sandbox>` stands for the primary scratch
  directory and `<sandbox-306>` for the secondary one `setup_sandbox_306`
  creates. Nothing else in any quoted line is altered.

## Verdicts

Machine-greppable, `^#(315|314|306) +(REPRODUCED|REFUTED)`, plus `#331` recorded
the same way:

```
#315 REPRODUCED
#314 REPRODUCED
#306 REFUTED
#331 REPRODUCED
```

## How this evidence was produced: derived first, then measured

The coder who first wrote this file could not run the harness. That is not a
self-imposed caution -- it was enforced live: a plain `git init -q` issued
against an isolated `/private/tmp/...` scratch directory, purely to hand-verify
this step's own probes before writing them up, was denied by shepherd's own
guard with:

```
[shepherd] A role dispatched to implement one file-disjoint scope (coder)
never performs any version-control write, under any circumstance -- custody
sits one tier up, always.
```

`sandbox.sh` needs `git init` for every scratch repository it builds, so that
denial put the whole harness out of that role's reach. It is issue #335, it is
still true of the `coder` role today, and it is why the first version of the
`#314` and `#306` sections below were derived from the code paths they exercise
rather than captured from a run.

That derivation has now been superseded by measurement. The lane conductor,
which has the standing the `coder` role does not, executed the corrected
`sandbox.sh` against both binaries named above and captured every transcript in
this file. Every string quoted below is measured output, attributed inline to
the binary that produced it. Nothing here is awaiting a first run.

The measurement also overturned one derivation, which is why this file was
rewritten rather than merely appended to. The original `#306` section measured
a **SessionStart** envelope, and #306 is a **PreToolUse-class** block. A
SessionStart error cannot be a block at all (`native_hook.rs:119-164`; the
generic `context()` arm at `:154-163`), so that probe would have printed the
same shape whether or not PreToolUse still hard-denied. The REFUTED conclusion
survived re-measurement; the evidence for it did not, and has been replaced.
See "#306" below.

Two stale comments this lane cannot repair from here, both inside
`sandbox.sh` and both outside this artifact's scope: its `METHODOLOGY NOTE`
header still describes the script as awaiting a first execution, and its
zero-count guard comments (`sandbox.sh:594-599` and `:681-686`) cite
`passed=0 failed=1` as "the recorded pre-fix `--follow-remediation` run" when
the measured pre-fix run is `passed=3 failed=1` (the `passed=0 failed=1` case
is the silent stub, below). Both texts were accurate when written; neither
guard is wrong, only the examples are. The corrections are left to whoever
next edits that file.

---

## #315 -- unbound-session denial is a raw errno

**Verdict: REPRODUCED**

Command (conductor, pre-dispatch capture, against the pre-fix binary):

```
$ printf '{"hook_event_name":"PreToolUse","session_id":"stranger","tool_use_id":"t2","tool_name":"Write","tool_input":{"file_path":"x"}}' | shepherd claude-hook
```

Literal output:

```
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[shepherd] dispatch filesystem operation `open regular file` failed for /Users/jo3/src/pzzld/shepherd/.shepherd/runs/v651/dispatch/.root-session.stranger.json: No such file or directory (os error 2)"}}
[exit 0]
```

The harness reproduces the same denial inside a scratch repository rather than
against this checkout; that capture is `PROBE #315` in the full pre-fix
`--mode expect-abort` transcript under "Harness run output" below, and it
differs from the line above only in the path, which is the scratch run instead
of the real `v651` one.

What the operator is told vs. what they need to know: the message names a
filesystem primitive (`open regular file`), an absolute path inside
shepherd's own dispatch bookkeeping, and a bare OS errno. What the operator
actually needs is "your session was never bound -- run whatever your harness
does for `SessionStart`" or similar; nothing in this string says that.

Mechanism, at base `b0ad8aa` (`crates/cli/src/cmd/native_hook.rs:504-545`,
`unresolved_pre_tool_use`): a session with no `.root-session.<id>.json` fails
resolution with `DispatchStoreError::Io` (open-regular-file, ENOENT). That
error is not `Identity::MissingRecord` or `Store::UnknownRecord`, so it does
not take the "never recorded" exemption; and once
`run_namespace_is_usable(&context.runs_root)` is true (at base
`native_hook.rs:551-563` -- some run has a `dispatch/` dir and
`run.json.status == "executing"`), the function falls to
`HookOutput::Deny { detail: error.to_string() }` -- the raw `Display` of
`DispatchStoreError::Io` (`crates/cli/src/dispatch_store.rs:28`):
`` dispatch filesystem operation `{operation}` failed for {path}: {source} ``,
where `{source}` is `std::io::Error`'s own OS-string Display, hence
`No such file or directory (os error 2)`. The only place this codebase prints
an actionable command for this failure class is the *advisory* banner (at base
`native_hook.rs:537-543`), which this branch never reaches, because the run
namespace being usable is precisely what routes here instead of there.

`sandbox.sh`'s `assert_abort_315` (and, at the "AFTER" step, `assert_no_worse`
in `--follow-remediation`) asserts: decision is `deny`; reason contains
`os error`; reason names `.root-session.<session>.json`; reason contains no
`Repair with` (no actionable command).

`assert_fixed_315` (`sandbox.sh:355-363`) no longer asserts the negative space
only. It asserts three things: no `os error`, no `No such file or directory`,
and `"permissionDecision":"deny"` still present. The positive half is not
decoration. L4-S2's NON-GOALS require #315 to stay fail-closed, and a
regression that routed the unbound-session case through the PreToolUse
catch-all at `native_hook.rs:137` (`Err(error) if pre_tool_use`) would emit
`dispatch state unavailable, tool allowed: ...` (`native_hook.rs:141`) -- text
carrying neither `os error` nor `No such file or directory` -- so a
negative-space-only assertion would have scored that fail-open flip as a PASS.
What wording replaces the errno is still L4-S2/S3's call, and nothing in
`assert_fixed_315` constrains it.

Proof the positive half is load-bearing rather than assumed: the silent-stub
fixture in the falsification table below scores `--mode expect-fixed` at
`passed=5 failed=1`, and the one failure is exactly
`FAIL  #315 remains fail-closed post-fix`. The other five assertions pass
vacuously against empty output -- which is precisely what a negative-space-only
`assert_fixed_315` would have amounted to.

---

## #314 -- SessionStart is not idempotent

**Verdict: REPRODUCED**

Command (both probes go through `shepherd claude-hook`, same `session_id`,
inside a scratch repo with one run raised to `status: executing`; exact
sequence in `sandbox.sh`'s `main`, `PROBE #314a`/`PROBE #314b`):

```
$ printf '{"hook_event_name":"SessionStart","session_id":"probe-314"}' | shepherd claude-hook
$ printf '{"hook_event_name":"SessionStart","session_id":"probe-314"}' | shepherd claude-hook
```

Measured output, conductor's run of `sandbox.sh --mode expect-abort` against
the pre-fix binary:

```
=== PROBE #314a · first SessionStart for probe-314 (expect BIND) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] bound root session to run v900","hookEventName":"SessionStart"}}
[exit 0]

=== PROBE #314b · second SessionStart for the SAME session (expect REJECTED) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] native lifecycle hook rejected: dispatch record already exists: <sandbox>/.shepherd/runs/v900/dispatch/.root-session.probe-314.json","hookEventName":"SessionStart"}}
[exit 0]
```

(`v900` and `probe-314` are `sandbox.sh`'s own harness constants, `RUN` and
`SESSION_314`, at `sandbox.sh:134` and `:137`.)

What the operator is told vs. what they need to know: the second call reads
as an infrastructure failure ("rejected") rather than "you already did this,
here is what's already true" -- a client that legitimately replays a
`SessionStart` (retry after a dropped response, a supervisor restart) gets a
rejection instead of an idempotent re-affirmation of the existing binding.

Mechanism, cited exactly, not assumed: `run_hook`'s `DispatchRequest::BindRoot`
arm (`native_hook.rs:252-259`) calls `service.bind_root(...)`
(`crates/cli/src/dispatch_service.rs:214-237`), which calls
`self.store.publish_root_binding(&binding)?`
(`crates/cli/src/dispatch_store.rs:114-124`), which calls
`platform::publish_root_binding` (`dispatch_store.rs:331-342`, unix) calls
`publish_no_clobber` (`dispatch_store.rs:645-...`, wraps `linkat` with no
overwrite). A second publish to the same path returns
`DispatchStoreError::AlreadyExists`: the variant is declared at
`dispatch_store.rs:44`, and the message it renders,
`"dispatch record already exists: {path}"`, is the `#[error(...)]` attribute
one line above it at `:43` -- two lines, two different things, cited
separately because the plan cites a single line for both (see plan defect 4).
This exact mechanism is already proven, checked in, and (per its presence in
the tree at this commit) currently exercised by
`crates/cli/tests/dispatch_store.rs:212-231`,
`root_session_binding_is_durable_no_clobber_and_primary_run_scoped`:

```rust
store
    .publish_root_binding(&binding)
    .expect("first root binding publication succeeds");
...
assert!(matches!(
    store.publish_root_binding(&binding),
    Err(DispatchStoreError::AlreadyExists { .. })
));
```

Back in `run_native_hook` (`native_hook.rs:119-164`), a `SessionStart` error
is neither the `pre_tool_use` branch (`:137`) nor the `SubagentStop` branch
(`:147-153`), so it takes the generic
`Err(error) => ... "native lifecycle hook rejected: {}"` wrapper at
`:154-163` -- the exact wrapper string in the original #314 report, and the
exact string the transcript above carries.

`sandbox.sh`'s `assert_abort_314` asserts: the first output is not itself a
rejection and does contain "bound root session to run"; the second contains
"rejected" and "dispatch record already exists"; and the two outputs are NOT
byte-identical. All five held in the measured run. `assert_fixed_314` asserts
the second output no longer contains "rejected", and that the two outputs are
either byte-identical or a non-rejection re-affirmation -- matching the brief's
stated fix shape exactly.

---

## #306 -- hook rejection when project identity is missing

**Verdict: #306 REFUTED**

Mesh R51's claim is correct at this commit. Milestone correction: per the
conductor's own `gh issue view 306` (not re-run here, recorded as supplied),
**#306 carries milestone 60 (v6.4.6), not 61** -- plan correction C5.

### Correction to the previous version of this section

The earlier version of this section measured a `SessionStart` envelope. That
was the wrong probe class, and it is what a root-dispatched auditor returned
REDO over. #306 is a PreToolUse-class complaint in its own words: "commands
using shell tools were blocked ... fails before command runs". A `SessionStart`
error can never be a block. It reaches the arm-selection matcher in
`run_native_hook` (`native_hook.rs:119-164`) as neither the `pre_tool_use`
branch nor the `SubagentStop` branch, so it renders through the generic
`context()` arm at `:154-163` as advisory `additionalContext` -- the only
shape that arm can produce. A SessionStart probe would therefore have printed
the same shape whether PreToolUse still hard-denied or not: it is structurally
incapable of deciding this verdict. The conclusion held under re-measurement;
the evidence did not support it, so it has been replaced with the probe class
the complaint actually names. `sandbox.sh` now sends a PreToolUse Write
envelope for #306 (`envelope_pretooluse_write "$SESSION_306" ...` in `main`).

### Primary evidence: the PreToolUse probe

Fresh scratch repo, `shepherd init` deliberately never run
(`sandbox.sh`'s `setup_sandbox_306` / `PROBE #306`), pre-fix binary,
conductor's run of `--mode expect-abort`:

```
=== PROBE #306 · PreToolUse write into a fresh scratch repo, no `shepherd init` at all (project identity absent) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] dispatch state unavailable, tool allowed: project not scaffolded — run `shepherd init --confirm`: <sandbox-306>/.shepherd/project.json","hookEventName":"PreToolUse"}}
[exit 0]
```

`hookEventName` is `PreToolUse`, the envelope carries `additionalContext` and
no `permissionDecision` at all, and the text names the exact command to run
and the exact missing artifact with no bare OS errno anywhere in it. The tool
is allowed. That is the whole of what #306 asked for, and it is what a
pre-fix binary already does. Nothing here is left for L4-S2/S3.

The conductor re-ran the same PreToolUse probe against the post-fix binary:
byte-identical apart from the scratch path. #306's behavior is untouched by
this lane, which is what REFUTED means.

### Secondary evidence: the SessionStart probe, kept for comparison

This is the weaker probe -- the one the previous version of this section
relied on -- measured by the conductor against the pre-fix binary and recorded
here only so the two event classes sit side by side:

```
{"hookSpecificOutput":{"additionalContext":"[shepherd] native lifecycle hook rejected: project not scaffolded — run `shepherd init --confirm`: <sandbox-306>/.shepherd/project.json","hookEventName":"SessionStart"}}
[exit 0]
```

Against the post-fix binary the same SessionStart probe is byte-identical
apart from the scratch path. Note what this pair does and does not show: the
message body is the same either way, and the only difference from the
PreToolUse capture is the wrapper each arm applies
(`"dispatch state unavailable, tool allowed: "` at `:141` vs.
`"native lifecycle hook rejected: "` at `:158`). Neither of these two
SessionStart lines could have carried a block no matter what the hook decided,
which is exactly why this probe is secondary.

### Mechanism

The governing citation is `crates/cli/src/cmd/native_hook.rs:137`, the
`Err(error) if pre_tool_use => ...` arm. Its own comment at `:130-136` states
the reason it exists:

> A guard verdict reaches us as `Ok(HookOutput::Deny)`. Every error that
> lands here is therefore an infrastructure fault in shepherd's own
> bookkeeping -- an unresolved identity, a run that is not executing,
> unreadable dispatch state -- and says nothing about whether the requested
> call is safe. Denying on it strands the session: the repair for broken run
> state is itself a tool call, and this matcher covers every tool that could
> perform one. Surface the fault and allow.

That arm, and only that arm, decides block versus allow for a PreToolUse
envelope whose dispatch resolution failed early. A missing project identity
fails before any resolution verdict exists, so it lands there, is allowed, and
is rendered as advisory `additionalContext` prefixed
`dispatch state unavailable, tool allowed: ` (`:141`).

`crates/cli/src/cmd/dispatch.rs:182`'s
`ReadSubject::ProjectIdentity::not_found_message` supplies the message TEXT
only:

```rust
Self::ProjectIdentity => format!(
    "project not scaffolded — run `shepherd init --confirm`: {}",
    path.display()
),
```

It is a hand-written string with zero OS-error surface -- not
`error.to_string()`, not a `DispatchStoreError` passthrough -- and it is what
makes the sentence actionable. It has no say in whether the hook blocks or
allows, and it is reached through a NOFOLLOW-guarded identity read on a path
of its own (`read_project_id`, `crates/cli/src/cmd/dispatch.rs:234-253`). Reading it as the
reason #306 is refuted was the original section's second mistake, one layer
below the probe-class mistake; it is demoted here to what it actually is.

`execution_context()` (`native_hook.rs:316-324`) is what lets the probe get
that far: it succeeds even with no `.shepherd` directory at all, since config
resolution has built-in defaults, which is required for `shepherd init` itself
to be able to run before any config exists. `read_project_id(&context.project_id_path)`
then fails on the plain-ENOENT path, and that failure is the error the `:137`
arm receives.

Corroboration for the message text, and only for the text:
`crates/cli/tests/dispatch_cli.rs:277-303`,
`dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal`
(labelled `GE1` in-file), already checked in and already end-to-end at this
commit:

```rust
let root = repository_missing_identity("missing-identity");
assert!(!root.join(".shepherd/project.json").exists());

let start = run(&root, &["dispatch", "start"], &start_request());
assert!(!start.status.success());
assert!(start.stdout.is_empty());
let stderr = String::from_utf8_lossy(&start.stderr);
assert!(stderr.contains("project not scaffolded"), "stderr={stderr}");
assert!(
    stderr.contains("run `shepherd init --confirm`"),
    "stderr={stderr}"
);
assert!(
    !stderr.contains("without following symlinks"),
    "stderr={stderr}"
);
```

That test drives `shepherd dispatch start` -- a different subcommand, a
different edge (plain stderr, non-zero exit), and a deliberate failure rather
than an allow. It pins the wording of that subcommand's failure. It says
nothing about what `shepherd claude-hook` decides on a PreToolUse envelope,
and it is cited here for the text alone. The decision is `:137`; the
measurement of the decision is the PreToolUse transcript above.

### What the harness holds

`sandbox.sh`'s `assert_306` (`sandbox.sh:415-419`) is one counted assertion,
run in BOTH modes on purpose: `"permissionDecision":"deny"` must be absent
from the #306 output. "A missing project identity does not block the tool" has
to hold before and after L4-S2/S3 land; there is no state of this sprint in
which a deny there would be acceptable. It is the assertion that makes the
pre-fix `--mode expect-abort` count 10 rather than 9.

`note_306` (`sandbox.sh:436-445`) reads the message TEXT and records a NOTE,
never a PASS/FAIL, because a REFUTED verdict carries no assertion demanding a
change and the wording is not this lane's to constrain. In the measured
pre-fix run it printed:

```
=== NOTES · #306 message text, not a verdict counted here ===
  NOTE  #306 names an action and carries no bare os error -- REFUTED
```

If a future commit regresses the wording back to a raw `os error`, that NOTE
flips and says so; if a future commit regresses the decision to a deny,
`assert_306` fails the run outright.

---

## #331 -- `shepherd ready --run <missing>` aborts on a raw errno

**Verdict: REPRODUCED**

Measured by the lane conductor from this worktree, against both binaries.

Pre-fix binary:

```
$ shepherd ready --run dummy
ERROR: open state directory /Users/jo3/src/pzzld/shepherd/.shepherd/runs/dummy: No such file or directory (os error 2)
[exit 5]
```

Post-fix binary (`target/debug/shepherd`):

```
$ shepherd ready --run dummy
ERROR: run lookup /Users/jo3/src/pzzld/shepherd/.shepherd/runs/dummy: no such run `dummy` — list existing runs with `shepherd run list`
[exit 5]
```

Both strings are on the record, so the pre-fix one can never be mistaken for
a post-fix capture or vice versa: the pre-fix line names a filesystem
primitive (`open state directory`) and an errno; the post-fix line names the
run that does not exist and the command that lists the ones that do. The exit
code is 5 in both captures: what this lane changed is the message, not the
exit code, and the two transcripts above are the measurement that says so.

`sandbox.sh` carries no probe for #331. It is out of this lane's live-probe
set by the conductor's own instruction, recorded here only.

---

## Harness run output

Every row below was measured by the lane conductor from
`/Users/jo3/src/pzzld/shepherd/.worktrees/v651-l4-diagnostics` with the
corrected `sandbox.sh`.

### Full pre-fix `--mode expect-abort` transcript, exit 0

```
=== PROBE #315 · unbound session onto a Write tool (expect hard DENY, raw errno) ===
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[shepherd] dispatch filesystem operation `open regular file` failed for <sandbox>/.shepherd/runs/v900/dispatch/.root-session.stranger.json: No such file or directory (os error 2)"}}
[exit 0]

=== PROBE #314a · first SessionStart for probe-314 (expect BIND) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] bound root session to run v900","hookEventName":"SessionStart"}}
[exit 0]

=== PROBE #314b · second SessionStart for the SAME session (expect REJECTED) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] native lifecycle hook rejected: dispatch record already exists: <sandbox>/.shepherd/runs/v900/dispatch/.root-session.probe-314.json","hookEventName":"SessionStart"}}
[exit 0]

=== PROBE #306 · PreToolUse write into a fresh scratch repo, no `shepherd init` at all (project identity absent) ===
{"hookSpecificOutput":{"additionalContext":"[shepherd] dispatch state unavailable, tool allowed: project not scaffolded — run `shepherd init --confirm`: <sandbox-306>/.shepherd/project.json","hookEventName":"PreToolUse"}}
[exit 0]

=== ASSERTIONS · mode=expect-abort ===
PASS  #315 hard-denies the unbound session
PASS  #315 reason leaks a raw errno
PASS  #315 reason names the missing root-session binding file
PASS  #315 reason carries no actionable command
PASS  #314 first SessionStart is not itself a rejection
PASS  #314 first SessionStart binds the root session
PASS  #314 second SessionStart is rejected
PASS  #314 second SessionStart names the collision
PASS  #314 the two SessionStart outputs are NOT byte-identical
PASS  #306 PreToolUse is not blocked when project identity is missing

=== NOTES · #306 message text, not a verdict counted here ===
  NOTE  #306 names an action and carries no bare os error -- REFUTED

=== RESULT ===
mode=expect-abort passed=10 failed=0
#315 and #314 reproduced as specified.
```

The count is 10, not the 9 an earlier version of this file predicted. The
difference is `assert_306`, a counted assertion the REDO added; the four
`#315` and five `#314` assertions are unchanged.

### The matrix

| binary | invocation | result | exit |
|---|---|---|---|
| pre-fix | `--mode expect-abort` | `passed=10 failed=0` | 0 |
| pre-fix | `--mode expect-fixed` | `passed=3 failed=3` | 1 |
| post-fix | `--mode expect-abort` | `passed=6 failed=4` | 1 |
| post-fix | `--mode expect-fixed` | `passed=6 failed=0` | 0 |
| pre-fix | `--follow-remediation` | `passed=3 failed=1` | 1 |
| post-fix | `--follow-remediation` | `passed=2 failed=0` | 0 |
| silent stub | `--follow-remediation` | `passed=0 failed=1` | 1 |
| silent stub | `--mode expect-fixed` | `passed=5 failed=1` | 1 |

The first four rows are the shape a reproduction harness has to have: the
pre-fix binary passes the "these defects are present" mode and fails the
"these defects are gone" mode, and the post-fix binary does the reverse. A
harness that passed both modes against one binary would be measuring nothing.

### Reproduction

```bash
cargo build --locked -p shepherd-cli --bin shepherd
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --mode expect-fixed  target/debug/shepherd
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --mode expect-abort  target/debug/shepherd
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --follow-remediation target/debug/shepherd

# PRE_FIX_BIN: a shepherd-cli 6.5.1 built from b0ad8aa before this lane's
# fixes landed, kept outside the tree. Verify identity before trusting a
# capture from it: it must carry `Repair with ` and must NOT carry
# `this session is not bound to a shepherd run`,
# `root session already bound to run`, or `list existing runs with`.
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --mode expect-abort  "$PRE_FIX_BIN"
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --mode expect-fixed  "$PRE_FIX_BIN"
bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --follow-remediation "$PRE_FIX_BIN"
```

The binary under test is the first positional argument, then `$SHEPHERD_BIN`,
then `<repo root>/target/debug/shepherd` -- see `sandbox.sh`'s CONTRACT block.

### The silent stub, and what it falsifies

The auditor found two assertions that could pass without measuring anything.
The falsification fixture for both is a "silent stub": an executable that
accepts every subcommand, exits 0, and prints nothing at all
(`#!/usr/bin/env bash` followed by `exit 0` is enough). It is not a shepherd
binary and is not supposed to be; it exists to be the emptiest possible input.

- `--follow-remediation` against the stub scores `passed=0 failed=1`, failing
  on `FAIL  BEFORE probe produced a hook response`. Before the fix, that same
  input scored `passed=1 failed=0` and exit 0: an empty banner names no
  backtick-fenced command, so "banner printed no command to follow" recorded a
  PASS over a binary that never spoke. `probe_spoke` (`sandbox.sh:453-458`)
  and `assert_probe_spoke` (`:469-478`) now gate every branch of that mode on
  the probe having produced a `hookSpecificOutput` envelope at all.
- `--mode expect-fixed` against the stub scores `passed=5 failed=1`, and the
  single failure is `FAIL  #315 remains fail-closed post-fix` -- the assertion
  the auditor required. The other five pass vacuously on empty output
  (`printf '' | grep -qF -- '"permissionDecision":"deny"'` exits 1, so silence
  reads as "not denied"), which is exactly why the negative-space-only form of
  `assert_fixed_315` was not a gate.

Both zero-count guards were also changed to test `PASS_COUNT + FAIL_COUNT`
rather than `PASS_COUNT` alone (`sandbox.sh:600` and `:687`). Testing
`PASS_COUNT` alone reports "zero assertions ran" about any run in which every
assertion failed, because such a run also has `PASS_COUNT=0`, and it returns
before the accurate diagnostic below it. The silent stub's
`--follow-remediation` row above, `passed=0 failed=1`, is exactly that case
and is the measurement that exercises the corrected guard: it still exits 1,
and it now says why.

### The pre-fix `--follow-remediation` failure

`passed=3 failed=1` is the R36d/R36e defect reproducing, not a broken harness.
The BEFORE probe is an advisory allow, the harness parses and executes the two
commands the banner itself printed (never hardcoded -- see
`extract_backtick_commands`), and the AFTER probe is a hard deny naming
`.root-session.follow-remediation-probe.json` with `os error 2`. Following the
tool's own printed remediation verbatim turned an allowed tool call into a
refused one, because `shepherd run layout <run> --repair` and
`shepherd run set <run> --status executing` create exactly the two conditions
`run_namespace_is_usable` checks.

Post-fix the banner names no command at all, so `extract_backtick_commands`
returns empty, there is nothing to follow, and nothing that can make the
decision worse: `passed=2 failed=0`, exit 0. The two passes are the BEFORE
liveness check and "banner printed no command to follow" -- and that second
one is only trustworthy because the liveness check now precedes it.

### Static checks

`bash -n` (syntax) and `shellcheck -s bash -x` (run from this lane directory,
so the `# shellcheck source=../l1-resolution/sandbox.sh` directive resolves)
both ran clean against `sandbox.sh`: zero warnings, zero errors, exit 0. They
were re-verified clean after the REDO edits that added `assert_306`, added the
third assertion to `assert_fixed_315`, added `probe_spoke`/`assert_probe_spoke`,
and changed both zero-count guards to test `PASS_COUNT + FAIL_COUNT`.
`shellcheck` 0.11.0 was available on this machine
(`/opt/homebrew/bin/shellcheck`); this is a real, executed, clean result, not
a claim.

---

## Plan defects noted while building this lane's harness

1. **The `--follow-remediation` flag did not exist anywhere in this sprint's
   sandbox family.** L4-S2's plan acceptance invokes it against
   `l1-resolution/sandbox.sh`, which has no such switch -- that invocation
   hits l1's own `die "unknown option"` and exits 2. This lane's
   `sandbox.sh` (`l4-diagnostics/sandbox.sh`) now implements the flag for
   real; L4-S2's acceptance should be corrected to point at this lane's
   script, not l1's.

2. **`grep -qv PATTERN` is the wrong idiom, and it appears twice in L4-S2's
   acceptance block.** `grep -v -q` succeeds as soon as it finds *any* line
   that does not match `PATTERN` -- true of almost any multi-line output,
   including the exit-2 usage-error line from defect 1 above, which is
   exactly how that acceptance block passed without ever running a probe.
   The non-vacuous form is `! grep -q PATTERN` (fails unless the pattern is
   absent from every line). `sandbox.sh` uses `! grep -q` (via its own
   `contains_text` helper, which distinguishes grep's exit 2 from exit 1 per
   G5) everywhere it needs this kind of check, and never `grep -qv`.
   Root has since fixed this in the plan, in plan commit `8d1124f`. In root's
   checkout `plan.md` now carries `{ ! grep -q ...; }` with an inline
   `# ROOT FIX` marker at `:363`, `:702`, `:705`, and `:1054`, and no
   `grep -qv` survives in any acceptance block. This worktree's copy of
   `plan.md` is still at `b0ad8aa` and predates that commit, so grepping it
   here still finds the defective form at `:359`, `:694`, `:697`, and
   `:1046`.

3. **The plan's own #306 citation points at the wrong arm, and this
   artifact inherited the error.** L4-S1's CONTEXT-INVENTORY
   (`plan.md:632-633`, repeated at `:655`) says "#306 may already be
   satisfied by `crates/cli/src/cmd/native_hook.rs:521-531` (mesh R51)". At
   base `b0ad8aa`, `:521-531` is the `never_recorded` matcher and its
   "tool allowed because shepherd never recorded this agent" arm inside
   `unresolved_pre_tool_use` -- a different condition entirely. That arm fires
   on a missing *agent* record, which `dispatch_store.rs`'s `read_record` maps
   to `UnknownRecord` (or `IdentityError::MissingRecord`), and it is reached
   only after resolution has run far enough to produce such an error. #306's
   path is a missing *project identity*, which fails earlier, never reaches
   `unresolved_pre_tool_use` at all, and lands on the PreToolUse catch-all at
   `native_hook.rs:137`. Reading the verdict off `:521-531` is what led the
   original evidence to probe the wrong event class and to cite a message
   builder as if it decided the block. The plan's re-measurement instruction
   at `plan.md:655` should name `:137`.

4. **Two off-by-a-line plan citations.** L4-S1 (`plan.md:632`) cites
   `crates/cli/src/dispatch_store.rs:45` for `DispatchStoreError::AlreadyExists`;
   the `#[error(...)]` message is at `:43` and the variant at `:44`, and `:45`
   is the next variant's attribute. L4-S2 (`plan.md:672`, `:674`) cites
   `native_hook.rs:536-542` for the banner and `:549-563` for
   `run_namespace_is_usable`; measured at base, the banner is `:537-543` and
   the predicate `:551-563`. Neither misleads about which code is meant, and
   both are recorded only so a later reader who greps by line number does not
   conclude the code moved.

5. **Editing any file the harness-parity table cites breaks a gate no lane's
   acceptance names.** `hooks/tests/test_harness_parity_generator.sh:453-464`
   regenerates `.shepherd/runs/v646/harness-parity.md` via
   `hooks/scripts/generate_harness_parity.sh --check` and diffs it against the
   committed copy. That table cites `crates/cli/src/cmd/native_hook.rs:358,390`
   (rows at `harness-parity.md:27` and `:39`, the SubagentStart write-scope
   narrowing rows). This lane's edits to `native_hook.rs` moved those two
   byte-identical `vec!["**".into()]` lines to `:371` and `:403`, so the
   committed table is now stale and `bash hooks/tests/run.sh` reports 2
   failures instead of the 1 baseline failure -- against `W2-GATE`
   (`plan.md:610`), which demands `0 failed`. The citations are generated from
   the real tree at run time, by design, so any edit that shifts a line the
   table cites regenerates a different table and trips this, whether or not
   the cited code itself changed; no lane's acceptance mentions it, and
   `.shepherd/runs/v646/harness-parity.md` is in no lane's file scope, so this
   lane cannot repair it. Escalated to root. The fix is one command plus a
   re-run of the suite, both of which write outside this lane's scope:

   ```bash
   bash hooks/scripts/generate_harness_parity.sh   # default output is the committed table
   bash hooks/tests/run.sh                          # expect back to the 1 baseline failure
   ```
