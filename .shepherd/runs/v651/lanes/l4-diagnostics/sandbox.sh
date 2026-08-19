#!/usr/bin/env bash
#
# sandbox.sh -- reproduce shepherd issues #315, #314, and #306 (re-measured,
# not assumed) inside throwaway scratch repositories, and give L4-S2's plan
# acceptance a real `--follow-remediation` target to run.
#
# #315: an unbound PreToolUse session, once the run namespace is usable,
# hard-denies with a raw `DispatchStoreError::Io` display -- an errno and a
# bare filesystem path, no actionable command -- instead of a message that
# tells the operator what to do.
#
# #314: `SessionStart` is not idempotent. Feeding the same session id twice
# binds the root session on the first call and rejects the second with
# `native lifecycle hook rejected: dispatch record already exists: ...`,
# which is not what a client replaying a duplicate lifecycle event expects.
#
# #306: a PreToolUse-class block -- "commands using shell tools were blocked
# ... fails before command runs". The probe below therefore sends a PreToolUse
# Write envelope, not a SessionStart one. Per the arm-selection matcher at
# `crates/cli/src/cmd/native_hook.rs:119-164`, a SessionStart error renders
# through the generic `context()` arm (:154-163) as advisory
# `additionalContext` and can never carry a block, so a SessionStart probe
# prints the same shape whether or not PreToolUse still hard-denies: it is
# structurally incapable of measuring this verdict. The governing arm is the
# fail-open one at `native_hook.rs:137` (`Err(error) if pre_tool_use`), which
# allows the tool and surfaces the fault as advisory text. Mesh R51 claims
# #306 is already fixed at this commit; this script re-measures it against a
# fresh scratch repo that never ran `shepherd init` rather than trusting the
# claim. One counted assertion holds the only thing #306 actually complained
# about -- PreToolUse is not blocked when project identity is missing -- and
# the wording of the message stays an uncounted NOTE, because if the text
# already names an action there is nothing there for L4-S2/S3 to fix.
#
# `--follow-remediation` closes a hole in L4-S2's own plan: its acceptance
# block invokes a flag that did not exist anywhere in this sprint's sandbox
# family, and because it piped a usage-error exit through `grep -qv`, that
# acceptance block PASSED without ever running a probe (exactly the Class A
# defect -- "an assertion measured against a target that was never built" --
# this sprint exists to kill). This file is where `--follow-remediation`
# gets a real implementation: it captures the PreToolUse decision, parses
# the *actual* remediation commands out of the banner text the binary
# itself prints (never hardcoded), executes them verbatim against the real
# run name, and asserts the decision got no worse. Mesh R36d/R36e: pre-fix,
# following the banner flips an advisory allow into a hard deny, so this
# assertion is written to FAIL loudly pre-fix and PASS post-fix.
#
# ---------------------------------------------------------------------------
# CONTRACT
#
#   usage: sandbox.sh [--mode expect-abort|expect-fixed] [BINARY]
#          sandbox.sh --follow-remediation [BINARY]
#
#   Binary under test, highest precedence first:
#     1. the first positional argument
#     2. $SHEPHERD_BIN
#     3. <repo root>/target/debug/shepherd, where <repo root> is derived from
#        this script's own location by stripping the trailing
#        `/.shepherd/runs/<run>/lanes/<lane>` segment. Nothing about the run,
#        the lane, or the checkout is baked in.
#
#   Modes:
#     --mode expect-abort  (default) #315 and #314 MUST reproduce. Exit 1 if
#                          either fails to show. #306 is measured and
#                          recorded either way but never gates this mode --
#                          see the REFUTED note above.
#     --mode expect-fixed  #315 and #314 MUST be gone. Exit 1 if either is
#                          still there.
#     --follow-remediation runs a dedicated probe: drive the hook to print
#                          its own "no usable run namespace" banner, execute
#                          the exact commands that banner names (substituting
#                          the real run id for its `<run>` placeholder), then
#                          assert the decision got no worse. Ignores --mode.
#
#   Environment:
#     SHEPHERD_BIN    binary under test when no positional argument is given
#     KEEP_SANDBOX=1  keep the scratch directory/directories on exit
#
#   Exit codes: 0 every assertion held * 1 an assertion failed * 2 usage error.
#
# ---------------------------------------------------------------------------
# SAFETY
#
#   Every mutation lands inside a `mktemp -d` scratch directory that an EXIT
#   trap removes on every path, and SHEPHERD_HOME is redirected into that same
#   directory so the real user home is never read or written. This script
#   never raises a run's status, binds a session, or probes PreToolUse
#   against anything but a freshly `git init`'d scratch repository -- never
#   against this checkout or its real, currently-executing `v651` run. A
#   `SessionStart` envelope writes a dispatch record, and `resolve_primary`
#   (`crates/cli/src/context.rs:608-612`) resolves a linked worktree back to
#   the primary checkout, so every probe below is isolated for exactly that
#   reason.
#
#   bash 3.2 compatible (macOS ships 3.2): no associative arrays, no ${var^^},
#   no mapfile/readarray, no `**` globstar.
#
#   METHODOLOGY NOTE (why the author never ran this script): the coder who
#   wrote it is categorically forbidden from running any git command, in any
#   form, including inside an unrelated scratch directory -- shepherd's own
#   live guard enforces this for the `coder` role ("never performs any
#   version-control write, under any circumstance"), and it denied exactly
#   that attempt during authorship. Every probe here was therefore derived
#   from static reading of the exact code paths it exercises (cited inline)
#   plus this repository's own existing, checked-in, currently-passing
#   regression tests -- never from a live run the author personally
#   executed. The lane conductor has since executed this script under its
#   own standing, in every mode, against both a pre-fix binary built at
#   `b0ad8aa` and the post-fix binary, and `evidence/pre-fix.md` is
#   reconciled against those transcripts.
# ---------------------------------------------------------------------------

