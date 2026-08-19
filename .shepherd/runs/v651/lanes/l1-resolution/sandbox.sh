#!/usr/bin/env bash
#
# sandbox.sh — reproduce shepherd issue #330 inside a throwaway scratch repo.
#
# #330: a legacy run namespace holding only a `plan.md` and no `run.json` makes
# dispatch-store resolution abort on `open regular file`. The abort reaches the
# operator through `shepherd claude-hook` at two different severities, and which
# one you get is decided by the lifecycle status of the *healthy* run sitting
# beside the legacy directory — not by anything about the legacy directory
# itself. This script drives the three-way severity sweep that proves it
# (planted -> advisory, executing -> deny, planted -> advisory) and then the
# safe-mitigation probe that shows the correct banner already exists in the
# binary and the fix only has to reach it.
#
# ---------------------------------------------------------------------------
# CONTRACT
#
#   usage: sandbox.sh [--mode expect-abort|expect-fixed] [BINARY]
#
#   Binary under test, highest precedence first:
#     1. the first positional argument
#     2. $SHEPHERD_BIN
#     3. <repo root>/target/debug/shepherd, where <repo root> is derived from
#        this script's own location by stripping the trailing
#        `/.shepherd/runs/<run>/lanes/<lane>` segment. Nothing about the run,
#        the lane, or the checkout is baked in, so a later step can run this
#        exact file, unchanged, against a rebuilt binary.
#
#   Modes. The assertion is named and explicit in both directions; the script
#   never silently succeeds when reality disagrees with the mode it was asked
#   to prove:
#     --mode expect-abort  (default) the #330 abort MUST reproduce. Exit 1 if
#                          any probe fails to show it. Use before the fix.
#     --mode expect-fixed  the #330 abort MUST be gone: no probe may name
#                          `runs/v500/run.json`, and the executing probe may not
#                          hard-deny over shepherd's own bookkeeping. Exit 1 if
#                          the abort is still there. Use after the fix.
#
#   Environment:
#     SHEPHERD_BIN    binary under test when no positional argument is given
#     KEEP_SANDBOX=1  keep the scratch directory on exit, for debugging
#
#   Exit codes: 0 every assertion held · 1 an assertion failed · 2 usage error.
#
# ---------------------------------------------------------------------------
# SAFETY
#
#   Every mutation lands inside a `mktemp -d` scratch directory that an EXIT
#   trap removes on every path, and SHEPHERD_HOME is redirected into that same
#   directory so the real user home is never read or written. `shepherd run set
#   <run> --status executing` is aimed at the scratch repo and nowhere else:
#   mesh R36d records that raising the status of a run next to a broken legacy
#   namespace converts a working session into a hard-denied one, so pointing it
#   at a real repository would break that repository's live sessions.
#
#   bash 3.2 compatible (macOS ships 3.2): no associative arrays, no ${var^^},
#   no mapfile/readarray, no `**` globstar.
# ---------------------------------------------------------------------------

set -euo pipefail

# The legacy namespace that has no run.json, and the healthy run beside it.
LEGACY_RUN="v500"
HEALTHY_RUN="v651"
PROBE_SESSION="probe-330"

SANDBOX=""
BIN=""
MODE="expect-abort"
PROBE_OUT=""
PROBE_RC=0
PASS_COUNT=0
FAIL_COUNT=0

usage() {
    cat <<'EOF'
usage: sandbox.sh [--mode expect-abort|expect-fixed] [BINARY]

Reproduce shepherd issue #330 in a self-cleaning scratch repository.

  --mode expect-abort   (default) fail unless the #330 abort reproduces
  --mode expect-fixed   fail unless the #330 abort is gone
  -h, --help            print this help

  BINARY                shepherd binary under test. Falls back to
                        $SHEPHERD_BIN, then to <repo root>/target/debug/shepherd
                        derived from this script's own location.

  KEEP_SANDBOX=1        keep the scratch directory on exit
EOF
}

die() {
    printf 'sandbox.sh: error: %s\n' "$*" >&2
    exit 2
}

heading() {
    printf '\n=== %s ===\n' "$*"
}

record_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf 'PASS  %s\n' "$1"
}

record_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    printf 'FAIL  %s\n' "$1"
    printf '      %s\n' "$2"
}

