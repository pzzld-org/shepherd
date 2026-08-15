#!/usr/bin/env bash
# Canonical project-state location: always <primary-root>/.shepherd.
set -eu -o pipefail

LIB="$(cd "$(dirname "$0")/../scripts" && pwd)/_lib.sh"
fails=0
total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2" >&2; fails=$((fails + 1)); }
assert_eq() {
  total=$((total + 1))
  if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1" "expected '$3', got '$2'"; fi
}

tmp="$(mktemp -d -t shepherd-namespace-contract.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
ROOT="$(git rev-parse --show-toplevel)"
resolve() { ( source "$LIB"; resolve_namespace ); }

assert_eq "default-project-namespace" "$(resolve)" "$ROOT/.shepherd"
mkdir -p "$ROOT/.artifacts"
assert_eq "artifacts-directory-does-not-rebind-namespace" "$(resolve)" "$ROOT/.shepherd"
assert_eq "retired-workdir-variable-is-ignored" \
  "$(SHEPHERD_WORKDIR=other resolve)" "$ROOT/.shepherd"
assert_eq "retired-root-override-is-ignored" \
  "$(SHCTX_ROOT_OVERRIDE=.artifacts resolve)" "$ROOT/.shepherd"

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_resolve_namespace\n'
  exit 0
fi

printf 'FAIL: test_resolve_namespace (%d)\n' "$fails" >&2
exit 1
