#!/usr/bin/env bash
#
# sandbox.sh — falsify the l5-vocabulary fixes for shepherd issues #324 and #319.
#
# #324: the root role answers to two different names. `models resolve root`
# succeeds while `models resolve shepherd` is refused as an unknown role, even
# though `content/`, the guard engine, the agent cards and the `shepherd:shepherd`
# subagent type all spell that same role `shepherd`.
#
# #319: the seed gate HARD-fails this project's own seeds. `.shepherd/runs/v646/seed.md`
# fails twice — once on a `kind=patch-seed` 200-line cap it exceeds at 393 lines, and
# once on `bin`, a directory that v6.4.6's own decision D4 deleted after the seed was
# written. Both are the same underlying fact: the gate validates a historical artifact
# against the live tree.
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
#     --mode expect-abort  (default) both defects MUST reproduce. Exit 1 if any
#                          probe fails to show them. Use against a pre-fix binary.
#     --mode expect-fixed  both defects MUST be gone, and every negative control
#                          below MUST still hold. Exit 1 otherwise.
#
#   Environment:
#     SHEPHERD_BIN    binary under test when no positional argument is given
#     KEEP_SANDBOX=1  keep the scratch directory on exit, for debugging
#
#   Exit codes: 0 every assertion held · 1 an assertion failed · 2 usage error.
#
#   Assertions only ever match text the CLI actually emits. `seed verify` never
#   prints the run id, so no probe here asserts one; the closed-run finding is
#   recognised by the unresolved PATH plus the literal phrase `run closed`,
#   which is what `crates/cli/src/cmd/wave_b2_seed.rs` emits.
#
# ---------------------------------------------------------------------------
# WHAT THE NEGATIVE CONTROLS ARE FOR
#
#   The #319 change relaxes ONE severity at ONE site under TWO simultaneous
#   conditions. A relaxation is only distinguishable from a disabled check by
#   what still fails, so the controls carry the weight of the proof:
#
#     NC1  path shape is load-bearing. A stray `close.md` sitting beside a seed
#          whose path is NOT `runs/<id>/seed.md` relaxes nothing. This is the
#          control that protects `hooks/scripts/seed_preflight_check.sh`, which
#          runs the live SEED-GATE against a bare `mktemp -t shep-seed.XXXXXX`
#          file in $TMPDIR. Were the path-shape half dropped, any unrelated
#          `close.md` in $TMPDIR would silently downgrade that gate for every
#          seed a planter writes — a gate degrading silently to green, which is
#          this sprint's entire theme.
#     NC2  the $TMPDIR scenario itself, driven literally rather than by analogy.
#     NC3  close.md is load-bearing. The same seed bytes at the same run-shaped
#          path HARD-fail without the sibling close.md.
#     NC4  the relaxation is scoped to the file_scope site. A closed run's seed
#          carrying a TODO: marker still HARD-fails.
#     NC5  400 is a hard ceiling for a sprint-seed.
#     NC6  400 is a hard ceiling for a patch-seed too, so relabelling down buys
#          no slack.
#     NC7  a real historical seed with no close.md (v645) keeps its HARD failures
#          byte-for-byte. "Historical" is not a bypass; "closed" is a fact on disk.
#     NC8  an unknown role is still refused (the #324 alias is one named pair,
#          not a permissive fallthrough).
#
# ---------------------------------------------------------------------------
# SAFETY
#
#   Every mutation lands inside a `mktemp -d` scratch directory that an EXIT
#   trap removes on every path. The script never writes inside the repository:
#   the only repository files it touches are read by `shepherd seed verify`,
#   which is a pure-text reader. No git state is read or written.
#
#   bash 3.2 compatible (macOS ships 3.2): no associative arrays, no ${var^^},
#   no mapfile/readarray, no `**` globstar.
# ---------------------------------------------------------------------------

set -euo pipefail