set -euo pipefail

# Locate and source the sprint's shared sandbox standard. Derived from this
# script's own directory (two levels up is `lanes/`) rather than hardcoding
# this lane's own name, so only the dependency on l1-resolution as the
# sibling that defines the standard is baked in -- and that dependency is
# deliberate: see the DO-NOT-DUPLICATE note in the L4-S1 brief.
L4_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
L4_LANES_DIR="$(dirname -- "$L4_SELF_DIR")"
L1_SANDBOX="$L4_LANES_DIR/l1-resolution/sandbox.sh"
if [[ ! -f "$L1_SANDBOX" ]]; then
    printf 'sandbox.sh: error: cannot find the sprint sandbox standard to source at %s\n' \
        "$L1_SANDBOX" >&2
    exit 2
fi
# shellcheck source=../l1-resolution/sandbox.sh
source "$L1_SANDBOX"

# ---------------------------------------------------------------------------
# Constants for this lane's probes. RUN is a canonical-but-fictitious run id
# (all-digits after `v`, see `is_canonical` in wave_b2_run.rs) unrelated to
# the real v651 sprint run -- this sandbox never touches the real run.
RUN="v900"
SESSION_315="stranger"
TOOL_USE_315="t2"
SESSION_314="probe-314"
SESSION_306="probe-306"
TOOL_USE_306="probe-306-tool"
SESSION_REMEDIATION="follow-remediation-probe"
TOOL_USE_REMEDIATION="remediation-tool-a"

FOLLOW_REMEDIATION=0
SANDBOX_306=""

usage() {
    cat <<'EOF'
usage: sandbox.sh [--mode expect-abort|expect-fixed] [BINARY]
       sandbox.sh --follow-remediation [BINARY]

Reproduce shepherd issues #315 and #314, re-measure #306, and give
L4-S2's plan acceptance a real `--follow-remediation` target, all inside
self-cleaning scratch repositories.

  --mode expect-abort   (default) fail unless #315 and #314 reproduce
  --mode expect-fixed   fail unless #315 and #314 are gone
  --follow-remediation  drive the "no usable run namespace" banner, run the
                        commands it prints verbatim, assert no regression.
                        Ignores --mode.
  -h, --help            print this help

  BINARY                shepherd binary under test. Falls back to
                        $SHEPHERD_BIN, then to <repo root>/target/debug/shepherd
                        derived from this script's own location.

  KEEP_SANDBOX=1        keep the scratch directory/directories on exit
EOF
}

