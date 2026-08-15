#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
version=$(node -p "require('${repo_root}/packages/harness-claude/package.json').version")
asset="shepherd-claude-plugin-${version}.zip"

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-claude-release-test.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

first="$tmp_dir/first"
second="$tmp_dir/second"
mkdir -p "$first" "$second"

SHEPHERD_COMPONENT_NODE_ROOT="$repo_root" \
  "$repo_root/scripts/build-claude-plugin-release.sh" "$first"
SHEPHERD_COMPONENT_NODE_ROOT="$repo_root" \
  "$repo_root/scripts/build-claude-plugin-release.sh" "$second"

cmp "$first/$asset" "$second/$asset"
cmp "$first/$asset.sha256" "$second/$asset.sha256"

(
  cd "$first"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check "$asset.sha256"
  else
    shasum -a 256 --check "$asset.sha256"
  fi
)

archive_listing="$tmp_dir/archive.txt"
unzip -Z1 "$first/$asset" > "$archive_listing"
if grep -Eq '(^/|(^|/)\.\.(/|$))' "$archive_listing"; then
  printf 'archive contains an unsafe path\n' >&2
  exit 1
fi
for forbidden in '.git/' 'target/' 'packages/component-runtime/test/' 'packages/harness-claude/test/'; do
  if grep -Fq "$forbidden" "$archive_listing"; then
    printf 'archive contains development-only path: %s\n' "$forbidden" >&2
    exit 1
  fi
done
for forbidden in 'commands/' 'services/cli/' 'skills/context/scripts/' 'bin/' 'scripts/'; do
  if grep -Fq "$forbidden" "$archive_listing"; then
    printf 'archive contains retired or non-canonical surface: %s\n' "$forbidden" >&2
    exit 1
  fi
done
if grep -Eq '\.(py|sh)$' "$archive_listing"; then
  printf 'archive contains a Python or Bash implementation surface\n' >&2
  exit 1
fi

plugin="$tmp_dir/plugin root with spaces"
mkdir -p "$plugin"
unzip -q "$first/$asset" -d "$plugin"
test -s "$plugin/LICENSE"
test -s "$plugin/THIRD_PARTY_NOTICES.md"
cmp LICENSE "$plugin/LICENSE"
python3 "$repo_root/scripts/generate-third-party-notices.py" --scope claude --check \
  --output "$plugin/THIRD_PARTY_NOTICES.md" --licenses-dir "$plugin/THIRD_PARTY_LICENSES"
python3 - "$plugin" <<'PY'
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = set(re.findall(r"THIRD_PARTY_LICENSES/([0-9a-f]{64}\.txt)", (root / "THIRD_PARTY_NOTICES.md").read_text()))
actual = {path.name for path in (root / "THIRD_PARTY_LICENSES").glob("*.txt")}
assert expected and actual == expected
for name in actual:
    assert hashlib.sha256((root / "THIRD_PARTY_LICENSES" / name).read_bytes()).hexdigest() == name.removesuffix(".txt")
PY

test -s "$plugin/.claude-plugin/plugin.json"
test ! -e "$plugin/.claude-plugin/marketplace.json"
test -s "$plugin/hooks/hooks.json"
test -x "$plugin/packages/harness-claude/hooks/guard-eval.mjs"
test -x "$plugin/packages/harness-claude/hooks/dispatch-lifecycle.mjs"
test -s "$plugin/packages/component-runtime/runtime/shepherd-component.js"
test -s "$plugin/packages/component-runtime/runtime/shepherd-component.wasm"
test -s "$plugin/packages/component-runtime/runtime/shepherd-component.core.wasm"
test -s "$plugin/node_modules/@bytecodealliance/preview2-shim/LICENSE"

node --input-type=module - "$plugin" <<'NODE'
import assert from "node:assert/strict";
import { accessSync, constants, readFileSync } from "node:fs";
import { join } from "node:path";

