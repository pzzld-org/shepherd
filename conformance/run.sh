#!/usr/bin/env bash
# conformance/run.sh -- byte-exact behavioral-oracle runner for the shepherd
# CLI (W0-S9, #281). Freezes the CURRENT Python CLI's observable behavior
# (services/cli/shepherd_cli) into conformance/cases/**, so the Rust port
# (W1-W3) can be graded against it instead of by eyeball.
#
# Usage:
#   conformance/run.sh --impl=<python|rust> [--suite=<name>]
#   conformance/run.sh --impl=<python|rust> --count [--suite=<name>]
#   conformance/run.sh --impl=<python|rust> --verify-checksum
#
# --impl=python drives the corpus against the REAL Python CLI via
#   ${PY} -m shepherd_cli ... (conformance/lib/harness.py; the same
#   invocation shape services/cli/tests/conftest.py's run_cli() uses, and
#   the one bin/shepherd's own python3-fallback path reaches).
# --impl=rust is a REAL BUT EMPTY lane: no Rust port exists yet (W1-W3
#   build it) -- this always reports "0 cases implemented" and exits 0, so
#   the wave-0 gate script (plan.md's W0-GATE) has a runnable target from
#   day one and nothing errors just because the port hasn't landed.
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
CLI_ROOT="$REPO_ROOT/services/cli"
PY="$CLI_ROOT/.venv/bin/python"

usage() {
  printf 'usage: %s --impl=<python|rust> [--suite=<name>] [--count] [--verify-checksum]\n' "$(basename "$0")"
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
  printf 'run.sh: --impl=<python|rust> is required\n' >&2
  usage >&2
  exit 2
fi
if [[ "$impl" != "python" && "$impl" != "rust" ]]; then
  printf 'run.sh: unknown --impl=%s (want python|rust)\n' "$impl" >&2
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

if [[ "$impl" == "rust" ]]; then
  # No Rust port exists yet (W1-W3 build it) -- real-but-empty lane per
  # plan.md W0-S9 action 5. Always exits 0: this is what makes W0-GATE's
  # `conformance/run.sh --impl=rust; test $? -eq 0` pass long before any
  # Rust code lands.
  if [[ "$mode" == "count" ]]; then
    printf '0\n'
    exit 0
  fi
  printf 'conformance --impl=rust: 0 cases implemented (Rust port not yet built -- W1-W3)\n'
  exit 0
fi

# impl == python from here on.
if [[ ! -x "$PY" ]]; then
  printf 'run.sh: CLI venv missing at %s -- run bin/shepherd-venv-ensure first\n' "$PY" >&2
  exit 1
fi

runner_args=(--cases-dir "$HERE/cases")
[[ -n "$suite" ]] && runner_args+=(--suite "$suite")
[[ "$mode" == "count" ]] && runner_args+=(--count)

exec "$PY" "$HERE/runner.py" "${runner_args[@]}"