# Override: l1's parse_args has no `--follow-remediation` switch -- that gap
# is exactly the plan defect this file exists to fix (see the header). This
# reimplements l1's option grammar unchanged and adds the one new flag.
parse_args() {
    local bin=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --mode)
                [[ $# -ge 2 ]] || die "--mode requires a value"
                MODE="$2"
                shift 2
                ;;
            --mode=*)
                MODE="${1#--mode=}"
                shift
                ;;
            --expect-abort)
                MODE="expect-abort"
                shift
                ;;
            --expect-fixed)
                MODE="expect-fixed"
                shift
                ;;
            --follow-remediation)
                FOLLOW_REMEDIATION=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            --)
                shift
                break
                ;;
            -*)
                die "unknown option: $1"
                ;;
            *)
                [[ -z "$bin" ]] || die "unexpected extra argument: $1"
                bin="$1"
                shift
                ;;
        esac
    done
    [[ -z "${1:-}" ]] || bin="$1"

    case "$MODE" in
        expect-abort|expect-fixed) ;;
        *) die "unknown mode: $MODE (want expect-abort or expect-fixed)" ;;
    esac

    if [[ -z "$bin" ]]; then
        bin="${SHEPHERD_BIN:-$(default_binary)}"
    fi
    [[ -x "$bin" ]] || die "shepherd binary not executable: $bin"
    # Absolute, because every command below runs with cwd inside a sandbox.
    case "$bin" in
        /*) BIN="$bin" ;;
        *) BIN="$(cd -- "$(dirname -- "$bin")" && pwd -P)/$(basename -- "$bin")" ;;
    esac
}

# Override: l1's hook_envelope is hardcoded to one safe Bash `echo` PreToolUse
# call, built for #330's needs. L4 needs many different envelope shapes
# (SessionStart bound twice, an unbound PreToolUse denial, a project-identity
# probe), so this override emits whatever JSON was staged in $ENVELOPE_JSON
# immediately before calling l1's `probe`, which this file reuses unchanged.
hook_envelope() {
    printf '%s' "$ENVELOPE_JSON"
}

# Override: l1's cleanup only tracks one scratch directory ($SANDBOX). #306
# needs its own, separate scratch repository that never runs `shepherd init`
# -- a repo where #315/#314's setup has already run cannot also stand in for
# "no `.shepherd/project.json` was ever scaffolded" -- so this override also
# tracks and removes $SANDBOX_306 when present.
cleanup() {
    if [[ -n "${KEEP_SANDBOX:-}" ]]; then
        [[ -n "$SANDBOX" ]] && printf '\nsandbox kept at %s (KEEP_SANDBOX set)\n' "$SANDBOX"
        [[ -n "$SANDBOX_306" ]] && printf 'sandbox (#306) kept at %s (KEEP_SANDBOX set)\n' "$SANDBOX_306"
        return 0
    fi
    if [[ -n "$SANDBOX" && -d "$SANDBOX" ]]; then
        rm -rf -- "$SANDBOX"
    fi
    if [[ -n "$SANDBOX_306" && -d "$SANDBOX_306" ]]; then
        rm -rf -- "$SANDBOX_306"
    fi
}

# A second, independent scratch git repository that never runs
# `shepherd init`, for #306. Mirrors l1's `setup_sandbox` but deliberately
# does not scaffold anything shepherd-shaped.
setup_sandbox_306() {
    local tmp_root
    tmp_root="${TMPDIR:-/tmp}"
    tmp_root="${tmp_root%/}"
    SANDBOX_306="$(mktemp -d "$tmp_root/shepherd-l4-306-XXXXXX")"
    (
        cd -- "$SANDBOX_306" || exit 1
        git init -q
        git config user.email "probe@shepherd.invalid"
        git config user.name "shepherd l4 probe (306)"
    )
}

envelope_session_start() {
    local session="$1"
    printf '{"hook_event_name":"SessionStart","session_id":"%s"}' "$session"
}

envelope_pretooluse_write() {
    local session="$1" tool_use_id="$2" file_path="$3"
    printf '{"hook_event_name":"PreToolUse","session_id":"%s","tool_use_id":"%s","tool_name":"Write","tool_input":{"file_path":"%s"}}' \
        "$session" "$tool_use_id" "$file_path"
}

# Returns 0 if $2 is a fixed-string substring of $1, 1 if it is genuinely
# absent, and dies loudly on any other grep exit status. G5: grep exit 2 is
# "could not look", never "found nothing" -- conflating them would let a
# broken grep invocation silently read as a clean verdict.
contains_text() {
    local haystack="$1" needle="$2" rc=0
    printf '%s' "$haystack" | grep -qF -- "$needle" || rc=$?
    case "$rc" in
        0) return 0 ;;
        1) return 1 ;;
        *) die "grep failed while scanning probe output (exit $rc)" ;;
    esac
}

# Extract every backtick-fenced command template from a banner, in the order
# printed, one per output line, backticks stripped. Never hardcodes the
# command text -- this exists so `--follow-remediation` runs exactly what the
# tool actually told the operator to do. An empty result (no backtick-fenced
# command anywhere in the banner) is a legitimate outcome, not an error: G5
# applies here too, so a real grep failure (exit >1) still dies loudly.
extract_backtick_commands() {
    local haystack="$1" raw rc=0
    # shellcheck disable=SC2016  # the backticks below are a literal regex
    # match target, not command substitution -- no expansion is intended.
    raw="$(printf '%s' "$haystack" | grep -o '`[^`]*`')" || rc=$?
    case "$rc" in
        0) printf '%s\n' "$raw" | sed -e 's/^`//' -e 's/`$//' ;;
        1) : ;;
        *) die "grep failed while parsing the remediation banner (exit $rc)" ;;
    esac
}

# ---------------------------------------------------------------------------
# #315 assertions.
#
# native_hook.rs:532-545 (`unresolved_pre_tool_use`): once
# `run_namespace_is_usable` is true, an unresolved PreToolUse hard-denies
# with `error.to_string()` verbatim -- for an unbound session that is
# `DispatchStoreError::Io`'s Display (dispatch_store.rs:28), a raw errno and
# a bare filesystem path, with no remediation text anywhere in it (the only
# place this codebase ever prints an actionable command for this failure
# class is the *advisory* banner at native_hook.rs:540-543, which this
# branch does not reach).
assert_abort_315() {
    local out="$1"
    assert_contains "#315 hard-denies the unbound session" \
        "$out" '"permissionDecision":"deny"'
    assert_contains "#315 reason leaks a raw errno" \
        "$out" "os error"
    assert_contains "#315 reason names the missing root-session binding file" \
        "$out" ".root-session.$SESSION_315.json"
    assert_not_contains "#315 reason carries no actionable command" \
        "$out" "Repair with"
}

# Post-fix: the raw errno leak must be gone AND the denial must remain.
#
# The negative half alone was wrong, and dangerously so. L4-S2's NON-GOALS
# require #315 to stay fail-closed, but a regression that routed the
# unbound-session case through the PreToolUse catch-all at
# `native_hook.rs:137` (`Err(error) if pre_tool_use`) would emit "dispatch
# state unavailable, tool allowed: ..." -- text carrying neither `os error`
# nor `No such file or directory` -- and a negative-space-only assertion would
# have scored that fail-open flip as a PASS. The positive half below pins the
# decision itself. What wording replaces the errno is still L4-S2/S3's call,
# not this lane's, so nothing here constrains it.
assert_fixed_315() {
    local out="$1"
    assert_not_contains "#315 reason no longer leaks a raw errno" \
        "$out" "os error"
    assert_not_contains "#315 reason no longer leaks the raw io::Error text" \
        "$out" "No such file or directory"
    assert_contains "#315 remains fail-closed post-fix" \
        "$out" '"permissionDecision":"deny"'
}

# ---------------------------------------------------------------------------
# #314 assertions.
#
# dispatch_store.rs's `publish_no_clobber` (~line 1220, platform twin ~645)
# is genuinely no-clobber: `crates/cli/tests/dispatch_store.rs`'s
# `root_session_binding_is_durable_no_clobber_and_primary_run_scoped` already
# proves a second `publish_root_binding` for the same binding returns
# `DispatchStoreError::AlreadyExists`. `run_hook` (native_hook.rs:145-161)
# wraps every non-PreToolUse, non-SubagentStop error the same way:
# "native lifecycle hook rejected: {error}".
assert_abort_314() {
    local first="$1" second="$2"
    assert_not_contains "#314 first SessionStart is not itself a rejection" \
        "$first" "rejected"
    assert_contains "#314 first SessionStart binds the root session" \
        "$first" "bound root session to run"
    assert_contains "#314 second SessionStart is rejected" \
        "$second" "rejected"
    assert_contains "#314 second SessionStart names the collision" \
        "$second" "dispatch record already exists"
    if [[ "$first" == "$second" ]]; then
        record_fail "#314 the two SessionStart outputs are NOT byte-identical" \
            "expected them to differ (that is the idempotency defect), but they were identical"
    else
        record_pass "#314 the two SessionStart outputs are NOT byte-identical"
    fi
}

assert_fixed_314() {
    local first="$1" second="$2"
    assert_not_contains "#314 second SessionStart carries no rejection" \
        "$second" "rejected"
    if [[ "$first" == "$second" ]]; then
        record_pass "#314 repeated SessionStart is now byte-identical (idempotent re-affirmation)"
    else
        record_pass "#314 repeated SessionStart is a non-rejection re-affirmation (differs from the first, carries no rejection)"
    fi
}

# ---------------------------------------------------------------------------
# #306's one counted assertion.
#
# It runs in BOTH modes on purpose. #306's complaint is PreToolUse-class
# ("commands using shell tools were blocked ... fails before command runs"),
# and "a missing project identity does not block the tool" has to hold before
# and after L4-S2/S3 land -- there is no state of this sprint in which a deny
# here would be acceptable. `native_hook.rs:137`'s `Err(error) if pre_tool_use`
# arm is what decides it: on a PreToolUse envelope every error reaching the
# matcher is allowed and surfaced as advisory text, so a deny in this output
# means that arm was bypassed.
assert_306() {
    local out="$1"
    assert_not_contains "#306 PreToolUse is not blocked when project identity is missing" \
        "$out" '"permissionDecision":"deny"'
}

# #306's message TEXT: observed and recorded, never a verdict. The
# block-versus-allow decision is not made here and is not what this reads.
# That decision belongs to the arm-selection matcher in
# `crates/cli/src/cmd/native_hook.rs`: on a PreToolUse envelope every error
# lands on the fail-open arm at `native_hook.rs:137`
# (`Err(error) if pre_tool_use`), which allows the tool and renders the fault
# as advisory `additionalContext`. `assert_306` above is what holds that line;
# this function only reads how the resulting sentence is worded.
# `crates/cli/src/cmd/dispatch.rs:182`'s
# `ReadSubject::ProjectIdentity::not_found_message` supplies wording for a
# NOFOLLOW-guarded identity read on a path of its own -- text only, with no
# say in whether the hook blocks or allows. The REFUTED reading is
# corroborated by `crates/cli/tests/dispatch_cli.rs`'s
# `dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal`
# (GE1), which is already checked in and already end-to-end at this commit.
note_306() {
    local out="$1"
    if contains_text "$out" "os error"; then
        record_note "#306 STILL leaks a raw os error -- would be REPRODUCED, not REFUTED" \
            "re-check the text native_hook.rs:137 renders through cli_error_detail, and dispatch.rs:182's ReadSubject::ProjectIdentity::not_found_message"
    else
        record_note "#306 names an action and carries no bare os error -- REFUTED" \
            "see evidence/pre-fix.md for the full transcript and citations"
    fi
}

# ---------------------------------------------------------------------------
# Did a probe actually produce a hook response? Non-empty, AND carrying the
# `hookSpecificOutput` wrapper that every PreToolUse reply is built with
# (native_hook.rs:718-731 -- `context()` and `deny()` both emit it), so its
# absence means no hook reply was produced at all rather than one that
# happened to allow. Counts nothing itself; returns 1 for silence.
probe_spoke() {
    local out="$1"
    [[ -n "$out" ]] || return 1
    contains_text "$out" 'hookSpecificOutput' || return 1
    return 0
}
#
# The counted form. G4 applied to the INPUT rather than only to the assertion
# count: an empty capture is not a decision, and every question this mode asks
# reads as a benign answer when asked of empty output. `printf '' | grep -qF --
# '"permissionDecision":"deny"'` exits 1, so silence looks like "not denied";
# an empty banner names no command, so silence also looks like "nothing to
# follow". Both are the only assertions on their branch, so either one would
# report passed=1 failed=0 and exit 0 over a binary that never spoke. A silent
# probe is a FAIL, never a pass, because nothing downstream of it is
# measurable.
assert_probe_spoke() {
    local name="$1" out="$2"
    if probe_spoke "$out"; then
        record_pass "$name probe produced a hook response"
        return 0
    fi
    record_fail "$name probe produced a hook response" \
        "it printed no hook response at all; every verdict derived from it is unmeasurable, which is a failure and never a pass"
    return 1
}

# ---------------------------------------------------------------------------
# `--follow-remediation`: asserts the decision got no worse after executing
# exactly the commands the banner itself printed. Mesh R36d/R36e: pre-fix,
# following the banner's own advice flips an advisory allow into a hard
# deny, because the two commands it prints create exactly the two
# conditions `run_namespace_is_usable` checks (native_hook.rs:551-563).
#
# The comparison is gated on both probes having really spoken. `run_follow_
# remediation` already asserts that at each probe site, and this gate repeats
# it so the function cannot be called directly on empty input and answer
# "no worse" about two silences.
assert_no_worse() {
    local before="$1" after="$2"
    local before_denied=0 after_denied=0

    local before_spoke=0 after_spoke=0
    probe_spoke "$before" && before_spoke=1
    probe_spoke "$after" && after_spoke=1
    if [[ "$before_spoke" -eq 0 || "$after_spoke" -eq 0 ]]; then
        local silent="both remediation probes"
        if [[ "$before_spoke" -eq 1 ]]; then
            silent="the AFTER probe"
        elif [[ "$after_spoke" -eq 1 ]]; then
            silent="the BEFORE probe"
        fi
        record_fail "both remediation probes produced a hook response" \
            "$silent produced no hook response; the no-worse comparison is unmeasurable, which is a failure and never a pass"
        return 0
    fi
    record_pass "both remediation probes produced a hook response"

    contains_text "$before" '"permissionDecision":"deny"' && before_denied=1
    contains_text "$after" '"permissionDecision":"deny"' && after_denied=1
    if [[ "$before_denied" -eq 0 ]]; then
        if [[ "$after_denied" -eq 0 ]]; then
            record_pass "following the banner's own remediation did not turn allow into deny"
        else
            record_fail "following the banner's own remediation turned allow into deny" \
                "before was advisory/allow, after denies -- mesh R36d/R36e"
        fi
    else
        record_note "before was already a hard deny" \
            "the no-worse assertion is vacuous here; nothing to compare against"
    fi
}

run_follow_remediation() {
    trap cleanup EXIT
    setup_sandbox

    printf 'shepherd L4 --follow-remediation probe\n'
    printf 'binary    : %s\n' "$BIN"
    printf 'sandbox   : %s\n' "$SANDBOX"
    printf 'version   : %s\n' "$("$BIN" --version 2>&1 || printf 'unknown')"

    heading "STEP 1 · scaffold a fresh project and a planted (non-executing) run"
    "$BIN" init --confirm --no-doctor
    "$BIN" run init "$RUN"

    heading "PROBE BEFORE · unbound PreToolUse, run namespace not yet usable (expect advisory banner)"
    ENVELOPE_JSON="$(envelope_pretooluse_write "$SESSION_REMEDIATION" "$TOOL_USE_REMEDIATION" "x")"
    probe
    local before="$PROBE_OUT"

    # Liveness first, before any branch reads $before. The empty-$commands
    # branch below is the other half of the same hole `assert_no_worse` had:
    # a silent binary yields an empty $before, an empty $before yields no
    # backtick-fenced command, and "banner printed no command to follow" would
    # then record a PASS and return 0 with passed=1 failed=0. Post-fix that is
    # the branch this mode actually takes, so it is the one that most has to
    # be un-foolable.
    if ! assert_probe_spoke "BEFORE" "$before"; then
        heading "RESULT"
        printf 'mode=follow-remediation passed=%d failed=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
        printf 'the BEFORE probe produced no hook response; nothing downstream of it is measurable.\n'
        return 1
    fi

    heading "STEP 2 · parse and execute the banner's own remediation commands, verbatim"
    local commands
    commands="$(extract_backtick_commands "$before")"
    if [[ -z "$commands" ]]; then
        record_pass "banner printed no command to follow"
        heading "RESULT"
        printf 'mode=follow-remediation passed=%d failed=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
        return 0
    fi
    local line run_command
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        run_command="${line/<run>/$RUN}"
        run_command="${run_command#shepherd }"
        printf '+ %s %s\n' "$BIN" "$run_command"
        # shellcheck disable=SC2086  # word-splitting is the point: this is a
        # dynamically parsed command line, not a fixed literal.
        "$BIN" $run_command
    done < <(printf '%s\n' "$commands")

    heading "PROBE AFTER · same unbound session and tool, after following the banner verbatim"
    probe
    local after="$PROBE_OUT"

    if ! assert_probe_spoke "AFTER" "$after"; then
        heading "RESULT"
        printf 'mode=follow-remediation passed=%d failed=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
        printf 'the AFTER probe produced no hook response; the no-worse comparison is unmeasurable.\n'
        return 1
    fi

    heading "ASSERTIONS · --follow-remediation"
    assert_no_worse "$before" "$after"

    heading "RESULT"
    printf 'mode=follow-remediation passed=%d failed=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
    # The TOTAL, not PASS_COUNT: a run in which every assertion FAILED also
    # has PASS_COUNT=0, so testing PASS_COUNT alone reports "zero assertions
    # ran" about a run that ran plenty, and returns before the accurate
    # diagnostic below it. Measured now: pre-fix `--follow-remediation` is
    # `passed=3 failed=1` and no longer reaches this branch at all, precisely
    # because the liveness assertions record passes; the run that genuinely
    # produces `passed=0 failed=1` is a silent-stub binary (accepts every
    # subcommand, exits 0, prints nothing) -- it fails on "BEFORE probe
    # produced a hook response" and records no pass. Only a genuinely empty
    # run may take this branch, and it still fails loudly (G4).
    if [[ $((PASS_COUNT + FAIL_COUNT)) -eq 0 ]]; then
        printf 'zero assertions ran; this gate cannot be trusted at count zero (G4).\n'
        return 1
    fi
    if [[ "$FAIL_COUNT" -ne 0 ]]; then
        printf 'following the banners own remediation made an advisory tool call into a hard deny.\n'
        printf 'mesh R36d/R36e: expected pre-fix, must be gone once L4-S2/S3 land.\n'
        return 1
    fi
    return 0
}

main() {
    parse_args "$@"
    require_cmd git
    require_cmd grep
    require_cmd sed

    if [[ "$FOLLOW_REMEDIATION" -eq 1 ]]; then
        run_follow_remediation
        return $?
    fi

    trap cleanup EXIT
    setup_sandbox

    printf 'shepherd #315/#314/#306 reproduction sandbox\n'
    printf 'mode      : %s\n' "$MODE"
    printf 'binary    : %s\n' "$BIN"
    printf 'sandbox   : %s\n' "$SANDBOX"
    printf 'version   : %s\n' "$("$BIN" --version 2>&1 || printf 'unknown')"

    heading "STEP 1 · scaffold a fresh project and raise one run to executing"
    "$BIN" init --confirm --no-doctor
    "$BIN" run init "$RUN"
    set_status "$RUN" executing
    "$BIN" run layout "$RUN" --repair >/dev/null

    heading "PROBE #315 · unbound session onto a Write tool (expect hard DENY, raw errno)"
    ENVELOPE_JSON="$(envelope_pretooluse_write "$SESSION_315" "$TOOL_USE_315" "x")"
    probe
    local out_315="$PROBE_OUT"
    # Liveness is asserted on each probe's own output, not inferred from a
    # neighbouring assertion. assert_fixed_314 alone checks only that the
    # second output does NOT contain "rejected" and that the two outputs
    # compare -- against a binary printing nothing, both checks pass, and
    # today the mode as a whole only fails because a different assertion
    # (#315 remains fail-closed post-fix) happens to also be watching. An
    # assertion that is sound only because its neighbour is sound is exactly
    # the defect class this harness exists to kill, so every probe gets its
    # own counted liveness check here, before any mode assertion reads it.
    assert_probe_spoke "#315" "$out_315" || true

    heading "PROBE #314a · first SessionStart for $SESSION_314 (expect BIND)"
    ENVELOPE_JSON="$(envelope_session_start "$SESSION_314")"
    probe
    local out_314a="$PROBE_OUT"
    assert_probe_spoke "#314a" "$out_314a" || true

    heading "PROBE #314b · second SessionStart for the SAME session (expect REJECTED)"
    probe
    local out_314b="$PROBE_OUT"
    assert_probe_spoke "#314b" "$out_314b" || true

    heading "PROBE #306 · PreToolUse write into a fresh scratch repo, no \`shepherd init\` at all (project identity absent)"
    setup_sandbox_306
    cd -- "$SANDBOX_306" || die "cannot enter secondary scratch $SANDBOX_306"
    export SHEPHERD_HOME="$SANDBOX_306/isolated-home"
    ENVELOPE_JSON="$(envelope_pretooluse_write "$SESSION_306" "$TOOL_USE_306" "x")"
    probe
    local out_306="$PROBE_OUT"
    cd -- "$SANDBOX" || die "cannot return to primary scratch $SANDBOX"
    assert_probe_spoke "#306" "$out_306" || true
    export SHEPHERD_HOME="$SANDBOX/isolated-home"

    heading "ASSERTIONS · mode=$MODE"
    case "$MODE" in
        expect-abort)
            assert_abort_315 "$out_315"
            assert_abort_314 "$out_314a" "$out_314b"
            assert_306 "$out_306"
            ;;
        expect-fixed)
            assert_fixed_315 "$out_315"
            assert_fixed_314 "$out_314a" "$out_314b"
            assert_306 "$out_306"
            ;;
    esac

    heading "NOTES · #306 message text, not a verdict counted here"
    note_306 "$out_306"

    heading "RESULT"
    printf 'mode=%s passed=%d failed=%d\n' "$MODE" "$PASS_COUNT" "$FAIL_COUNT"
    # The TOTAL, not PASS_COUNT: a run in which every assertion FAILED also
    # has PASS_COUNT=0, so testing PASS_COUNT alone reports "zero assertions
    # ran" about a run that ran plenty, and returns before the accurate
    # diagnostic below it. Measured now: pre-fix `--follow-remediation` is
    # `passed=3 failed=1` and no longer reaches this branch at all, precisely
    # because the liveness assertions record passes; the run that genuinely
    # produces `passed=0 failed=1` is a silent-stub binary (accepts every
    # subcommand, exits 0, prints nothing) -- it fails on "BEFORE probe
    # produced a hook response" and records no pass. Only a genuinely empty
    # run may take this branch, and it still fails loudly (G4).
    if [[ $((PASS_COUNT + FAIL_COUNT)) -eq 0 ]]; then
        printf 'zero assertions ran; this gate cannot be trusted at count zero (G4).\n'
        return 1
    fi
    if [[ "$FAIL_COUNT" -ne 0 ]]; then
        if [[ "$MODE" == "expect-abort" ]]; then
            printf '#315 and/or #314 did NOT reproduce as specified. This harness is only\n'
            printf 'meaningful while it fails loudly here, so this is exit 1.\n'
        else
            printf '#315 and/or #314 is/are STILL present.\n'
        fi
        return 1
    fi
    if [[ "$MODE" == "expect-abort" ]]; then
        printf '#315 and #314 reproduced as specified.\n'
    else
        printf '#315 and #314 are fixed.\n'
    fi
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
