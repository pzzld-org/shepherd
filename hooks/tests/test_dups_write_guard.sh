#!/usr/bin/env bash
# v6.4.5 retirement contract for the old Write/Edit field-shape hook.
#
# The Rust engine deliberately refuses stdin-to-file identity for `dups check`.
# A shell hook therefore cannot preserve the old check safely. It must be
# unregistered, not silently downgraded to a no-op.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

if jq -e '[.. | objects | .command? // empty] | any(contains("dups_write_guard.sh")) | not' \
  "$ROOT/hooks/hooks.json" >/dev/null; then
  pass "unsafe-stdin-dups-hook-is-unregistered"
else
  fail "unsafe-stdin-dups-hook-is-unregistered"
fi

set +e
out="$(cd "$ROOT" && printf 'pub struct T { a: u8 }\n' | cargo run --quiet --locked -p shepherd-cli -- dups check --stdin --as src/t.rs --json 2>&1)"
rc=$?
set -e
if [[ "$rc" -ne 0 && "$out" == *'stdin-to-file identity is not descriptor-safe'* ]]; then
  pass "native-engine-refuses-unsafe-stdin-identity"
else
  fail "native-engine-refuses-unsafe-stdin-identity"
  printf '        rc=%s output=%s\n' "$rc" "$out" >&2
fi

if [[ ! -e "$ROOT/hooks/scripts/dups_write_guard.sh" ]]; then
  pass "obsolete-dups-hook-script-is-removed"
else
  fail "obsolete-dups-hook-script-is-removed"
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_dups_write_guard\n'
  exit 0
fi

printf 'FAIL: test_dups_write_guard (%d)\n' "$fails" >&2
exit 1
