#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"

# Source the lib under test. SHCTX_QUIET keeps the split-brain warning
# silent if both .shepherd/ and .artifacts/ happen to coexist.
SHCTX_QUIET=1 source "$SHCTX_SKILL_ROOT/scripts/_lib.sh"

# Both shims must be defined as functions.
if ! declare -F resolve_namespace >/dev/null; then
  echo "FAIL: resolve_namespace not defined after sourcing _lib.sh" >&2; exit 1
fi
if ! declare -F current_sprint >/dev/null; then
  echo "FAIL: current_sprint not defined after sourcing _lib.sh" >&2; exit 1
fi

# Both shims produce non-empty output.
ns=$(resolve_namespace)
[[ -n "$ns" ]] || { echo "FAIL: resolve_namespace produced empty output" >&2; exit 1; }

sprint=$(current_sprint)
[[ -n "$sprint" ]] || { echo "FAIL: current_sprint produced empty output" >&2; exit 1; }

# resolve_namespace should return an absolute path ending in .shepherd or
# .artifacts (matching shctx_artifacts_root's contract).
case "$ns" in
  /*/.shepherd|/*/.artifacts) ;;
  *) echo "FAIL: resolve_namespace output '$ns' is not an absolute .shepherd/.artifacts path" >&2; exit 1 ;;
esac

echo "PASS: helpers_in_ctx_lib"
