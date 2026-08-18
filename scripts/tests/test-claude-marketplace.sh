#!/usr/bin/env bash
# Prove Claude dereferences the thin marketplace carrier into an isolated cache
# and executes the installed native hook without a plugin-local Node/npm path.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
marketplace="$repo_root/.claude-plugin/marketplace.json"
carrier_root="$repo_root/plugins/shepherd"
version=$(python3 - "$repo_root/.claude-plugin/plugin.json" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])
PY
)

test -s "$marketplace"
test -d "$carrier_root"

python3 - "$marketplace" "$carrier_root" "$repo_root" "$version" <<'PY'
import json
import pathlib
import sys

marketplace_path = pathlib.Path(sys.argv[1])
carrier_root = pathlib.Path(sys.argv[2])
repo_root = pathlib.Path(sys.argv[3]).resolve()
version = sys.argv[4]
catalog = json.loads(marketplace_path.read_text(encoding="utf-8"))
assert catalog["name"] == "shepherd"
assert catalog["version"] == version
assert len(catalog["plugins"]) == 1
plugin = catalog["plugins"][0]
assert plugin["name"] == "shepherd"
assert plugin["version"] == version
assert plugin["source"] == "./plugins/shepherd"
assert not any(token in json.dumps(plugin).lower() for token in ("archive", ".zip", "releases/download"))

carrier_manifest = carrier_root / ".claude-plugin/plugin.json"
canonical_manifest = repo_root / ".claude-plugin/plugin.json"
assert carrier_manifest.is_file() and not carrier_manifest.is_symlink(), "carrier manifest must be a regular file"
assert carrier_manifest.read_bytes() == canonical_manifest.read_bytes(), "carrier manifest drifted from canonical manifest"

expected = {
    "hooks/hooks.json": "../../../hooks/hooks.json",
    "agents": "../../agents",
    "skills": "../../skills",
}
for relative, target in expected.items():
    path = carrier_root / relative
    assert path.is_symlink(), f"thin carrier link is missing: {relative}"
    assert path.readlink().as_posix() == target, f"unexpected carrier link target: {relative}"
    assert path.resolve().is_relative_to(repo_root), f"carrier link escapes repository: {relative}"

for forbidden in ("package.json", "package-lock.json", "node_modules"):
    assert not (carrier_root / forbidden).exists(), f"thin carrier contains {forbidden}"
PY

python3 - "$repo_root/hooks/hooks.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
hooks = [
    hook
    for groups in manifest["hooks"].values()
    for group in groups
    for hook in group["hooks"]
]
# The four native adapters must be registered exactly as they are, and nothing
# may resolve POLICY through a plugin-local runtime. v6.4.6 re-registered seven
# telemetry-only shell hooks that v6.4.5 had left inert, so a literal TOTAL is
# no longer the property: it counted registrations instead of testing one.
native = {"type": "command", "command": "shepherd", "args": ["claude-hook"]}
adapters = [hook for hook in hooks if hook == native]
assert len(adapters) == 4, f"expected 4 native `shepherd claude-hook` adapters, found {len(adapters)}"
launchers = [
    hook
    for hook in hooks
    if hook != native
    and any(token in json.dumps(hook).lower() for token in ("node", "npx", "python", "poetry"))
]
assert not launchers, f"a registered hook resolves through a plugin-local runtime: {launchers}"
PY

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-claude-marketplace-test.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
isolated_home="$tmp_dir/home"
isolated_config="$tmp_dir/config"
sentinel_bin="$tmp_dir/no-node-npm"
sentinel_log="$tmp_dir/node-npm-invocations.log"
mkdir -p "$isolated_home" "$isolated_config" "$sentinel_bin"
ln -s "$repo_root/scripts/tests/fixtures/node-npm-sentinel.sh" "$sentinel_bin/node"
ln -s "$repo_root/scripts/tests/fixtures/node-npm-sentinel.sh" "$sentinel_bin/npm"
if SHEPHERD_NODE_NPM_SENTINEL_LOG="$sentinel_log" \
  "$sentinel_bin/node" sentinel-self-test >/dev/null 2>&1; then
  printf 'node/npm sentinel unexpectedly returned success\n' >&2
  exit 1
fi
test -s "$sentinel_log"
rm "$sentinel_log"

run_claude() {
  HOME="$isolated_home" CLAUDE_CONFIG_DIR="$isolated_config" PATH="$sentinel_bin:$PATH" \
    SHEPHERD_NODE_NPM_SENTINEL_LOG="$sentinel_log" command claude "$@"
}