# A NOTE records an observation that is deliberately NOT a verdict. It never
# touches PASS_COUNT or FAIL_COUNT, so it can never change the exit code. It
# exists so this harness can report a defect that belongs to a DIFFERENT lane
# without failing this one.
record_note() {
    printf '  NOTE  %s\n' "$1"
    if [[ -n "${2:-}" ]]; then
        printf '        %s\n' "$2"
    fi
}

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        record_pass "$name"
    else
        record_fail "$name" "expected output to contain: $needle"
    fi
}

assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        record_fail "$name" "expected output NOT to contain: $needle"
    else
        record_pass "$name"
    fi
}

cleanup() {
    if [[ -n "${KEEP_SANDBOX:-}" ]]; then
        printf '\nsandbox kept at %s (KEEP_SANDBOX set)\n' "$SANDBOX"
        return 0
    fi
    # Idempotent: the trap can fire twice, and -d guards an already-gone dir.
    if [[ -n "$SANDBOX" && -d "$SANDBOX" ]]; then
        rm -rf -- "$SANDBOX"
    fi
}

# Absolute, symlink-resolved directory holding this script.
script_dir() {
    local dir
    dir="$(dirname -- "${BASH_SOURCE[0]}")"
    (cd -- "$dir" && pwd -P)
}

