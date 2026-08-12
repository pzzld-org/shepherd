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
  # The invariants are checked for falsifiability first: a validator with a
  # typo'd key name passes everything forever and is worse than no validator.
  step "workspace invariants are falsifiable" ./scripts/check-workspace.sh --self-test
  step "workspace invariants" ./scripts/check-workspace.sh
}

# ---------------------------------------------------------------- full --- #
gate_full() {
  gate_fast
  step "clippy (default)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked
  step "clippy (full)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked --features full
  step "tests" cargo test --workspace --locked
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
  command -v wasmtime >/dev/null 2>&1 || { printf 'wasmtime not on PATH\n'; missing=1; }
  [ -n "${WASI_SDK_PATH:-}" ] && [ -x "${WASI_SDK_PATH}/bin/clang" ] || {
    printf 'WASI_SDK_PATH unset or not a wasi-sdk install\n'
    missing=1
  }
  if [ "${missing}" = "1" ]; then
    printf '\n\033[33m==> wasm SKIPPED\033[0m (run scripts/setup.sh --wasm)\n'
    return 0
  fi

  # wasm32-unknown-unknown proves reach: no OS, no C toolchain, no filesystem.
  for pkg in shepherd-core shepherd shepherd-registry shepherd-render; do
    step "build ${pkg} -> wasm32-unknown-unknown" \
      cargo build --locked --release --package "${pkg}" \
      --target wasm32-unknown-unknown --no-default-features --features wasm
  done

  # wasm32-wasip1 proves behaviour. Building only proves the C cross-compile;
  # these tests EXECUTE under wasmtime, and one of them opens a WAL database as
  # a real file and reads a row back through the WASI VFS. That is the property
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
