#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
root="$PWD"
codex_bin="${CODEX_BIN:-$(command -v codex)}"
shepherd_bin="${SHEPHERD_NATIVE_BIN:-$root/target/debug/shepherd}"
version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')

# A FLOOR, never an equality. This asserted `== "codex-cli 0.147.0"`, which
# fails the moment upstream Codex ships ANY newer build -- 0.148.0 broke it
# with nothing in this repository having regressed. Pinning a third-party CLI
# to one exact version makes their release schedule our red build, and the
# reflex fix (bump the literal) is a chore that teaches the gate is noise.
# What the contract below actually needs is a Codex new enough to read
# `.codex-plugin/plugin.json`; 0.147.0 is the oldest release verified against
# it, so that is the floor and anything newer passes.
CODEX_VERSION_FLOOR="0.147.0"
codex_version_raw="$($codex_bin --version)"
codex_version="${codex_version_raw#codex-cli }"
[[ "$codex_version_raw" == codex-cli\ * ]] || {
  printf 'FAIL: Codex CLI version string is unparseable: %s\n' "$codex_version_raw" >&2
  exit 1
}
python3 - "$codex_version" "$CODEX_VERSION_FLOOR" <<'VER' || exit 1
import sys
def parts(v):
    return tuple(int(x) for x in v.split(".")[:3])
have, floor = sys.argv[1], sys.argv[2]
try:
    ok = parts(have) >= parts(floor)
except ValueError:
    sys.exit(f"FAIL: unparseable Codex version {have!r}")
if not ok:
    sys.exit(f"FAIL: Codex CLI {have} is older than the {floor} floor this "
             "contract was verified against")
print(f"codex-cli {have} satisfies the {floor} floor")
VER
[[ -x "$shepherd_bin" ]] || { printf 'FAIL: native shepherd binary must be executable at SHEPHERD_NATIVE_BIN or target/debug/shepherd\n' >&2; exit 1; }
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

[[ "$(run_codex plugin marketplace list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["marketplaces"]))')" == 0 ]] || { printf 'FAIL: a fresh CODEX_HOME must start with zero registered marketplaces\n' >&2; exit 1; }
run_codex plugin marketplace add "$root" --json >"$fixture/add.json"
run_codex plugin add shepherd@shepherd --json >"$fixture/install.json"
cache=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["installedPath"])' "$fixture/install.json")
# Compare RESOLVED paths, not raw strings. macOS $TMPDIR ends in a slash, so
# "$TMPDIR/shepherd-..." yields "/var/folders/.../T//shepherd-..." with a
# doubled separator, while Codex reports the normalized path -- and on macOS
# /var is itself a symlink to /private/var, which is why a hand-written
# "/private$fixture" alternative was bolted on here. Two string spellings of
# one directory were being compared as text. Resolve both sides and compare
# the directories. This assertion could not run at all until the codex-cli
# version pin above became a floor, so this defect was latent, not new.
expected_cache="$fixture/codex/plugins/cache/shepherd/shepherd/$version"
resolve_path() { python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
[[ "$(resolve_path "$cache")" == "$(resolve_path "$expected_cache")" ]] || {
  printf 'FAIL: codex plugin add must install shepherd under plugins/cache/shepherd/shepherd/<version>\n  expected: %s\n  actual:   %s\n' \
    "$(resolve_path "$expected_cache")" "$(resolve_path "$cache")" >&2
  exit 1
}
cache=${cache#/private}
[[ -f "$cache/.codex-plugin/plugin.json" ]] || { printf 'FAIL: Codex plugin cache must contain the .codex-plugin/plugin.json manifest\n' >&2; exit 1; }
[[ -f "$cache/codex/hooks/hooks.json" ]] || { printf 'FAIL: Codex plugin cache must contain the codex/hooks/hooks.json manifest\n' >&2; exit 1; }
# DERIVE the count, never hardcode it. The literal here was 7, written when
# the carrier shipped 7 skills; it is 9 today (`plant` was restored this
# sprint), and this assertion never once complained -- the codex-cli version
# pin above exited first, every run. A hardcoded count is a second source of
# truth that drifts silently from the first.
#
# The contract is: the Codex carrier ships every authored skill EXCEPT those
# marked `portability: claude-only`. Compute both sides and compare, so adding
# a skill needs no edit here and removing one cannot pass unnoticed.
expected_skills=$(find content/skills -mindepth 1 -maxdepth 1 -type d | while read -r skill_dir; do
  grep -q '^portability: claude-only' "$skill_dir/SKILL.md" || printf 'x\n'
done | wc -l | tr -d ' ')
actual_skills=$(find "$cache/codex/skills" -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ')
[[ "$expected_skills" -gt 0 ]] || { printf 'FAIL: derived zero cross-harness skills from content/skills -- pathspec drift?\n' >&2; exit 1; }
[[ "$actual_skills" == "$expected_skills" ]] || {
  printf 'FAIL: Codex plugin cache must ship every non-claude-only skill\n  expected: %s (from content/skills)\n  actual:   %s (in carrier)\n' \
    "$expected_skills" "$actual_skills" >&2
  exit 1
}
printf 'codex carrier ships %s/%s cross-harness skills\n' "$actual_skills" "$expected_skills"
[[ -z "$(find "$cache" -type l -print -quit)" ]] || { printf 'FAIL: Codex plugin cache must not contain any symlinks\n' >&2; exit 1; }
[[ ! -e "$cache/package.json" && ! -e "$cache/node_modules" ]] || { printf 'FAIL: Codex plugin cache must not contain package.json or node_modules\n' >&2; exit 1; }

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
printf 'ok: Codex %s installs the regular native Shepherd carrier\n' "$codex_version"