SANDBOX=""
BIN=""
MODE="expect-abort"
PASS_COUNT=0
FAIL_COUNT=0
OUT=""
RC=0

usage() {
    cat <<'EOF'
usage: sandbox.sh [--mode expect-abort|expect-fixed] [BINARY]

Falsify the l5-vocabulary fixes for shepherd issues #324 and #319.

  --mode expect-abort   (default) fail unless both defects reproduce
  --mode expect-fixed   fail unless both defects are gone and every
                        negative control still holds
  -h, --help            print this help

  BINARY                shepherd binary under test. Falls back to
                        $SHEPHERD_BIN, then to <repo root>/target/debug/shepherd
                        derived from this script's own location.

  KEEP_SANDBOX=1        keep the scratch directory on exit
EOF
}

cleanup() {
    if [[ -n "$SANDBOX" && -d "$SANDBOX" ]]; then
        if [[ "${KEEP_SANDBOX:-0}" == "1" ]]; then
            printf 'sandbox kept at: %s\n' "$SANDBOX" >&2
        else
            rm -rf "$SANDBOX"
        fi
    fi
}
trap cleanup EXIT

# --- argument parsing ------------------------------------------------------

POSITIONAL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            [[ $# -ge 2 ]] || { printf 'error: --mode needs a value\n' >&2; usage >&2; exit 2; }
            MODE="$2"
            shift 2
            ;;
        --mode=*)
            MODE="${1#--mode=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            printf 'error: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
        *)
            [[ -z "$POSITIONAL" ]] || { printf 'error: at most one BINARY argument\n' >&2; exit 2; }
            POSITIONAL="$1"
            shift
            ;;
    esac
done

case "$MODE" in
    expect-abort|expect-fixed) ;;
    *) printf 'error: --mode must be expect-abort or expect-fixed (got: %s)\n' "$MODE" >&2; exit 2 ;;
esac

# --- binary + repo resolution ----------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# <root>/.shepherd/runs/<run>/lanes/<lane>  ->  <root>
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

if [[ -n "$POSITIONAL" ]]; then
    BIN="$POSITIONAL"
elif [[ -n "${SHEPHERD_BIN:-}" ]]; then
    BIN="$SHEPHERD_BIN"
else
    BIN="$REPO_ROOT/target/debug/shepherd"
fi

if [[ ! -x "$BIN" ]]; then
    printf 'error: shepherd binary not found or not executable: %s\n' "$BIN" >&2
    printf 'hint: cargo build --locked -p shepherd-cli --bin shepherd\n' >&2
    exit 2
fi

if [[ ! -d "$REPO_ROOT/.shepherd/runs" ]]; then
    printf 'error: derived repo root has no .shepherd/runs: %s\n' "$REPO_ROOT" >&2
    exit 2
fi

# --- assertion helpers -----------------------------------------------------

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf '  PASS  %s\n' "$1"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    printf '  FAIL  %s\n' "$1"
    if [[ -n "${2:-}" ]]; then
        printf '        %s\n' "$2"
    fi
}

# run_bin <cwd> <args...> — captures combined output in $OUT and exit code in $RC.
run_bin() {
    local cwd="$1"
    shift
    set +e
    OUT="$(cd "$cwd" && "$BIN" "$@" 2>&1)"
    RC=$?
    set -e
}

assert_rc() {
    local name="$1" want="$2"
    if [[ "$RC" -eq "$want" ]]; then
        pass "$name (exit $RC)"
    else
        fail "$name" "expected exit $want, got $RC; output: $OUT"
    fi
}

assert_contains() {
    local name="$1" needle="$2"
    case "$OUT" in
        *"$needle"*) pass "$name" ;;
        *) fail "$name" "expected output to contain: $needle
        actual output: $OUT" ;;
    esac
}

assert_not_contains() {
    local name="$1" needle="$2"
    case "$OUT" in
        *"$needle"*) fail "$name" "expected output NOT to contain: $needle
        actual output: $OUT" ;;
        *) pass "$name" ;;
    esac
}