assert_installed_carrier() {
  local installed_root=$1
  python3 - "$installed_root" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
assert root.is_dir()
for relative in (".claude-plugin/plugin.json", "hooks/hooks.json", "agents", "skills"):
    path = root / relative
    assert path.exists(), f"installed carrier is missing {relative}"
    assert not path.is_symlink(), f"installed carrier retained a symlink: {relative}"

for path in root.rglob("*"):
    assert not path.is_symlink(), f"installed cache retained a symlink: {path.relative_to(root)}"

for forbidden in ("package.json", "package-lock.json", "node_modules"):
    hits = [str(path.relative_to(root)) for path in root.rglob(forbidden)]
    assert not hits, f"installed carrier contains forbidden Node/npm artifact {forbidden}: {hits}"

manifest = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))
hooks = [hook for groups in manifest["hooks"].values() for group in groups for hook in group["hooks"]]
# The four native adapters must be registered exactly as they are, and nothing
# may resolve POLICY through a plugin-local runtime. v6.4.6 re-registered seven
# telemetry-only shell hooks that v6.4.5 had left inert, so a literal TOTAL is
# no longer the property: it counted registrations instead of testing one.
native = {"type": "command", "command": "shepherd", "args": ["claude-hook"]}
adapters = [hook for hook in hooks if hook == native]
assert len(adapters) == 4, f"expected 4 native `shepherd claude-hook` adapters, found {len(adapters)}"
launchers = [
    hook
    for hook in hooks
    if hook != native
    and any(token in json.dumps(hook).lower() for token in ("node", "npx", "python", "poetry"))
]
assert not launchers, f"a registered hook resolves through a plugin-local runtime: {launchers}"
PY
}

if command -v claude >/dev/null 2>&1; then
  if [[ ! -x "$repo_root/target/debug/shepherd" ]]; then
    cargo build --locked -p shepherd-cli >/dev/null
  fi
  run_claude plugin validate --strict "$marketplace"
  strict_carrier="$tmp_dir/strict-carrier"
  cp -RL "$carrier_root" "$strict_carrier"
  run_claude plugin validate --strict "$strict_carrier"
  run_claude plugin marketplace add "$repo_root" >/dev/null
  available=$(run_claude plugin list --available --json)
  python3 - "$available" "$version" <<'PY'
import json
import sys

catalog = json.loads(sys.argv[1])
shepherd = next((entry for entry in catalog.get("available", []) if entry.get("pluginId") == "shepherd@shepherd"), None)
assert shepherd is not None, "Claude marketplace loader did not expose Shepherd"
assert shepherd["version"] == sys.argv[2]
assert shepherd["source"] == "./plugins/shepherd"
PY
  run_claude plugin install shepherd@shepherd --scope user >/dev/null
  installed=$(run_claude plugin list --json)
  test ! -e "$sentinel_log"
  installed_root=$(python3 - "$installed" "$version" <<'PY'
import json
import sys

installed = json.loads(sys.argv[1])
assert isinstance(installed, list)
shepherd = next((entry for entry in installed if entry.get("id") == "shepherd@shepherd"), None)
assert shepherd is not None, "Claude did not install Shepherd from the marketplace"
assert shepherd["version"] == sys.argv[2]
assert isinstance(shepherd.get("installPath"), str)
print(shepherd["installPath"])
PY
  )
  installed_root=$(cd "$installed_root" && pwd -P)
  assert_installed_carrier "$installed_root"

  hook_output=$(cd "$installed_root" && PATH="$repo_root/target/debug:$PATH" SHEPHERD_HOME="$tmp_dir/shepherd-home" \
    shepherd claude-hook <<'JSON'
{"hook_event_name":"PreToolUse","session_id":"unbound-installed-session","tool_use_id":"installed-hook-tool","tool_name":"Bash","tool_input":{"command":"printf safe"}}
JSON
  )
  python3 - "$hook_output" <<'PY'
import json
import sys

response = json.loads(sys.argv[1])
output = response["hookSpecificOutput"]
assert output["hookEventName"] == "PreToolUse", output

# What this test is actually about: the INSTALLED carrier reaches the native
# binary and answers, without a plugin-local Node or npm path. It previously
# asserted `deny`, which pinned the pre-v6.4.6 behaviour where an unusable run
# namespace refused every tool -- the deadlock that made a broken run
# unrepairable from inside the session that had to repair it. A namespace with
# no executing run now surfaces the fault and allows, so the property here is
# that the hook RESPONDS in one of its two valid shapes, not which one.
assert "permissionDecision" in output or "additionalContext" in output, output
if "additionalContext" in output:
    assert output["additionalContext"].startswith("[shepherd]"), output
PY
  printf 'ok: Claude installed the dereferenced thin carrier and the native hook answered\n'
else
  printf 'SKIP: claude CLI unavailable; thin carrier and native exec-form hook contracts were verified\n'
fi

printf 'ok: Claude marketplace uses the normal thin-carrier install path\n'
