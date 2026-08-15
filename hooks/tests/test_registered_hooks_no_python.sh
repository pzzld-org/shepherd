#!/usr/bin/env bash
# The marketplace plugin invokes one native command. It must not resolve policy
# through a plugin-local shell or Node runtime.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$ROOT/hooks/hooks.json"
fails=0
checks=0

fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }

commands="$(python3 - "$CONFIG" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
commands = [
    (hook["command"], tuple(hook.get("args", [])))
    for groups in manifest["hooks"].values()
    for group in groups
    for hook in group["hooks"]
]
assert commands and set(commands) == {("shepherd", ("claude-hook",))}
print(len(commands))
PY
)"
pass "registered native hook commands are exact exec-form (${commands})"

if rg -n 'node|hooks/scripts|packages/harness-claude|CLAUDE_PLUGIN_ROOT|\.mjs|\.sh' "$CONFIG"; then
  fail "registered hook manifest has no plugin-local runtime"
else
  pass "registered hook manifest has no plugin-local runtime"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