# seed_body <kind> <total_lines> — emit a seed whose line count, as
# `wave_b2_seed.rs::verify` counts it (trailing newline trimmed, then split on
# '\n'), is exactly <total_lines>.
seed_body() {
    local kind="$1" total="$2" index=0
    printf 'kind: %s\n' "$kind"
    while [[ "$index" -lt $((total - 1)) ]]; do
        printf 'line %s\n' "$index"
        index=$((index + 1))
    done
}

# scope_seed <missing_path> — a minimal seed naming one path that cannot resolve.
scope_seed() {
    printf 'kind: patch-seed\nmilestone: v1\nfile_scope:\n  - %s\n---\n' "$1"
}

SANDBOX="$(mktemp -d 2>/dev/null)" || { printf 'error: mktemp -d failed\n' >&2; exit 2; }

printf '\n'
printf 'sandbox.sh — l5-vocabulary falsification (#324, #319)\n'
printf '  mode:    %s\n' "$MODE"
printf '  binary:  %s\n' "$BIN"
printf '  repo:    %s\n' "$REPO_ROOT"
printf '  scratch: %s\n' "$SANDBOX"
printf '\n'

# ===========================================================================
# #324 — the root role has one name
# ===========================================================================
printf '#324 — models resolve accepts the role by the name every other surface uses\n'

run_bin "$REPO_ROOT" models resolve root --harness claude
assert_rc "canonical: models resolve root --harness claude" 0
ROOT_OUT="$OUT"

run_bin "$REPO_ROOT" models resolve shepherd --harness claude
if [[ "$MODE" == "expect-abort" ]]; then
    assert_rc "DEFECT #324 reproduces: resolve shepherd is refused" 2
    assert_contains "DEFECT #324 reproduces: names shepherd as an unknown role" \
        "unknown role: shepherd"
else
    assert_rc "FIXED #324: resolve shepherd is accepted" 0
    if [[ "$OUT" == "$ROOT_OUT" ]]; then
        pass "FIXED #324: resolve shepherd is byte-identical to resolve root"
    else
        fail "FIXED #324: resolve shepherd is byte-identical to resolve root" \
            "root=[$ROOT_OUT] shepherd=[$OUT]"
    fi
fi

# NC8 — the alias is one named pair, not a permissive fallthrough.
run_bin "$REPO_ROOT" models resolve nonsense --harness claude
assert_rc "NC8: an unknown role is still refused (both modes)" 2
assert_contains "NC8: the refusal still names the offending role" "unknown role: nonsense"

printf '\n'

# ===========================================================================
# #319 — the seed gate accepts the seeds this project actually writes
# ===========================================================================
printf '#319 — the seed gate against the real corpus\n'

run_bin "$REPO_ROOT" seed verify .shepherd/runs/v651/seed.md
assert_rc "this sprint's own seed passes (both modes)" 0

run_bin "$REPO_ROOT" seed verify .shepherd/runs/v646/seed.md
if [[ "$MODE" == "expect-abort" ]]; then
    assert_rc "DEFECT #319 reproduces: v646 HARD-fails" 1
    assert_contains "DEFECT #319 reproduces: the 200-line cap on a 393-line seed" \
        "HARD  footprint 393 lines > cap 200 (kind=patch-seed)"
    assert_contains "DEFECT #319 reproduces: HARD on a path v6.4.6 itself deleted" \
        "HARD  file_scope path does not resolve and is not marked (NEW): bin"
else
    assert_rc "FIXED #319: v646 passes" 0
    assert_not_contains "FIXED #319: no HARD finding remains on v646" "HARD"
    assert_contains "FIXED #319: the footprint mislabel is still reported, as a warn" \
        "warn  footprint 393 lines > patch cap 200 (kind=patch-seed)"
    assert_contains "FIXED #319: the unresolved path is still reported, as a warn" \
        "warn  file_scope path does not resolve: bin (run closed"