const pluginRoot = process.argv[2];
const manifest = JSON.parse(readFileSync(join(pluginRoot, "hooks/hooks.json"), "utf8"));
const expectedTargets = new Set([
  "${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/guard-eval.mjs",
  "${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/dispatch-lifecycle.mjs",
]);
const targets = new Set();
for (const eventEntries of Object.values(manifest.hooks)) {
  for (const entry of eventEntries) {
    for (const hook of entry.hooks) {
      assert.equal(hook.type, "command");
      assert.equal(hook.command, "node", "Claude hook command must not shell-concatenate the script path");
      assert.equal(hook.args?.length, 1, "Claude hook command must pass one script argument");
      assert.equal(typeof hook.args?.[0], "string");
      targets.add(hook.args[0]);
      assert.match(hook.args[0], /^\$\{CLAUDE_PLUGIN_ROOT\}\//);
      const relative = hook.args[0].replace(/^\$\{CLAUDE_PLUGIN_ROOT\}\//, "");
      accessSync(join(pluginRoot, relative), constants.X_OK);
    }
  }
}
assert.deepEqual(targets, expectedTargets);
NODE

test "$(find "$plugin/agents" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')" = 9
test "$(find "$plugin/skills" -mindepth 2 -maxdepth 2 -type f -name SKILL.md | wc -l | tr -d ' ')" = 7
test ! -e "$plugin/commands"
test ! -e "$plugin/services"
test ! -e "$plugin/bin"
test ! -e "$plugin/scripts"
if rg -n '\b(shctx|shepherd_cli)\b' "$plugin" \
  --glob '!node_modules/**' --glob '!README.md' >/dev/null; then
  printf 'archive contains a retired CLI name\n' >&2
  exit 1
fi

fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"
fake_shepherd="$fake_bin/shepherd"
cp "$repo_root/scripts/tests/fixtures/native-dispatch-ok.mjs" "$fake_shepherd"
chmod 755 "$fake_shepherd"

policy_bin="$tmp_dir/policy-bin"
mkdir -p "$policy_bin"
policy_shepherd="$policy_bin/shepherd"
cp "$fake_shepherd" "$policy_shepherd"
node --input-type=module - "$policy_shepherd" <<'NODE'
import { readFileSync, writeFileSync } from "node:fs";

const path = process.argv[2];
const source = readFileSync(path, "utf8");
writeFileSync(path, source.replace('role: "engineer"', 'role: "conductor"'));
NODE

hook_output=$(
  cd "$tmp_dir"
  PATH="$fake_bin:$PATH" env -u SHEPHERD_COMPONENT_MODULE -u SHEPHERD_NATIVE_BIN \
    node "$plugin/packages/harness-claude/hooks/guard-eval.mjs" <<'JSON'
{"hook_event_name":"PreToolUse","session_id":"session-a","tool_use_id":"tool-a","tool_name":"Bash","tool_input":{"command":"printf safe"}}
JSON
)
test -z "$hook_output"

policy_deny_output=$(
  cd "$tmp_dir"
  PATH="$policy_bin:$PATH" env -u SHEPHERD_COMPONENT_MODULE -u SHEPHERD_NATIVE_BIN \
    node "$plugin/packages/harness-claude/hooks/guard-eval.mjs" <<'JSON'
{"hook_event_name":"PreToolUse","session_id":"session-a","tool_use_id":"tool-deny","agent_id":"agent-conductor","agent_type":"conductor","tool_name":"Agent","tool_input":{"target_role":"engineer"}}
JSON
)
node --input-type=module - "$policy_deny_output" <<'NODE'
import assert from "node:assert/strict";

const response = JSON.parse(process.argv[2]);
assert.deepEqual(response, {
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: response.hookSpecificOutput?.permissionDecisionReason,
  },
});
assert.equal(typeof response.hookSpecificOutput.permissionDecisionReason, "string");
assert.notEqual(response.hookSpecificOutput.permissionDecisionReason, "");
NODE

native_failure_output=$(
  cd "$tmp_dir"
  PATH="$fake_bin:$PATH" SHEPHERD_NATIVE_BIN=/usr/bin/false \
    env -u SHEPHERD_COMPONENT_MODULE \
    node "$plugin/packages/harness-claude/hooks/guard-eval.mjs" <<'JSON'
{"hook_event_name":"PreToolUse","session_id":"session-a","tool_use_id":"tool-native-failure","tool_name":"Bash","tool_input":{"command":"printf safe"}}
JSON
)
node --input-type=module - "$native_failure_output" <<'NODE'
import assert from "node:assert/strict";

const response = JSON.parse(process.argv[2]);
assert.deepEqual(response, {
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: response.hookSpecificOutput?.permissionDecisionReason,
  },
});
assert.match(response.hookSpecificOutput.permissionDecisionReason, /unavailable|rejected|failed|exited/i);
NODE

lifecycle_output=$(
  cd "$tmp_dir"
  PATH="$fake_bin:$PATH" env -u SHEPHERD_COMPONENT_MODULE -u SHEPHERD_NATIVE_BIN \
    node "$plugin/packages/harness-claude/hooks/dispatch-lifecycle.mjs" <<'JSON'
{"hook_event_name":"SessionStart","session_id":"session-a","source":"startup"}
JSON
)
test -z "$lifecycle_output"

if command -v claude >/dev/null 2>&1; then
  claude plugin validate --strict "$plugin"
  details=$(claude --plugin-dir "$first/$asset" plugin details shepherd)
  grep -Fq 'Skills (7)' <<<"$details"
  grep -Fq 'Agents (9)' <<<"$details"
  grep -Fq 'Hooks (4)' <<<"$details"
  if grep -Eq '\b(cleanup|ctx|focus|loop|plant|spawn|start)\b' <<<"$details"; then
    printf 'Claude release inventory exposes a retired hand-authored command\n' >&2
    exit 1
  fi
else
  printf 'SKIP: claude CLI is unavailable; archive structure and live hook were still verified\n'
fi

test ! -e "$repo_root/packages/component-runtime/runtime"
printf 'ok: reproducible bundled Claude release ZIP loaded the adjacent component runtime\n'
