#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
workflow="$repo_root/.github/workflows/rust-wasm.yml"
gate="$repo_root/scripts/gate.sh"
runner="$repo_root/scripts/test-component-node.sh"
node_test="$repo_root/packages/scripts/test-component-node.mjs"

failures=0
check() {
  local label=$1
  local file=$2
  local needle=$3
  if grep -Fq "$needle" "$file"; then
    printf '  PASS %s\n' "$label"
  else
    printf '  FAIL %s\n' "$label"
    failures=$((failures + 1))
  fi
}

check_absent() {
  local label=$1
  local file=$2
  local needle=$3
  if grep -Fq "$needle" "$file"; then
    printf '  FAIL %s\n' "$label"
    failures=$((failures + 1))
  else
    printf '  PASS %s\n' "$label"
  fi
}

check "workflow runs the Node component probe" "$workflow" "bash scripts/test-component-node.sh"
check "local WASM gate runs the Node component probe" "$gate" "scripts/test-component-node.sh"
check "workflow installs the locked Node graph" "$workflow" "npm ci --ignore-scripts"
check "workflow watches WIT changes" "$workflow" "crates/component/wit/**"
check "workflow watches authored content" "$workflow" "content/**"
check "workflow watches adapter and runtime sources" "$workflow" "packages/**"
check "workflow watches root package lock" "$workflow" "package-lock.json"
check "workflow watches Node probe shell script" "$workflow" "scripts/test-component-node.sh"
check "workflow watches Node probe module" "$workflow" "packages/scripts/test-component-node.mjs"
check "probe requires local pinned jco" "$runner" "node_modules/.bin/jco"
check "probe supports an isolated locked Node root" "$runner" "SHEPHERD_COMPONENT_NODE_ROOT"
check "probe verifies locked jco version" "$runner" "1.28.1"
check "probe stages the runtime" "$runner" "stage_dir"
check_absent "probe never provisions jco from the registry" "$runner" "npm exec"
check "Node test calls canonical profile" "$node_test" "engine.canonicalProfile"
check "Node test calls canonical compile" "$node_test" "engine.compileCanonical"
check "Node test probes all canonical targets" "$node_test" "[\"claude\", \"codex\", \"pi\"]"
check "Node test calls canonical guard evaluation" "$node_test" "engine.guardEvalCanonical"
check "workflow runs the Claude package suite" "$workflow" "node packages/harness-claude/test.mjs"
check "workflow runs the Codex package suite" "$workflow" "node packages/harness-codex/test.mjs"
check "workflow runs the Pi package suite" "$workflow" "node packages/harness-pi/test.mjs"
check "workflow audits real package boundaries" "$workflow" "node packages/scripts/check-package-boundary.mjs"
check_absent "Node test avoids retired string guard evaluation" "$node_test" "engine.guardEval("
check "component runtime documents the resolved import count" "$repo_root/crates/component/README.md" "current component imports these 14 WASI Preview 2 interfaces"
check "component runtime documents the resolved import version" "$repo_root/crates/component/README.md" "wasi:cli/environment@0.2.6"
check_absent "component runtime does not claim an absent clock import" "$repo_root/crates/component/README.md" "wasi:clocks/monotonic-clock"
check "component runtime documents the POSIX probe-host limit" "$repo_root/crates/component/README.md" "repository probe is POSIX-only"

if (( failures > 0 )); then
  printf 'FAILED: %d component Node gate invariant(s) missing\n' "$failures"
  exit 1
fi
printf 'ok: component Node gate invariants present\n'