# <repo root>/target/debug/shepherd, derived from this script's location.
# `%` takes the shortest matching suffix, which anchors on the last
# `/.shepherd/runs/` in the path, so the run and lane names never matter.
default_binary() {
    local here root
    here="$(script_dir)"
    root="${here%/.shepherd/runs/*}"
    if [[ "$root" == "$here" ]]; then
        die "cannot derive a repo root from $here; pass the binary explicitly"
    fi
    printf '%s/target/debug/shepherd\n' "$root"
}

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
    # Absolute, because every command below runs with cwd inside the sandbox.
    case "$bin" in
        /*) BIN="$bin" ;;
        *) BIN="$(cd -- "$(dirname -- "$bin")" && pwd -P)/$(basename -- "$bin")" ;;
    esac
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

# A brand-new git repository in scratch space. Nothing here is ever a working
# checkout: shepherd resolves its project root through `git rev-parse`, so the
# scratch repo is the only way to give it a root that is not a real one.
setup_sandbox() {
    local tmp_root
    tmp_root="${TMPDIR:-/tmp}"
    tmp_root="${tmp_root%/}"
    SANDBOX="$(mktemp -d "$tmp_root/shepherd-330-XXXXXX")"
    # Redirect the user home into the sandbox and drop any inherited git
    # pointers, so neither the real home nor a caller's repo is in play.
    export SHEPHERD_HOME="$SANDBOX/isolated-home"
    unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
    cd -- "$SANDBOX" || die "cannot enter scratch directory $SANDBOX"
    git init -q
    git config user.email "probe@shepherd.invalid"
    git config user.name "shepherd 330 probe"
}

# `shepherd claude-hook` reads one PreToolUse envelope on stdin. The tool is a
# trivially safe `echo`, so anything but "allowed" is shepherd talking about
# itself rather than about the tool.
hook_envelope() {
    printf '{"hook_event_name":"PreToolUse","session_id":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
        "$PROBE_SESSION" "$SANDBOX"
}

# Sets PROBE_OUT (stdout+stderr, verbatim) and PROBE_RC, and echoes both.
probe() {
    PROBE_OUT="$(hook_envelope | "$BIN" claude-hook 2>&1)" && PROBE_RC=0 || PROBE_RC=$?
    printf '%s\n' "$PROBE_OUT"
    printf '[exit %d]\n' "$PROBE_RC"
}

set_status() {
    local run="$1" status="$2"
    # Scratch repo only. See SAFETY above.
    "$BIN" run set "$run" --status "$status"
    printf 'run %s status -> %s\n' "$run" "$status"
}

main() {
    parse_args "$@"
    require_cmd git
    require_cmd grep

    trap cleanup EXIT
    setup_sandbox

    printf 'shepherd #330 reproduction sandbox\n'
    printf 'mode      : %s\n' "$MODE"
    printf 'binary    : %s\n' "$BIN"
    printf 'sandbox   : %s\n' "$SANDBOX"
    printf 'version   : %s\n' "$("$BIN" --version 2>&1 || printf 'unknown')"

    heading "STEP 1 · scaffold the layout-v5 namespace"
    "$BIN" init --confirm --no-doctor

    heading "STEP 2 · plant the legacy namespace: plan.md, no run.json"
    mkdir -p ".shepherd/runs/$LEGACY_RUN"
    printf '# legacy\n' > ".shepherd/runs/$LEGACY_RUN/plan.md"
    ls -1 ".shepherd/runs/$LEGACY_RUN"

    heading "STEP 3 · create one healthy run beside it"
    "$BIN" run init "$HEALTHY_RUN"
    cat ".shepherd/runs/$HEALTHY_RUN/run.json"

    heading "PROBE 1 · PreToolUse with $HEALTHY_RUN status=planted (expect ADVISORY, tool allowed)"
    probe
    local planted_a="$PROBE_OUT"

    heading "STEP 4 · raise $HEALTHY_RUN to executing (SANDBOX ONLY — mesh R36d)"
    set_status "$HEALTHY_RUN" executing

    heading "PROBE 2 · PreToolUse with $HEALTHY_RUN status=executing (expect HARD DENY)"
    probe
    local executing="$PROBE_OUT"

    heading "STEP 5 · lower $HEALTHY_RUN back to planted"
    set_status "$HEALTHY_RUN" planted

    heading "PROBE 3 · PreToolUse with $HEALTHY_RUN status=planted again (expect ADVISORY)"
    probe
    local planted_b="$PROBE_OUT"

    heading "STEP 6 · safe mitigation (mesh R36i): give the legacy namespace a run.json"
    printf '{"run":"%s","status":"closed"}\n' "$LEGACY_RUN" \
        > ".shepherd/runs/$LEGACY_RUN/run.json"
    cat ".shepherd/runs/$LEGACY_RUN/run.json"

    heading "PROBE 4 · PreToolUse after the mitigation (expect the correct banner)"
    probe
    local mitigated="$PROBE_OUT"

    heading "ASSERTIONS · mode=$MODE"
    case "$MODE" in
        expect-abort) assert_abort "$planted_a" "$executing" "$planted_b" "$mitigated" ;;
        expect-fixed)
            assert_fixed "$planted_a" "$executing" "$planted_b" "$mitigated"
            heading "NOTES · not verdicts, not counted"
            note_unmasked_315 "$executing"
            ;;
    esac

    heading "RESULT"
    printf 'mode=%s passed=%d failed=%d\n' "$MODE" "$PASS_COUNT" "$FAIL_COUNT"
    if [[ "$FAIL_COUNT" -ne 0 ]]; then
        if [[ "$MODE" == "expect-abort" ]]; then
            printf '#330 did NOT reproduce as specified. This harness is only\n'
            printf 'meaningful while it fails loudly, so this is exit 1.\n'
        else
            printf '#330 is STILL present: a non-run namespace still reached a probe.\n'
        fi
        return 1
    fi
    if [[ "$MODE" == "expect-abort" ]]; then
        printf '#330 reproduced: advisory -> deny -> advisory, mitigated by a stub run.json.\n'
    else
        printf '#330 is fixed: the legacy namespace is inert at every status, and\n'
        printf 'the resolver reaches the pre-existing "no executing shepherd run\n'
        printf 'exists". Any deny above is #315 (lane l4-diagnostics), not this.\n'
    fi
    return 0
}

# Pre-fix expectations. The three-way sweep is the point: the same broken
# legacy directory yields ADVISORY, DENY, ADVISORY purely because the healthy
# run's status moved, which is what makes #330 a severity bug and not just a
# noisy banner.
assert_abort() {
    local planted_a="$1" executing="$2" planted_b="$3" mitigated="$4"

    assert_contains "planted/1 reports no usable run namespace" \
        "$planted_a" "no usable run namespace"
    assert_contains "planted/1 names the missing legacy run.json" \
        "$planted_a" "runs/$LEGACY_RUN/run.json"
    assert_contains "planted/1 names the failing filesystem operation" \
        "$planted_a" 'open regular file'
    assert_contains "planted/1 states the tool was allowed" \
        "$planted_a" "tool allowed"
    assert_not_contains "planted/1 is advisory, not a denial" \
        "$planted_a" '"permissionDecision":"deny"'

    assert_contains "executing hard-denies the tool" \
        "$executing" '"permissionDecision":"deny"'
    assert_contains "executing denies over the missing legacy run.json" \
        "$executing" "runs/$LEGACY_RUN/run.json"
    assert_not_contains "executing offers no advisory escape" \
        "$executing" "tool allowed"

    assert_contains "planted/2 returns to no usable run namespace" \
        "$planted_b" "no usable run namespace"
    assert_contains "planted/2 names the missing legacy run.json" \
        "$planted_b" "runs/$LEGACY_RUN/run.json"
    assert_not_contains "planted/2 is advisory again, not a denial" \
        "$planted_b" '"permissionDecision":"deny"'

    assert_contains "mitigated banner drops the filesystem abort" \
        "$mitigated" "no usable run namespace (no executing shepherd run exists)"
    assert_not_contains "mitigated banner no longer names the legacy run.json" \
        "$mitigated" "runs/$LEGACY_RUN/run.json"
}

# Post-fix expectations for #330 ONLY.
#
# D2's claim is bounded: a directory under `.shepherd/runs/` that is not a run
# is inert. It was never "no PreToolUse call ever denies". Asserting the latter
# would make this lane's gate fail on another lane's open defect forever, so
# the deny is observed and reported, not judged. See the NOTE block below.
#
# Both halves are asserted on purpose. The negative half proves the old abort
# is gone; the positive half proves the resolver landed on the RIGHT error.
# Without the positive half a build that failed some other way would still
# pass, because "does not mention v500" is true of almost any wrong answer.
# Mesh R36h is the point: the correct string already existed in the codebase
# and the fix only had to stop preempting it.
assert_fixed() {
    local planted_a="$1" executing="$2" planted_b="$3" mitigated="$4"

    assert_not_contains "planted/1 no longer names the legacy run.json" \
        "$planted_a" "runs/$LEGACY_RUN/run.json"
    assert_not_contains "planted/1 no longer reports a filesystem abort" \
        "$planted_a" 'open regular file'
    assert_contains "planted/1 reaches the pre-existing NoActiveRun message" \
        "$planted_a" "no usable run namespace (no executing shepherd run exists)"
    assert_contains "planted/1 still allows the tool" \
        "$planted_a" "tool allowed"

    assert_not_contains "executing no longer names the legacy run.json" \
        "$executing" "runs/$LEGACY_RUN/run.json"
    assert_not_contains "executing no longer aborts over any run.json" \
        "$executing" "run.json"

    assert_not_contains "planted/2 no longer names the legacy run.json" \
        "$planted_b" "runs/$LEGACY_RUN/run.json"
    assert_not_contains "planted/2 no longer reports a filesystem abort" \
        "$planted_b" 'open regular file'
    assert_contains "planted/2 reaches the pre-existing NoActiveRun message" \
        "$planted_b" "no usable run namespace (no executing shepherd run exists)"

    assert_not_contains "mitigated no longer names the legacy run.json" \
        "$mitigated" "runs/$LEGACY_RUN/run.json"
    assert_contains "mitigated keeps the NoActiveRun message" \
        "$mitigated" "no usable run namespace (no executing shepherd run exists)"
}

# What #330's repair UNMASKS, reported and never judged.
#
# Mesh R36g: once the stale namespace stops preempting the resolver, the
# status=executing probe denies again -- this time over the real run's missing
# session binding, `runs/<run>/dispatch/.root-session.<session>.json`. That is
# issue #315, it is correctly fail-closed, and it belongs to lane
# `l4-diagnostics`. `L1-S1`'s interfaces name `L4-S1` as this script's
# consumer, so surfacing it here is this harness doing its second job.
note_unmasked_315() {
    local executing="$1"

    if printf '%s' "$executing" | grep -qF -- '"permissionDecision":"deny"'; then
        local path
        path="$(printf '%s' "$executing" | sed -n 's/.*failed for \([^:]*\).*/\1/p')"
        record_note "#315 is now observable: status=executing still denies" \
            "over ${path:-<unparsed path>}"
        record_note "that path is inside a REAL run, not a stale namespace" \
            "issue #315, lane l4-diagnostics -- out of scope for D2, not a #330 regression"
    else
        record_note "status=executing did not deny" \
            "#315 may have been fixed elsewhere; L4-S1 should re-measure"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
