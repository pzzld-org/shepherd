#!/usr/bin/env bash
# hooks/tests/test_exec_bits.sh — regression guard for the v6.1.2 toolkit
# "Permission denied" class (v6.1.3).
#
# WHY: Claude Code invokes hook scripts by PATH (the `command` in hooks.json),
# and `shctx` dispatches its cmd_*.sh by PATH. Both require the git-tracked
# executable bit (100755). But the smoke harness runs scripts via `bash <file>`
# (mode-agnostic), so a script committed as 100644 passes every other test yet
# fails the real invocation — exactly how toolkit_surface.sh + cmd_toolkit.sh
# shipped broken in v6.1.2. This test checks the COMMITTED mode (git index),
# which is what reaches consumers, for every path-invoked script.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fails=0
checked=0

# git ls-files --stage emits: "<mode> <sha> <stage>\t<path>".
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  mode="${line%% *}"
  path="${line#*$'\t'}"
  checked=$((checked+1))
  if [[ "$mode" != "100755" ]]; then
    printf '  FAIL  %s is git-mode %s (must be 100755 — invoked by path)\n' "$path" "$mode"
    fails=$((fails+1))
  fi
done < <(git ls-files --stage -- \
  'hooks/scripts/*.sh' \
  'skills/context/scripts/*.sh' \
  'skills/context/scripts/shctx' 2>/dev/null)

if [[ "$checked" -eq 0 ]]; then
  echo "  FAIL  exec-bits: no path-invoked scripts matched — pathspec drift?" >&2
  exit 1
fi

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d of %d path-invoked script(s) missing the executable bit\n' "$fails" "$checked" >&2
  exit 1
fi

printf '  PASS  all %d path-invoked scripts are executable (100755)\n' "$checked"
