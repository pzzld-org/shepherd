#!/usr/bin/env bash
# Fast authority-boundary gate for registered harness hooks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AUDIT="$ROOT/hooks/scripts/hook_authority_inventory.py"
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

if python3 "$AUDIT" --self-test >/dev/null; then
  pass "self-test-detects-retired-and-direct-policy-authorities"
else
  fail "self-test-detects-retired-and-direct-policy-authorities"
fi

if check_out="$(python3 "$AUDIT" --check 2>&1)"; then
  if [[ "$check_out" == *'3 thin, 6 telemetry, 0 independent, 0 nondeterministic'* ]]; then
    pass "registered-hooks-match-machine-readable-inventory"
  else
    fail "registered-hooks-match-machine-readable-inventory"
    printf '        %s\n' "$check_out" >&2
  fi
else
  fail "registered-hooks-match-machine-readable-inventory"
  printf '        %s\n' "$check_out" >&2
fi

inventory="$(python3 "$AUDIT" --json)"
if python3 -c '
import json, sys
inventory = json.load(sys.stdin)
assert inventory["schema"] == "shepherd.hook-authority-inventory/1"
assert len(inventory["entries"]) == 9
assert all(not item["forbidden_source_findings"] for item in inventory["entries"])
assert inventory["counts"]["independent deterministic policy/state authority"] == 0
assert inventory["counts"]["nondeterministic-policy"] == 0
assert {item["classification"] for item in inventory["entries"]} <= {
    "thin component/native adapter",
    "telemetry-only",
}
assert all("workflow_model" not in item["target"] for item in inventory["entries"])
assert all(item["registration_kind"] == "command" for item in inventory["entries"])
' <<<"$inventory"; then
  pass "inventory-is-exact-and-has-no-retired-runtime-authority"
else
  fail "inventory-is-exact-and-has-no-retired-runtime-authority"
fi

if strict_out="$(python3 "$AUDIT" --strict 2>&1)" \
   && [[ "$strict_out" == *'3 thin, 6 telemetry, 0 independent, 0 nondeterministic'* ]]; then
  pass "strict-gate-allows-only-thin-native-adapters-and-telemetry"
else
  fail "strict-gate-allows-only-thin-native-adapters-and-telemetry"
  printf '        %s\n' "${strict_out:-no output}" >&2
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_registered_hook_authority\n'
  exit 0
fi

printf 'FAIL: test_registered_hook_authority (%d)\n' "$fails" >&2
exit 1
