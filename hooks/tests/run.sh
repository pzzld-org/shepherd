#!/usr/bin/env bash
# Fast deterministic suite for the native Claude marketplace hook carrier.

set -euo pipefail

cd "$(dirname "$0")"
tests=(
  test_native_cli_contract.sh
  test_registered_hook_authority.sh
  test_legacy_policy_retirement.sh
  test_registered_hooks_no_python.sh
  test_hotfix_vehicle_guard.sh
  test_exec_bits.sh
)

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
  printf 'PASS: hooks/tests/run.sh (%d adapter regressions)\n' "${#tests[@]}"
  exit 0
fi

printf 'FAIL: hooks/tests/run.sh (%d/%d regressions failed)\n' "$fails" "${#tests[@]}" >&2
exit 1
