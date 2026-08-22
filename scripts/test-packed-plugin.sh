#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
artifact="${SHEPHERD_COMPONENT_WASM:-target/wasm32-wasip2/release/shepherd_component.wasm}"
if [[ ! -s "$artifact" ]]; then
  printf 'component artifact is missing: %s\n' "$artifact" >&2
  exit 1
fi

node_root="${SHEPHERD_COMPONENT_NODE_ROOT:-$PWD}"
node_root=$(cd "$node_root" && pwd)
jco="$node_root/node_modules/.bin/jco"
if [[ ! -x "$jco" ]]; then
  printf 'locked jco is missing: %s\n' "$jco" >&2
  exit 1
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-packed-plugin.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
stage="$tmp_dir/stage"
mkdir -p "$stage/packages"
for package in component-runtime harness-claude harness-codex harness-pi; do
  cp -R "packages/$package" "$stage/packages/$package"
done
SHEPHERD_COMPONENT_NODE_ROOT="$node_root" SHEPHERD_COMPONENT_WASM="$artifact" \
  scripts/stage-component-runtime.sh "$stage"
scripts/stage-pi-carrier.sh "$stage"
python3 - "$stage/packages/harness-pi/.shepherd-generated.json" <<'PY'
import json
import sys

roles = {role["role"]: role for role in json.load(open(sys.argv[1], encoding="utf-8"))["roles"]}
for role in ("critic", "worker"):
    assert "dispatch" not in roles[role]["capabilities"], f"canonical {role} unexpectedly gained dispatch authority"
for role in ("conductor", "engineer"):
    assert "dispatch" in roles[role]["capabilities"], f"canonical {role} lost dispatch authority"
PY
scripts/stage-distribution-legal.sh "$stage"
ln -s "$node_root/node_modules" "$stage/packages/component-runtime/node_modules"

tarballs="$tmp_dir/tarballs"
mkdir -p "$tarballs"
for package in component-runtime harness-claude harness-codex harness-pi; do
  (
    cd "$stage/packages/$package"
    npm pack --json --ignore-scripts --pack-destination "$tarballs" >/dev/null
  )
done
test -f "$tarballs/pzzld-component-runtime-6.5.6.tgz"
test -f "$tarballs/pzzld-claude-shepherd-6.5.6.tgz"
test -f "$tarballs/pzzld-codex-shepherd-6.5.6.tgz"
test -f "$tarballs/pzzld-pi-shepherd-6.5.6.tgz"
component_listing="$tmp_dir/component-runtime.list"
tar -tzf "$tarballs/pzzld-component-runtime-6.5.6.tgz" > "$component_listing"
grep -Fq 'package/runtime/shepherd-component.js' "$component_listing"
grep -Fq 'package/runtime/shepherd-component.wasm' "$component_listing"
for package in component-runtime harness-claude harness-codex harness-pi; do
  case "$package" in
    component-runtime) archive='pzzld-component-runtime' ;;
    harness-claude) archive='pzzld-claude-shepherd' ;;
    harness-codex) archive='pzzld-codex-shepherd' ;;
    harness-pi) archive='pzzld-pi-shepherd' ;;
  esac
  listing="$tmp_dir/${package}.list"
  tar -tzf "$tarballs/${archive}-6.5.6.tgz" > "$listing"
  grep -Fxq 'package/LICENSE' "$listing"
  grep -Fxq 'package/THIRD_PARTY_NOTICES.md' "$listing"
  grep -Eq '^package/THIRD_PARTY_LICENSES/[0-9a-f]{64}\.txt$' "$listing"
done

pi_archive="$tarballs/pzzld-pi-shepherd-6.5.6.tgz"
pi_listing="$tmp_dir/harness-pi.list"
tar -tzf "$pi_archive" > "$pi_listing"
canonical_roles=(auditor coder conductor critic discovery engineer planter shepherd worker)
dispatchable_roles=(auditor coder conductor critic discovery engineer worker)
for role in "${canonical_roles[@]}"; do
  grep -Fxq "package/prompts/$role.md" "$pi_listing"
done
prompt_count=$(grep -Ec '^package/prompts/[^/]+\.md$' "$pi_listing")
test "$prompt_count" -eq 9
for role in "${dispatchable_roles[@]}"; do
  grep -Fxq "package/agents/$role.md" "$pi_listing"
done
agent_count=$(grep -Ec '^package/agents/[^/]+\.md$' "$pi_listing")
test "$agent_count" -eq 7
! grep -Fxq 'package/agents/shepherd.md' "$pi_listing"
! grep -Fxq 'package/agents/planter.md' "$pi_listing"
pi_extract="$tmp_dir/pi-package"
mkdir -p "$pi_extract"
tar -xzf "$pi_archive" -C "$pi_extract"
for role in "${dispatchable_roles[@]}"; do
  grep -Fxq "name: \"shepherd:$role\"" "$pi_extract/package/agents/$role.md"
  grep -Fxq 'subagentOnlyExtensions: ../src/extension.mjs' "$pi_extract/package/agents/$role.md"
  grep -Eq '^tools: .*\bsubagent\b' "$pi_extract/package/agents/$role.md"
  grep -Fxq 'maxSubagentDepth: 2' "$pi_extract/package/agents/$role.md"
  ! grep -Eq '^model: (sonnet|haiku)$' "$pi_extract/package/agents/$role.md"
done
for role in "${dispatchable_roles[@]}"; do
  grep -Fxq 'model: model-required/model-required' "$pi_extract/package/agents/$role.md"
  ! grep -Fxq 'model: inherit' "$pi_extract/package/agents/$role.md"
done

install="$tmp_dir/install"
mkdir -p "$install"
npm_config_cache="$tmp_dir/npm-cache" \
  npm install --prefix "$install" --ignore-scripts --no-audit --no-fund --no-save \
  "$tarballs/pzzld-component-runtime-6.5.6.tgz" \
  "$tarballs/pzzld-claude-shepherd-6.5.6.tgz" \
  "$tarballs/pzzld-codex-shepherd-6.5.6.tgz" \
  "$tarballs/pzzld-pi-shepherd-6.5.6.tgz" >/dev/null
test -s "$install/node_modules/@pzzld/component-runtime/runtime/shepherd-component.js"
test -s "$install/node_modules/@pzzld/component-runtime/runtime/shepherd-component.wasm"
node packages/scripts/test-active-adapters.mjs \
  "$install/node_modules/@pzzld/component-runtime/runtime/shepherd-component.js" \
  "$install/node_modules/@pzzld"
printf 'ok: clean packed fixture installed all harness packages with adjacent component runtime\n'