fi

# NC7 — v645 is historical too, and has no close.md. Its verdict must not move.
run_bin "$REPO_ROOT" seed verify .shepherd/runs/v645/seed.md
assert_rc "NC7: v645 (historical, no close.md) still HARD-fails (both modes)" 1
assert_contains "NC7: v645 keeps its first HARD file_scope failure" \
    "HARD  file_scope path does not resolve and is not marked (NEW): services/cli"
assert_contains "NC7: v645 keeps its second HARD file_scope failure" \
    "HARD  file_scope path does not resolve and is not marked (NEW): commands"

printf '\n'
printf '#319 — negative controls\n'

# --- NC3 / the closed-run pair: one fact differs, the seed bytes are identical
CLOSED_DIR="$SANDBOX/repo/runs/v999"
mkdir -p "$CLOSED_DIR"
MISSING="$SANDBOX/repo/bin"
scope_seed "$MISSING" > "$CLOSED_DIR/seed.md"

run_bin "$SANDBOX" seed verify "$CLOSED_DIR/seed.md"
assert_rc "NC3: run-shaped path, NO close.md -> HARD (both modes)" 1
assert_contains "NC3: the HARD message is today's, unchanged" \
    "HARD  file_scope path does not resolve and is not marked (NEW): $MISSING"

printf 'closed\n' > "$CLOSED_DIR/close.md"
run_bin "$SANDBOX" seed verify "$CLOSED_DIR/seed.md"
if [[ "$MODE" == "expect-abort" ]]; then
    assert_rc "DEFECT #319 reproduces: a sibling close.md changes nothing" 1
    assert_contains "DEFECT #319 reproduces: still HARD with close.md present" \
        "HARD  file_scope path does not resolve and is not marked (NEW): $MISSING"
else
    assert_rc "FIXED #319: run-shaped path + close.md -> warn, exit 0" 0
    assert_contains "FIXED #319: the warn names the unresolved path and why" \
        "warn  file_scope path does not resolve: $MISSING (run closed"
fi

# --- NC1: path shape is load-bearing.
# Same seed bytes, same sibling close.md, path NOT runs/<id>/seed.md.
FLAT_DIR="$SANDBOX/flat"
mkdir -p "$FLAT_DIR"
scope_seed "$MISSING" > "$FLAT_DIR/shep-seed.ABC123"
printf 'closed\n' > "$FLAT_DIR/close.md"
run_bin "$SANDBOX" seed verify "$FLAT_DIR/shep-seed.ABC123"
assert_rc "NC1: close.md beside a NON run-shaped path relaxes nothing (both modes)" 1
assert_contains "NC1: the HARD failure survives the stray close.md" \
    "HARD  file_scope path does not resolve and is not marked (NEW): $MISSING"

# --- NC2: the $TMPDIR scenario driven literally.
# hooks/scripts/seed_preflight_check.sh runs the live SEED-GATE against
# `mktemp -t shep-seed.XXXXXX`. Reproduce that exactly, with a hostile
# close.md planted in the same temp directory.
FAKE_TMPDIR="$SANDBOX/tmpdir"
mkdir -p "$FAKE_TMPDIR"
printf 'closed\n' > "$FAKE_TMPDIR/close.md"
HOOK_TMP="$(TMPDIR="$FAKE_TMPDIR" mktemp -t shep-seed.XXXXXX)"
scope_seed "$MISSING" > "$HOOK_TMP"
run_bin "$SANDBOX" seed verify "$HOOK_TMP"
assert_rc "NC2: the hook's own mktemp copy is immune to a \$TMPDIR close.md (both modes)" 1
assert_contains "NC2: SEED-GATE still blocks (exit 1 is what the hook denies on)" \
    "HARD  file_scope path does not resolve and is not marked (NEW): $MISSING"

