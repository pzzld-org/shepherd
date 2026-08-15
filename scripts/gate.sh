#!/usr/bin/env bash
# gate.sh — the local gate suite, in one place.
#
# WHY ONE SCRIPT.
#
# The gate was previously four commands someone had to remember in the right
# order. A gate remembered as four commands gets run as three, and the one that
# gets dropped is whichever was slowest last time. Naming it once means the
# pre-commit hook, the pre-push hook, `cargo gate`, and CI all run the same
# thing, and adding a check to the gate is one edit rather than five.
#
# TIERS. CLAUDE.md draws the line at two seconds: gate tests are deterministic,
# local, free, and fast enough to run on every commit. Anything that compiles
# the workspace is not that, so it runs on push instead.
#
#   scripts/gate.sh fast     no compilation. formatting + workspace invariants.
#   scripts/gate.sh full     fast + clippy + tests + the feature matrix.
#   scripts/gate.sh wasm     the WASI execution suite (needs wasi-sdk, wasmtime).
#   scripts/gate.sh all      full + wasm.
#
# Default is `full`. Every tier is safe to run on a dirty tree; nothing here
# writes to the repository.
set -euo pipefail

cd "$(dirname "${0}")/.."

TIER="${1:-full}"
FAILURES=0
STARTED="${SECONDS}"

step() {
  local label="${1}"
  shift
  printf '\n\033[1m==> %s\033[0m\n' "${label}"
  if "$@"; then
    return 0
  fi
  printf '\033[31m    FAILED: %s\033[0m\n' "${label}"
  FAILURES=$((FAILURES + 1))
  return 0
}

# ---------------------------------------------------------------- fast --- #
# No compilation. This is what runs on every commit.
gate_fast() {
  step "rustfmt" cargo fmt --all --check
  step "npm adapter dependency rules are falsifiable" node packages/scripts/check-deps.mjs --self-test
  step "npm adapter dependency rules" node packages/scripts/check-deps.mjs
  # The invariants are checked for falsifiability first: a validator with a
  # typo'd key name passes everything forever and is worse than no validator.
  step "workspace invariants are falsifiable" ./scripts/check-workspace.sh --self-test
  step "workspace invariants" ./scripts/check-workspace.sh
  step "WASM release boundary is falsifiable" bash scripts/tests/test-wasm-release-gate.sh
  step "component Node boundary is falsifiable" bash scripts/tests/test-component-node-gate.sh
  step "package distribution boundary is falsifiable" bash scripts/tests/test-package-boundary.sh
  step "generated carrier authority" bash scripts/tests/test-generated-carrier-authority.sh
  step "native CLI authority inventory is falsifiable" python3 scripts/check-cli-authority.py --self-test
  step "native CLI authority inventory" python3 scripts/check-cli-authority.py
  step "release asset inventory" bash scripts/tests/test-release-assets.sh
  step "release installers" bash scripts/tests/test-release-installers.sh
  step "PowerShell installer contract" bash scripts/tests/test-release-installer-powershell-contract.sh
  step "release distribution legal material" bash scripts/tests/test-release-distribution-license.sh
  step "release workflow contract" bash scripts/tests/test-release-workflow.sh
  step "release version authority is falsifiable" python3 scripts/tests/test-version-bump.py
  check_release_version() {
    local version
    version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
    python3 scripts/version-bump.py check --root . --version "$version"
  }
  step "release version authority" check_release_version
  # The plugin layout is an interface contract with the harness. `claude plugin
  # validate` passes clean on a tree whose hooks all point at deleted scripts,
  # so it cannot be the thing that catches this.
  step "plugin contract is falsifiable" ./scripts/check-plugin.py --self-test
  step "plugin contract" ./scripts/check-plugin.py
}

