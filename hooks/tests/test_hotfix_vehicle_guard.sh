#!/usr/bin/env bash
# v6.4.5 retirement contract for the old hotfix cardinality hook.
#
# The hook consumed a private temporary handoff with no surviving native
# writer or typed verdict. Keeping it registered would look like enforcement
# while silently allowing every real dispatch, so it must be absent until
# native parity exists.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

if jq -e '[.. | objects | .command? // empty] | any(contains("hotfix_vehicle_guard.sh")) | not' \
  "$ROOT/hooks/hooks.json" >/dev/null; then
  pass "unresolved-hotfix-cardinality-hook-is-unregistered"
else
  fail "unresolved-hotfix-cardinality-hook-is-unregistered"
fi

if [[ ! -e "$ROOT/hooks/scripts/hotfix_vehicle_guard.sh" ]]; then
  pass "obsolete-hotfix-cardinality-script-is-removed"
else
  fail "obsolete-hotfix-cardinality-script-is-removed"
fi

inventory="$(python3 "$ROOT/hooks/scripts/hook_authority_inventory.py" --json)"
if jq -e '[.entries[].target] | index("hooks/scripts/hotfix_vehicle_guard.sh") | not' \
  <<<"$inventory" >/dev/null; then
  pass "authority-inventory-has-no-pretend-hotfix-enforcement"
else
  fail "authority-inventory-has-no-pretend-hotfix-enforcement"
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_hotfix_vehicle_guard\n'
  exit 0
fi

printf 'FAIL: test_hotfix_vehicle_guard (%d)\n' "$fails" >&2
exit 1
