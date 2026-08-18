#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

artifact="${SHEPHERD_COMPONENT_WASM:-target/wasm32-wasip2/release/shepherd_component.wasm}"
if [[ ! -s "$artifact" ]]; then
  printf 'component artifact is missing: %s\n' "$artifact" >&2
  printf 'build with: cargo build --locked --release --package shepherd-component --target wasm32-wasip2\n' >&2
  exit 1
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-component-node.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

# The locked root dependency graph is installed before this probe with npm ci.
# This script never asks npm to resolve, download, or execute anything: a
# clean checkout must provide this exact local jco binary.
node_root="${SHEPHERD_COMPONENT_NODE_ROOT:-$PWD}"
node_root=$(cd "$node_root" && pwd)
jco="$node_root/node_modules/.bin/jco"
if [[ ! -x "$jco" ]]; then
  printf 'locked jco is missing: run npm ci --ignore-scripts from the Node root\n' >&2
  exit 1
fi
(
  cd "$node_root"
  node -e '
    const lock = require("./package-lock.json");
    const pinned = lock.packages?.["node_modules/@bytecodealliance/jco"]?.version;
    const installed = require("./node_modules/@bytecodealliance/jco/package.json").version;
    if (pinned !== "1.28.1" || installed !== pinned) {
      throw new Error("expected locked and installed @bytecodealliance/jco 1.28.1; got " + pinned + "/" + installed);
    }
  '
)

stage_dir="$tmp_dir/runtime"
mkdir -p "$stage_dir"
artifact_dir=$(cd "$(dirname "$artifact")" && pwd)
artifact_name=$(basename "$artifact")
cp "$artifact_dir/$artifact_name" "$stage_dir/shepherd-component.wasm"
cp packages/scripts/test-component-node.mjs "$stage_dir/test-component-node.mjs"
# The conformance oracle travels with the test. Its digests used to be copied
# into the test as literals, which made a content change a seven-file edit and
# left this one -- reachable only from the wasm workflow -- to fail after the
# local gate went green.
cp conformance/content-target-final.json "$stage_dir/content-target-final.json"
mkdir -p "$tmp_dir/component-runtime"
cp -R packages/component-runtime/src "$tmp_dir/component-runtime/"

# jco emits the core modules and JavaScript into the staged runtime. The
# Preview 2 shim remains a symlink to the exact locked dependency tree, and
# the final Node process runs from staging with no repository target/content
# input and no npm invocation.
"$jco" transpile "$stage_dir/shepherd-component.wasm" \
  --out-dir "$stage_dir/component" --name shepherd-component
ln -s "$node_root/node_modules" "$stage_dir/node_modules"
test -s "$stage_dir/component/shepherd-component.js"
test -s "$stage_dir/component/shepherd-component.d.ts"
(
  cd "$stage_dir"
  node ./test-component-node.mjs ./component/shepherd-component.js
)