# ---------------------------------------------------------------- full --- #
gate_full() {
  gate_fast
  step "clippy (default)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked
  step "clippy (full)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked --features full
  step "tests" cargo test --workspace --locked
  step "build typed component for adapter package suites" \
    cargo build --locked --release --package shepherd-component --target wasm32-wasip2
  step "component runtime package suite" \
    node --test packages/component-runtime/test/*.test.mjs
  step "Claude adapter package suite" node packages/harness-claude/test.mjs
  step "Codex adapter package suite" node packages/harness-codex/test.mjs
  step "Pi adapter package suite" node packages/harness-pi/test.mjs
  step "canonical Claude carrier is compiler-owned" \
    cargo run --quiet --locked -p shepherd-cli -- \
    compile --target claude --out "$PWD" --check
  compile_ephemeral_carriers() {
    local stage status=0
    stage=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-carriers.XXXXXX")
    cargo run --quiet --locked -p shepherd-cli -- \
      compile --target codex --out "$stage/codex" || status=$?
    if [[ "$status" -eq 0 ]]; then
      cargo run --quiet --locked -p shepherd-cli -- \
        compile --target pi --out "$stage/pi" || status=$?
    fi
    if [[ "$status" -eq 0 ]]; then
      grep -Fq '"target": "codex"' "$stage/codex/.shepherd-generated.json" || status=1
      grep -Fq '"target": "pi"' "$stage/pi/.shepherd-generated.json" || status=1
    fi
    find "$stage" -depth -delete
    return "$status"
  }
  step "canonical Codex and Pi carriers compile from Rust" compile_ephemeral_carriers
  # `cargo check --workspace` builds exactly one feature combination; this is
  # what covers the rest. See the header of scripts/check-features.sh.
  step "feature matrix" ./scripts/check-features.sh
  if command -v cargo-deny >/dev/null 2>&1; then
    step "supply chain" cargo deny --workspace --all-features check
  else
    printf '\n\033[33m==> supply chain SKIPPED\033[0m (cargo-deny absent; scripts/setup.sh installs it)\n'
  fi
}

# ---------------------------------------------------------------- wasm --- #
# The reason the crate split exists. Requires wasi-sdk and wasmtime, so it is
# opt-in locally and always-on in CI (.github/workflows/rust-wasm.yml).
gate_wasm() {
  local missing=0
  local wasm_tools_version="1.254.0"

  # wasm32-unknown-unknown needs a clang with a WebAssembly backend, because
  # `sqlite-wasm-rs` compiles SQLite from C. Apple's system clang has no wasm
  # backend and fails deep inside cc-rs with a wall of `-D` flags that says
  # nothing about the actual cause, so it is worth finding Homebrew's up front.
  #
  # The variables are TARGET-SCOPED (`CC_wasm32_unknown_unknown`), not bare
  # `CC`. A bare `CC` also captures the wasip1 build below, and Homebrew's
  # clang has a wasm backend but no WASI sysroot -- so it compiles the
  # unknown-unknown leg and silently breaks the WASI one. That is exactly what
  # happened the first time this ran. Note underscores: cc-rs reads
  # `CC_wasm32_unknown_unknown`, matching the target triple with `-` replaced.
  local found_clang=0
  for llvm in /opt/homebrew/opt/llvm/bin /usr/local/opt/llvm/bin; do
    if [ -x "${llvm}/clang" ]; then
      export CC_wasm32_unknown_unknown="${llvm}/clang"
      export AR_wasm32_unknown_unknown="${llvm}/llvm-ar"
      found_clang=1
      break
    fi
  done
  if [ "$(uname -s)" = "Darwin" ] && [ "${found_clang}" = "0" ]; then
    printf 'no clang with a wasm backend found (brew install llvm)\n'
    missing=1
  fi

  command -v wasmtime >/dev/null 2>&1 || { printf 'wasmtime not on PATH\n'; missing=1; }
  command -v wasm-tools >/dev/null 2>&1 || { printf 'wasm-tools not on PATH\n'; missing=1; }
  if command -v wasm-tools >/dev/null 2>&1 \
    && [ "$(wasm-tools --version 2>/dev/null)" != "wasm-tools ${wasm_tools_version}" ]; then
    printf 'wasm-tools %s required\n' "${wasm_tools_version}"
    missing=1
  fi
  [ -n "${WASI_SDK_PATH:-}" ] && [ -x "${WASI_SDK_PATH}/bin/clang" ] || {
    printf 'WASI_SDK_PATH unset or not a wasi-sdk install\n'
    missing=1
  }
  if [ "${missing}" = "1" ]; then
    printf '\n\033[31m==> wasm BLOCKED\033[0m (run scripts/setup.sh --wasm)\n'
    return 1
  fi

  # wasm32-unknown-unknown proves reach: no OS, no C toolchain, no filesystem.
  for pkg in shepherd-core shepherd-compiler shepherd shepherd-registry shepherd-render; do
    step "build ${pkg} -> wasm32-unknown-unknown" \
      cargo build --locked --release --package "${pkg}" \
      --target wasm32-unknown-unknown --no-default-features --features wasm
  done

  step "build Shepherd WIT component (wasip2)" \
    cargo build --locked --release --package shepherd-component --target wasm32-wasip2
  step "validate Shepherd WIT component" \
    wasm-tools validate target/wasm32-wasip2/release/shepherd_component.wasm
  extract_component_wit() {
    local artifact="target/wasm32-wasip2/release/shepherd_component.wasm"
    local wit_output="target/wasm32-wasip2/release/shepherd.wit"
    local resolved_imports="${wit_output}.imports"
    local resolved_import_count
    wasm-tools component wit "${artifact}" > "${wit_output}"
    test -s "${wit_output}"
    grep -Fq 'export fl03:shepherd/engine@6.4.5;' "${wit_output}"
    sed -n 's/^  import \(wasi:[^;]*\);$/\1/p' "${wit_output}" \
      | LC_ALL=C sort > "${resolved_imports}"
    resolved_import_count=$(wc -l < "${resolved_imports}" | tr -d ' ')
    test "${resolved_import_count}" -eq 14
    diff -u crates/component/wit/resolved-imports.txt "${resolved_imports}"
  }
  step "extract Shepherd WIT contract" extract_component_wit
  step "call Shepherd component from Node through jco" bash scripts/test-component-node.sh
  step "Claude adapter package suite" node packages/harness-claude/test.mjs
  step "Codex adapter package suite" node packages/harness-codex/test.mjs
  step "Pi adapter package suite" node packages/harness-pi/test.mjs
  step "build and validate the self-contained Claude plugin ZIP" \
    bash scripts/tests/test-claude-plugin-release.sh

  # wasm32-wasip1 proves behaviour. Building only proves the C cross-compile;
  # these tests EXECUTE under wasmtime, and one of them opens a file-backed
  # database and reads a row back through the WASI VFS. SQLite correctly falls
  # back from requested WAL to delete journaling on WASI, whose VFS has no WAL
  # shared-memory locking. Real file persistence is the property
  # wasm32-unknown-unknown cannot satisfy in Node.
  step "execute registry gate tests under wasmtime (wasip1)" \
    cargo test --locked --package shepherd-registry \
    --target wasm32-wasip1 --no-default-features --features wasi
}

case "${TIER}" in
  fast) gate_fast ;;
  full) gate_full ;;
  wasm) gate_wasm ;;
  all)
    gate_full
    gate_wasm
    ;;
  *)
    printf 'usage: scripts/gate.sh [fast|full|wasm|all]\n' >&2
    exit 2
    ;;
esac

ELAPSED=$((SECONDS - STARTED))
printf '\n'
if [ "${FAILURES}" -gt 0 ]; then
  printf '\033[31mgate (%s): %d check(s) failed in %ds\033[0m\n' "${TIER}" "${FAILURES}" "${ELAPSED}"
  exit 1
fi
printf '\033[32mgate (%s): green in %ds\033[0m\n' "${TIER}" "${ELAPSED}"
