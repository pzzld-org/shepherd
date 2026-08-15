#!/usr/bin/env bash
# Regression harness for the legacy-command disposition and public CLI
# authority checks. The gate itself supplies deliberate broken fixtures.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$ROOT/scripts/check-cli-authority.py"

python3 "$GATE" --self-test
python3 "$GATE"

test ! -e "$ROOT/services/cli"
test ! -e "$ROOT/skills/context/scripts"
if rg -n '"authority"[[:space:]]*:[[:space:]]*"python-legacy"|unsupported_pending_parity' \
  "$ROOT/conformance/cases" "$ROOT/conformance/legacy-command-disposition.json"; then
  printf '%s\n' 'legacy CLI implementation or pending route disposition remains' >&2
  exit 1
fi

test ! -e "$ROOT/bin/shepherd-venv-ensure"
test ! -e "$ROOT/hooks/scripts/session_venv.sh"
test ! -e "$ROOT/hooks/tests/test_cli_venv_selfheal.sh"

if rg -n '(session_venv|shepherd-venv-ensure|poetry)' \
  "$ROOT/hooks/hooks.json" "$ROOT/hooks/scripts" "$ROOT/bin"; then
  printf '%s\n' 'legacy interpreter bootstrap remains in an active launcher path' >&2
  exit 1
fi

transport="$ROOT/packages/component-runtime/src/native-transport.mjs"
claude_hook="$ROOT/crates/cli/src/cmd/claude_hook.rs"
test -f "$transport"
test -f "$claude_hook"
python3 - "$ROOT/hooks/hooks.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
hooks = [
    hook
    for groups in manifest["hooks"].values()
    for group in groups
    for hook in group["hooks"]
]
assert hooks and all(hook == {"type": "command", "command": "shepherd", "args": ["claude-hook"]} for hook in hooks)
PY
rg -q 'plan_lifecycle' "$claude_hook"
rg -q 'DispatchService::with_context' "$claude_hook"
rg -q 'GuardValue::from' "$claude_hook"

# Published adapters resolve one native CLI contract: an explicit
# SHEPHERD_NATIVE_BIN wins, otherwise the bare `shepherd` command is handed to
# the host PATH. They must not bake a source-checkout repository path into the
# published lifecycle.
rg -q 'SHEPHERD_NATIVE_BIN' "$transport"
rg -q '[:?] "shepherd"' "$transport"
if rg -n 'repositoryRoot|join\([^)]*bin[^)]*shepherd|/bin/shepherd' "$transport"; then
  printf '%s\n' 'published native transport contains a checkout-specific CLI path' >&2
  exit 1
fi
node --test "$ROOT/packages/component-runtime/test/native-transport.test.mjs"

printf '%s\n' 'check-cli-authority: SessionStart retains native dispatch binding without a legacy runtime bootstrap'
