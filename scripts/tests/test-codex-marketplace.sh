#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
root="$PWD"
codex_bin="${CODEX_BIN:-$(command -v codex)}"
shepherd_bin="${SHEPHERD_NATIVE_BIN:-$root/target/debug/shepherd}"
version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')

[[ "$($codex_bin --version)" == "codex-cli 0.147.0" ]]
[[ -x "$shepherd_bin" ]]
python3 - "$root" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
market = json.loads((root / ".agents/plugins/marketplace.json").read_text())
assert market == {
    "name": "shepherd",
    "interface": {"displayName": "Shepherd"},
    "plugins": [{
        "name": "shepherd",
        "source": {"source": "local", "path": "./plugins/shepherd"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "development",
    }],
}
carrier = root / "plugins/shepherd"
manifest = json.loads((carrier / ".codex-plugin/plugin.json").read_text())
assert manifest["name"] == "shepherd"
assert manifest["skills"] == "./codex/skills/"
assert manifest["hooks"] == "./codex/hooks/hooks.json"
hooks = json.loads((carrier / "codex/hooks/hooks.json").read_text())
assert set(hooks["hooks"]) == {"SessionStart", "PreToolUse"}
handlers = [hook for groups in hooks["hooks"].values() for group in groups for hook in group["hooks"]]
assert handlers and all(hook["command"] == "shepherd codex-hook" for hook in handlers)
assert all("args" not in hook for hook in handlers)
assert not any(path.is_symlink() for path in (carrier / "codex").rglob("*"))
# MINUS the claude-only skills. An exact match with the Claude tree is what
# shipped `skills/harness/` -- Agent Teams, Dynamic Workflows, `ToolSearch` --
# into the Codex carrier, on a platform that has none of them.
import re as _re
claude_only = set()
for authored in sorted((root / "content/skills").glob("*/SKILL.md")):
    text = authored.read_text()
    end = text.find("\n---", 4) if text.startswith("---\n") else -1
    if end != -1 and _re.search(r"^portability:\s*claude-only\s*$", text[4:end], _re.M):
        claude_only.add(authored.parent.name)
source = [p for p in sorted((root / "skills").glob("*/SKILL.md")) if p.parent.name not in claude_only]
projected = sorted((carrier / "codex/skills").glob("*/SKILL.md"))
assert [p.parent.name for p in source] == [p.parent.name for p in projected], (
    f"expected {[p.parent.name for p in source]}, found {[p.parent.name for p in projected]}"
)
assert claude_only, "no skill is marked claude-only; this filter would be a no-op"
for left, right in zip(source, projected, strict=True):
    assert left.read_bytes() == right.read_bytes(), right
PY

fixture=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-codex-marketplace.XXXXXX")
trap 'find "$fixture" -depth -delete' EXIT
mkdir -p "$fixture/home" "$fixture/codex"
run_codex() { env HOME="$fixture/home" CODEX_HOME="$fixture/codex" "$codex_bin" "$@"; }

[[ "$(run_codex plugin marketplace list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["marketplaces"]))')" == 0 ]]
run_codex plugin marketplace add "$root" --json >"$fixture/add.json"
run_codex plugin add shepherd@shepherd --json >"$fixture/install.json"
cache=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["installedPath"])' "$fixture/install.json")
[[ "$cache" == "$fixture/codex/plugins/cache/shepherd/shepherd/$version" || "$cache" == "/private$fixture/codex/plugins/cache/shepherd/shepherd/$version" ]]
cache=${cache#/private}
[[ -f "$cache/.codex-plugin/plugin.json" ]]
[[ -f "$cache/codex/hooks/hooks.json" ]]
[[ "$(find "$cache/codex/skills" -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ')" == 7 ]]
[[ -z "$(find "$cache" -type l -print -quit)" ]]
[[ ! -e "$cache/package.json" && ! -e "$cache/node_modules" ]]

bin_dir=$(dirname "$shepherd_bin")
repo="$fixture/project"
mkdir -p "$repo/.shepherd/runs/v645"
git -C "$repo" init --quiet
printf '%s' '{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a","scaffolded_at":1000}' >"$repo/.shepherd/project.json"
printf '%s' '{"run":"v645","status":"executing"}' >"$repo/.shepherd/runs/v645/run.json"
(
  cd "$repo"
  env PATH="$bin_dir:$PATH" SHEPHERD_HOME="$fixture/shepherd-home" sh -c 'shepherd codex-hook' <<'JSON' >"$fixture/session.json"
{"hook_event_name":"SessionStart","session_id":"codex-marketplace-session","provider_version":"0.147.0"}
JSON
  env PATH="$bin_dir:$PATH" SHEPHERD_HOME="$fixture/shepherd-home" sh -c 'shepherd codex-hook' <<'JSON' >"$fixture/deny.json"
{"hook_event_name":"PreToolUse","session_id":"unbound","tool_use_id":"deny-1","tool_name":"apply_patch","tool_input":{"patch":"change"}}
JSON
)
python3 - "$fixture/session.json" "$fixture/deny.json" <<'PY'
import json, sys
session, denial = (json.load(open(path)) for path in sys.argv[1:])
assert session["hookSpecificOutput"]["hookEventName"] == "SessionStart"
assert denial["hookSpecificOutput"]["permissionDecision"] == "deny"
PY
printf 'ok: Codex 0.147.0 installs the regular native Shepherd carrier\n'
