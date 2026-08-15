#!/usr/bin/env bash
# conformance/run.sh -- byte-exact versioned-contract runner for shepherd.
# Every case freezes the canonical Rust CLI. The release must replay the
# complete corpus byte-for-byte without a legacy implementation.
#
# Usage:
#   conformance/run.sh --impl=rust [--suite=<name>]
#   conformance/run.sh --impl=rust --count [--suite=<name>]
#   conformance/run.sh --impl=rust --verify-checksum
#
# --impl=rust builds the native binary once, then replays the versioned cases.
# --suite=<name> filters the corpus to cases tagged with that suite in
#   their case.json (see conformance/cases/**/case.json). --suite=guard-cli
#   is the MUST-FIX-BEFORE-DISPATCH suite (critic pass 2, HIGH): the five
#   CLI behaviors shepherd's own guard scripts depend on.
# --count prints the (suite-filtered) case count and exits 0, instead of
#   running cases.
# --verify-checksum recomputes conformance/CHECKSUM over cases/** (via
#   scripts/checksum.sh) and diffs it against the committed file -- exits
#   0 only when the corpus is byte-identical to what CHECKSUM records.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
RUNNER_PY="$(command -v python3 2>/dev/null || true)"

usage() {
  printf 'usage: %s --impl=rust [--suite=<name>] [--count] [--verify-checksum]\n' "$(basename "$0")"
}

impl=""
suite=""
mode="run"

for arg in "$@"; do
  case "$arg" in
    --impl=*) impl="${arg#--impl=}" ;;
    --suite=*) suite="${arg#--suite=}" ;;
    --count) mode="count" ;;
    --verify-checksum) mode="verify-checksum" ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'run.sh: unknown arg: %s\n' "$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$impl" ]]; then
  printf 'run.sh: --impl=rust is required\n' >&2
  usage >&2
  exit 2
fi
if [[ "$impl" != "rust" ]]; then
  printf 'run.sh: unknown --impl=%s (want rust)\n' "$impl" >&2
  exit 2
fi

if [[ "$mode" == "verify-checksum" ]]; then
  committed="$HERE/CHECKSUM"
  if [[ ! -s "$committed" ]]; then
    printf 'run.sh --verify-checksum: %s missing or empty\n' "$committed" >&2
    exit 1
  fi
  actual="$("$HERE/scripts/checksum.sh")"
  expected="$(tr -d '[:space:]' <"$committed")"
  if [[ "$actual" != "$expected" ]]; then
    printf 'run.sh --verify-checksum: MISMATCH\n  committed: %s\n  actual:    %s\n' "$expected" "$actual" >&2
    printf 'the corpus (conformance/cases/**) drifted from conformance/CHECKSUM -- regenerate it:\n' >&2
    printf '  conformance/scripts/checksum.sh > conformance/CHECKSUM\n' >&2
    exit 1
  fi
  printf 'run.sh --verify-checksum: OK (%s)\n' "$actual"
  exit 0
fi

if [[ -z "$RUNNER_PY" || ! -x "$RUNNER_PY" ]]; then
  printf 'run.sh: Python 3 is required for the conformance harness\n' >&2
  exit 1
fi

runner_args=(--cases-dir "$HERE/cases" --impl "$impl")
[[ -n "$suite" ]] && runner_args+=(--suite "$suite")
[[ "$mode" == "count" ]] && runner_args+=(--count)

if [[ "$impl" == "rust" && "$mode" != "count" ]]; then
  cargo build --quiet --locked --manifest-path "$REPO_ROOT/Cargo.toml" -p shepherd-cli --bin shepherd
  target_dir="${CARGO_TARGET_DIR:-$REPO_ROOT/target}"
  [[ "$target_dir" = /* ]] || target_dir="$REPO_ROOT/$target_dir"
  rust_bin="$target_dir/debug/shepherd"
  if [[ ! -x "$rust_bin" ]]; then
    printf 'run.sh: Rust binary missing after build: %s\n' "$rust_bin" >&2
    exit 1
  fi
  runner_args+=(--rust-bin "$rust_bin")
fi

exec "$RUNNER_PY" "$HERE/runner.py" "${runner_args[@]}"
