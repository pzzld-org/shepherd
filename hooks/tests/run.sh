#!/usr/bin/env bash
# Fast deterministic suite for the native Claude marketplace hook carrier.
#
# WHY discovery is a glob, not a hand-maintained array: `ffd9aea` de-registered
# 6 hooks in hooks.json and shipped green because this runner's array only
# covered 6 of the 27 files in this directory -- the 21 tests covering those
# hooks were never executed. A hand-maintained list silently drifts from the
# directory; a glob cannot. bash 3.2 has no `mapfile`, so discovery is a
# `while read` loop over `find`, not an array literal.

set -euo pipefail

cd "$(dirname "$0")"

tests=()
while IFS= read -r test_file; do
  tests+=("$test_file")
done < <(find . -maxdepth 1 -name '*.sh' ! -name 'run.sh' -exec basename {} \; | sort)

# A runner that discovers zero tests and reports success is exactly the
# failure this file exists to prevent -- fail loudly instead.
if [[ "${#tests[@]}" -eq 0 ]]; then
  printf '  FAIL  run.sh: no test files discovered in %s -- pathspec drift?\n' "$(pwd)" >&2
  exit 1
fi

fails=0
for test_file in "${tests[@]}"; do
  printf '== %s ==\n' "$test_file"
  if output="$(bash "$test_file" 2>&1)"; then
    printf '%s\n' "$output"
  else
    printf '%s\n' "$output"
    fails=$((fails + 1))
  fi
done

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: hooks/tests/run.sh (%d/%d tests ran, 0 failed)\n' "${#tests[@]}" "${#tests[@]}"
  exit 0
fi

printf 'FAIL: hooks/tests/run.sh (%d/%d tests ran, %d failed)\n' "${#tests[@]}" "${#tests[@]}" "$fails" >&2
exit 1
