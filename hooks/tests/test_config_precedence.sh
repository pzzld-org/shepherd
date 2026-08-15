#!/usr/bin/env bash
# Canonical hook-side configuration contract.
#
# Hooks must use the same four/six candidate chain as the Rust loader:
# project `.shepherd` local/harness/base, then user-home local/harness/base.
# Legacy `.claude`, `.artifacts`, XDG, and shctx-specific inputs are excluded.
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

tmp="$(mktemp -d -t shepherd-config-contract.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
ROOT="$(git rev-parse --show-toplevel)"
USER_HOME="$tmp/user-home"
mkdir -p "$ROOT/.shepherd" "$USER_HOME"
USER_HOME="$(cd "$USER_HOME" && pwd -P)"
export SHEPHERD_HOME="$USER_HOME"
unset CLAUDE_PLUGIN_ROOT CLAUDECODE CODEX_HOME SHEPHERD_HARNESS XDG_CONFIG_HOME SHCTX_ROOT_OVERRIDE SHEPHERD_WORKDIR 2>/dev/null || true

config_files() { ( source "$LIB"; shepherd_config_files ); }
get_key() { ( source "$LIB"; cfg_get "$1" ); }
get_section_key() { ( source "$LIB"; cfg_section_get "$1" "$2" ); }
is_project() { ( source "$LIB"; is_shepherd_project ); }
write_value() { printf '[spawn]\nmax_parallel = %s\n' "$2" > "$1"; }

# No harness selected: exactly four canonical candidates, in resolution order.
expected="$ROOT/.shepherd/shepherd.local.toml
$ROOT/.shepherd/shepherd.toml
$USER_HOME/shepherd.local.toml
$USER_HOME/shepherd.toml"
assert_eq "canonical-config-chain-without-harness" "$(config_files 2>/dev/null || true)" "$expected"

# The first existing value wins across the same order.
write_value "$USER_HOME/shepherd.toml" 1
assert_eq "user-base" "$(get_key max_parallel)" 1
write_value "$USER_HOME/shepherd.local.toml" 2
assert_eq "user-local-overrides-user-base" "$(get_key max_parallel)" 2
write_value "$ROOT/.shepherd/shepherd.toml" 3
assert_eq "project-base-overrides-user" "$(get_key max_parallel)" 3
write_value "$ROOT/.shepherd/shepherd.local.toml" 4
assert_eq "project-local-overrides-project-base" "$(get_key max_parallel)" 4
assert_eq "section-reader-uses-same-winner" "$(get_section_key spawn max_parallel)" 4

# Active-harness selection adds only the active harness file at each tier.
expected_claude="$ROOT/.shepherd/shepherd.local.toml
$ROOT/.shepherd/shepherd.claude.toml
$ROOT/.shepherd/shepherd.toml
$USER_HOME/shepherd.local.toml
$USER_HOME/shepherd.claude.toml
$USER_HOME/shepherd.toml"
assert_eq "canonical-config-chain-with-claude-harness" \
  "$(SHEPHERD_HARNESS=claude config_files 2>/dev/null || true)" "$expected_claude"
find "$ROOT/.shepherd/shepherd.local.toml" -type f -delete
printf '[spawn]\nmax_parallel = 91\n' > "$ROOT/.shepherd/shepherd.codex.toml"
printf '[spawn]\nmax_parallel = 5\n' > "$ROOT/.shepherd/shepherd.toml"
assert_eq "inactive-harness-file-is-ignored" \
  "$(SHEPHERD_HARNESS=claude get_key max_parallel)" 5

# A legacy location cannot activate a project or change resolution.
find "$ROOT/.shepherd" -depth -delete
mkdir -p "$ROOT/.claude"
printf '[spawn]\nmax_parallel = 99\n' > "$ROOT/.claude/shepherd.toml"
total=$((total + 1))
if is_project; then fail "legacy-claude-config-does-not-activate-project" "legacy path was accepted"; else pass "legacy-claude-config-does-not-activate-project"; fi
assert_eq "legacy-claude-config-is-not-read" "$(get_key max_parallel)" 2

mkdir -p "$ROOT/.shepherd"
: > "$ROOT/.shepherd/shepherd.toml"
total=$((total + 1))
if is_project; then pass "canonical-project-config-activates-hooks"; else fail "canonical-project-config-activates-hooks" "canonical path was not accepted"; fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_config_precedence\n'
  exit 0
fi

printf 'FAIL: test_config_precedence (%d)\n' "$fails" >&2
exit 1
