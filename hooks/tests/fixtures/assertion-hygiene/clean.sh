#!/usr/bin/env bash
# Fixture: hooks/tests/fixtures/assertion-hygiene/clean.sh
#
# The CLEAN baseline for hooks/tests/lint_shell_assertions.sh's two-sided
# falsification. Every test/search statement below is either:
#   (a) guarded by a trailing `||`/`&&`/`;` operator, per rule R3, or
#   (b) a function's RETURN VALUE -- the next non-blank, non-comment line
#       is a bare `}` -- per rule R4.
# This file must classify as BARE_TOTAL=0 when scanned by itself. The lint
# copies this exact file into $TMPDIR and appends one bare statement per
# falsification case; this tracked copy is never mutated in place.
#
# Not meant to run. Purely a text fixture for the classifier.

set -uo pipefail

# --- Case: house idiom, R2/R3 -----------------------------------------------
# The operator lives INSIDE the brackets (`-n "$a" && -f "$b"`), and the
# statement as a whole is guarded by a trailing `||`. A whole-line scan for
# `&&`/`||` would misread the inner `&&` as the guard and miss that the
# outer `||` is what actually matters -- the classifier instead matches the
# closing `]]` first, then reads the TAIL after it.
check_inputs() {
  local a="$1" b="$2"
  [[ -n "$a" && -f "$b" ]] || { printf 'FAIL: missing a or b\n' >&2; exit 1; }
}

# --- Case: same idiom with (( )) --------------------------------------------
check_count() {
  local n="$1"
  (( n > 0 )) || { printf 'FAIL: count must be positive\n' >&2; exit 1; }
}

# --- Case: same idiom with rg -q --------------------------------------------
check_marker() {
  local file="$1"
  rg -q 'MARKER' "$file" || { printf 'FAIL: marker not found\n' >&2; exit 1; }
}

# --- Case: function-return position, R4 -------------------------------------
# Mirrors hooks/scripts/_lib.sh:120 is_shepherd_project -- a boolean
# predicate, not an assertion. Converting this to `|| { ...; exit 1; }`
# would turn the false branch into a hard exit and break every caller.
is_shepherd_project() {
  local ns
  ns="$(resolve_namespace 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}

# --- Case: function-return position with (( )) ------------------------------
has_positive_count() {
  local n="$1"
  (( n > 0 ))
}
