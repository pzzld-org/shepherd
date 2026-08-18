#!/usr/bin/env bash
# The marketplace plugin invokes one native command plus a reviewed set of
# telemetry shims. No registered hook may resolve POLICY through a
# plugin-local shell or Node runtime: every non-native registration must be
# classified `thin component/native adapter` or `telemetry-only` by
# hook_authority_inventory.py, not merely allowlisted by filename. A version
# of this test that only allowlists filenames would look correct and prove
# nothing, so this test shells out to the inventory's own `--json` output
# and reads the classification back.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="${SHEPHERD_LINT_HOOKS_JSON:-$ROOT/hooks/hooks.json}"
AUDIT="$ROOT/hooks/scripts/hook_authority_inventory.py"
AUDIT_ROOT="${SHEPHERD_HOOK_AUTHORITY_ROOT:-$ROOT}"
fails=0
checks=0

fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }

# Registered Node is still never legitimate: no bare `node` runtime, no
# `.mjs` module, ever, regardless of what launches it (including a
# CLAUDE_PLUGIN_ROOT-prefixed command). Registered shell (`hooks/scripts/*.sh`)
# is legitimate now; it is gated below by consulting the inventory instead.
if rg -n '\bnode\b|\.mjs\b' "$CONFIG"; then
  fail "registered hook manifest launches Node (policy must never resolve through Node)"
else
  pass "registered hook manifest launches no Node runtime"
fi

if summary="$(python3 - "$CONFIG" "$AUDIT" "$AUDIT_ROOT" <<'PY'
import json
import re
import subprocess
import sys

config_path, audit_path, audit_root = sys.argv[1:4]
manifest = json.load(open(config_path, encoding="utf-8"))

# The one reviewed native authority. Any command that is not exactly this
# exec-form tuple must be a `hooks/scripts/*.sh` target the inventory
# classifies; anything else resolves policy through an unaudited runtime.
NATIVE_TARGET = "crates/cli/src/cmd/claude_hook.rs"
SCRIPT_RE = re.compile(r"^(?P<target>hooks/scripts/[A-Za-z0-9_.-]+\.sh)$")

native = 0
script_targets = set()
for groups in manifest["hooks"].values():
    for group in groups:
        for hook in group["hooks"]:
            if hook.get("type") != "command":
                continue
            command = hook["command"]
            args = tuple(hook.get("args", []))
            if command == "shepherd" and args == ("claude-hook",):
                native += 1
                continue
            match = SCRIPT_RE.search(command.replace("${CLAUDE_PLUGIN_ROOT}/", ""))
            if match is None:
                sys.exit(
                    f"registered command resolves through an unaudited runtime: {command!r}"
                )
            script_targets.add(match.group("target"))

if native == 0:
    sys.exit("no native `shepherd claude-hook` adapter is registered")

result = subprocess.run(
    [sys.executable, audit_path, "--root", audit_root, "--json"],
    capture_output=True,
    text=True,
)
try:
    inventory = json.loads(result.stdout)
except json.JSONDecodeError:
    sys.exit(
        "hook_authority_inventory.py --json produced no valid JSON: "
        + result.stderr.strip()
    )

classified = {item["target"] for item in inventory["entries"]}
expected = script_targets | {NATIVE_TARGET}
unclassified = expected - classified
if unclassified:
    sys.exit(
        "registered but not classified thin/telemetry in the inventory: "
        f"{sorted(unclassified)}"
    )

print(
    f"{native} native adapter registration(s), "
    f"{len(script_targets)} classified script registration(s)"
)
PY
)"; then
  pass "every non-native registration is classified thin/telemetry by hook_authority_inventory.py (${summary})"
else
  fail "every non-native registration is classified thin/telemetry by hook_authority_inventory.py: ${summary}"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