# --- NC4: the relaxation is scoped to the file_scope site.
TODO_DIR="$SANDBOX/repo/runs/v998"
mkdir -p "$TODO_DIR"
printf 'kind: patch-seed\nTODO: resolve before commit\n' > "$TODO_DIR/seed.md"
printf 'closed\n' > "$TODO_DIR/close.md"
run_bin "$SANDBOX" seed verify "$TODO_DIR/seed.md"
assert_rc "NC4: a closed run's TODO: marker still HARD-fails (both modes)" 1
assert_contains "NC4: the relaxation did not leak past the file_scope site" \
    "HARD  TODO:/FIXME: marker(s) present"

# --- NC5 / NC6: 400 is the ceiling for every kind.
seed_body "sprint-seed" 401 > "$SANDBOX/over-sprint.seed.md"
run_bin "$SANDBOX" seed verify "$SANDBOX/over-sprint.seed.md"
assert_rc "NC5: a 401-line sprint-seed is HARD over the 400 ceiling (both modes)" 1
assert_contains "NC5: the ceiling names itself" \
    "HARD  footprint 401 lines > cap 400 (kind=sprint-seed)"

seed_body "patch-seed" 401 > "$SANDBOX/over-patch.seed.md"
run_bin "$SANDBOX" seed verify "$SANDBOX/over-patch.seed.md"
# The control is the exit code, and it is mode-independent: a 401-line
# patch-seed HARD-fails whatever the declared kind buys it. WHICH number it
# names is mode-dependent, and that is the point of the change: before the
# fix the declared kind selected the hard cap (200), after it the kind selects
# only a warn threshold and 400 is the one ceiling.
assert_rc "NC6: a 401-line patch-seed cannot relabel past the ceiling (both modes)" 1
if [[ "$MODE" == "expect-abort" ]]; then
    assert_contains "NC6: before the fix, the declared kind sets the hard cap" \
        "HARD  footprint 401 lines > cap 200 (kind=patch-seed)"
else
    assert_contains "NC6: after the fix, the ceiling is 400 regardless of declared kind" \
        "HARD  footprint 401 lines > cap 400 (kind=patch-seed)"
fi

# --- the tiering change itself: 200 < n <= 400 on a patch-seed.
seed_body "patch-seed" 250 > "$SANDBOX/mislabel.seed.md"
run_bin "$SANDBOX" seed verify "$SANDBOX/mislabel.seed.md"
if [[ "$MODE" == "expect-abort" ]]; then
    assert_rc "DEFECT #319 reproduces: a 250-line patch-seed HARD-fails" 1
    assert_contains "DEFECT #319 reproduces: the declared kind sets a hard cap" \
        "HARD  footprint 250 lines > cap 200 (kind=patch-seed)"
else
    assert_rc "FIXED #319: a 250-line patch-seed warns rather than blocks" 0
    assert_contains "FIXED #319: the warn names the mislabel rather than hiding it" \
        "warn  footprint 250 lines > patch cap 200 (kind=patch-seed)"
fi

# ===========================================================================
printf '\n'
if [[ "$FAIL_COUNT" -eq 0 ]]; then
    if [[ "$PASS_COUNT" -eq 0 ]]; then
        printf 'FAIL: mode=%s ran zero assertions — an empty probe set is not evidence.\n' "$MODE"
        exit 1
    fi
    printf 'OK: mode=%s — %s assertion(s) held, 0 failed.\n' "$MODE" "$PASS_COUNT"
    exit 0
fi

printf 'FAIL: mode=%s — %s assertion(s) failed, %s held.\n' "$MODE" "$FAIL_COUNT" "$PASS_COUNT"
if [[ "$MODE" == "expect-abort" ]]; then
    printf 'If the fix has landed, this is the expected result: the defects no longer reproduce.\n'
else
    printf 'The fix is incomplete or a negative control regressed. Both are blocking.\n'
fi
exit 1
