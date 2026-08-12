#!/usr/bin/env bash
# hooks/tests/test_resolve_namespace.sh — hooks-side resolve_namespace precedence (GH #121).
#
# The hooks resolve_namespace MUST agree with skills resolve_workdir and
# docs/configuration.md §SHEPHERD_WORKDIR, or hook event logs / dispatch tags /
# locks land in a different namespace than the shctx runtime reads (split-brain).
#
# Precedence under test:
#   1. SHEPHERD_WORKDIR (absolute as-is, else relative to repo_root)
#   2. SHCTX_ROOT_OVERRIDE
#   3. existing .shepherd/  (tie-break winner when both exist)
#   4. existing .artifacts/
#   5. default .shepherd/
#
# Self-contained: no sqlite3. Sources the hooks lib, then pins repo_root by
# running each assertion from inside a throwaway git repo (resolve_namespace
# uses `git rev-parse --show-toplevel`).
set -eu -o pipefail
cd "$(dirname "$0")"
LIB="$(cd ../scripts && pwd)/_lib.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
assert_eq() { total=$((total+1)); if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1" "expected '$3', got '$2'"; fi; }

tmp=$(mktemp -d -t shep-rns-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
ROOT="$(git rev-parse --show-toplevel)"

resolve() { ( source "$LIB"; resolve_namespace ); }
reset_dirs() { rm -rf "$ROOT/.shepherd" "$ROOT/.artifacts"; }

# (a) SHEPHERD_WORKDIR relative → <root>/<rel>
reset_dirs
assert_eq "workdir-relative" "$(SHEPHERD_WORKDIR=work resolve)" "$ROOT/work"
# (a') SHEPHERD_WORKDIR absolute → used as-is
assert_eq "workdir-absolute" "$(SHEPHERD_WORKDIR=/abs/work resolve)" "/abs/work"
# (b) SHCTX_ROOT_OVERRIDE honored at precedence 2
reset_dirs
assert_eq "root-override" "$(SHCTX_ROOT_OVERRIDE=.artifacts resolve)" "$ROOT/.artifacts"
# (c) only .artifacts present → .artifacts (legacy auto-pickup)
reset_dirs; mkdir -p "$ROOT/.artifacts"
assert_eq "fallback-artifacts" "$(resolve)" "$ROOT/.artifacts"
# (d) only .shepherd present → .shepherd
reset_dirs; mkdir -p "$ROOT/.shepherd"
assert_eq "fallback-shepherd" "$(resolve)" "$ROOT/.shepherd"
# (e) BOTH present → .shepherd wins the tie-break (matches skills lib)
reset_dirs; mkdir -p "$ROOT/.shepherd" "$ROOT/.artifacts"
assert_eq "split-brain-picks-shepherd" "$(resolve)" "$ROOT/.shepherd"
# (f) neither present → default .shepherd
reset_dirs
assert_eq "default-shepherd" "$(resolve)" "$ROOT/.shepherd"

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
