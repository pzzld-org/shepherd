#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

output_dir=${1:-}
if [[ -z "$output_dir" ]]; then
  printf 'usage: %s <clean-output-directory>\n' "$0" >&2
  exit 64
fi
mkdir -p "$output_dir"
output_dir=$(cd "$output_dir" && pwd)

version=$(node -p "require('./packages/harness-claude/package.json').version")
manifest_version=$(node -p "require('./.claude-plugin/plugin.json').version")
if [[ "$manifest_version" != "$version" ]]; then
  printf 'Claude manifest version %s does not match adapter version %s\n' \
    "$manifest_version" "$version" >&2
  exit 1
fi

asset="shepherd-claude-plugin-${version}.zip"
asset_path="$output_dir/$asset"
sidecar_path="$asset_path.sha256"
if [[ -e "$asset_path" || -e "$sidecar_path" ]]; then
  printf 'refusing to overwrite Claude release asset: %s\n' "$asset_path" >&2
  exit 1
fi

node_root=${SHEPHERD_COMPONENT_NODE_ROOT:-$repo_root}
node_root=$(cd "$node_root" && pwd)
shim_root="$node_root/node_modules/@bytecodealliance/preview2-shim"
if [[ ! -s "$shim_root/package.json" || ! -s "$shim_root/LICENSE" ]]; then
  printf 'locked Preview 2 shim is missing under %s\n' "$node_root/node_modules" >&2
  exit 1
fi
expected_shim=$(node -p "require('./packages/component-runtime/package.json').dependencies['@bytecodealliance/preview2-shim']")
actual_shim=$(node -p "require('${shim_root}/package.json').version")
if [[ "$actual_shim" != "$expected_shim" ]]; then
  printf 'Preview 2 shim version %s does not match locked runtime dependency %s\n' \
    "$actual_shim" "$expected_shim" >&2
  exit 1
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-claude-release.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
plugin_root="$tmp_dir/plugin"
mkdir -p "$plugin_root/.claude-plugin" \
  "$plugin_root/agents" \
  "$plugin_root/hooks" \
  "$plugin_root/packages/harness-claude" \
  "$plugin_root/skills"

cp .claude-plugin/plugin.json "$plugin_root/.claude-plugin/plugin.json"
scripts/stage-distribution-legal.sh "$plugin_root"
cp packages/harness-claude/README.md "$plugin_root/README.md"

cp agents/*.md "$plugin_root/agents/"
for skill in adaptation bridge context harness motivation shepherd thinking; do
  mkdir -p "$plugin_root/skills/$skill"
  cp "skills/$skill/SKILL.md" "$plugin_root/skills/$skill/SKILL.md"
done

cp packages/harness-claude/hooks/hooks.json "$plugin_root/hooks/hooks.json"

cp packages/harness-claude/package.json packages/harness-claude/README.md \
  "$plugin_root/packages/harness-claude/"
cp -R packages/harness-claude/hooks packages/harness-claude/src \
  "$plugin_root/packages/harness-claude/"

SHEPHERD_COMPONENT_NODE_ROOT="$node_root" \
  scripts/stage-component-runtime.sh "$plugin_root"
mkdir -p "$plugin_root/node_modules/@bytecodealliance"
cp -R "$shim_root" "$plugin_root/node_modules/@bytecodealliance/preview2-shim"

find "$plugin_root/packages/harness-claude/hooks" \
  -type f -name '*.mjs' \
  -exec chmod 755 {} +
find "$plugin_root" -type f -exec touch -t 198001010000 {} +

(
  cd "$plugin_root"
  LC_ALL=C find . -type f -print | LC_ALL=C sort | zip -X -q "$asset_path" -@
)

if command -v sha256sum >/dev/null 2>&1; then
  digest=$(sha256sum "$asset_path" | cut -d ' ' -f 1)
else
  digest=$(shasum -a 256 "$asset_path" | cut -d ' ' -f 1)
fi
printf '%s  %s\n' "$digest" "$asset" > "$sidecar_path"
printf 'built %s\n' "$asset_path"
