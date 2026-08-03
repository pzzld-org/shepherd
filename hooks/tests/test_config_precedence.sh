#!/usr/bin/env bash
# hooks/tests/test_config_precedence.sh — v6.4.2 config precedence contract (bash side).
#
# Lane P2 pins the SAME config precedence contract Lane P1 implements in
# services/cli/shepherd_cli/commands/config.py:
#
#   1. <namespace>/shepherd.local.toml   <- NEW  (<namespace> = resolve_namespace)
#   2. <namespace>/shepherd.toml         <- NEW canonical
#   3. <repo>/.claude/shepherd.local.toml       (existing, unchanged)
#   4. <repo>/.claude/shepherd.toml             (existing, unchanged)
#   5. $XDG_CONFIG_HOME/shepherd.toml           (existing, unchanged)
#
# Covers: shctx_config_files' precedence order across all 5 tiers with real
# temp files; .shepherd beating .claude; a .claude-only project behaving
# exactly as before (backward compat); is_shepherd_project true for either
# binding; cfg_get and cfg_section_get agreeing on which file won; and an
# .artifacts/ namespace project resolving tiers 1-2 correctly (resolve_namespace,
# not a hardcoded ".shepherd", is what shctx_config_files walks through).
#
# Self-contained: no sqlite3, no jq required (cfg_get/cfg_section_get fall
# back to grep/awk directly — they never touch json_field). Conventions mirror
# hooks/tests/test_resolve_namespace.sh.
set -eu -o pipefail
cd "$(dirname "$0")"
LIB="$(cd ../scripts && pwd)/_lib.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
assert_eq() { total=$((total+1)); if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1" "expected '$3', got '$2'"; fi; }

tmp=$(mktemp -d -t shep-cfg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
ROOT="$(git rev-parse --show-toplevel)"

# Isolate tier 5 (XDG global) from whatever the test machine's real
# $HOME/.config/shepherd.toml might contain — set for the WHOLE script, never
# unset, so no assertion below can accidentally read a real user config.
XDG_HOME="$tmp/xdg-home"
mkdir -p "$XDG_HOME"
export XDG_CONFIG_HOME="$XDG_HOME"

# Same isolation for the v6.4.2 USER tier (~/.shepherd) -- otherwise the test
# machine's real user config joins the chain and the expected-list assertions
# below depend on whoever ran them.
USER_HOME="$tmp/user-home"
mkdir -p "$USER_HOME"
export SHEPHERD_HOME="$USER_HOME"

# Deterministic base chain: no harness detected, so the two harness tiers are
# absent (7 entries). The layering block at the bottom sets SHEPHERD_HARNESS
# explicitly per-invocation to exercise them.
unset CLAUDE_PLUGIN_ROOT CLAUDECODE CODEX_HOME SHEPHERD_HARNESS 2>/dev/null || true

config_files() { ( source "$LIB"; shctx_config_files ); }
get_key() { ( source "$LIB"; cfg_get "$1" ); }
get_section_key() { ( source "$LIB"; cfg_section_get "$1" "$2" ); }
check_is_shepherd_project() { ( source "$LIB"; is_shepherd_project ); }
reset_all() { rm -rf "$ROOT/.shepherd" "$ROOT/.artifacts" "$ROOT/.claude"; }

# ---------------------------------------------------------------------------
# 1. shctx_config_files echoes all 5 tiers, in order, namespace-resolved.
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.shepherd"
expected="$ROOT/.shepherd/shepherd.local.toml
$ROOT/.shepherd/shepherd.toml
$ROOT/.claude/shepherd.local.toml
$ROOT/.claude/shepherd.toml
$USER_HOME/shepherd.local.toml
$USER_HOME/shepherd.toml
$XDG_CONFIG_HOME/shepherd.toml"
assert_eq "config-files-full-chain-in-order" "$(config_files)" "$expected"

# ---------------------------------------------------------------------------
# 2. Precedence order across all 5 tiers with real temp files: lowest tier
#    populated first, then each higher tier added in turn must immediately
#    win — proves cfg_get walks the SAME order shctx_config_files echoes.
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.shepherd" "$ROOT/.claude"
rm -f "$XDG_CONFIG_HOME/shepherd.toml"

printf 'greeting = "tier5-xdg"\n' > "$XDG_CONFIG_HOME/shepherd.toml"
assert_eq "tier5-xdg-wins-when-alone" "$(get_key greeting)" "tier5-xdg"

printf 'greeting = "tier4-claude-project"\n' > "$ROOT/.claude/shepherd.toml"
assert_eq "tier4-beats-tier5" "$(get_key greeting)" "tier4-claude-project"

printf 'greeting = "tier3-claude-local"\n' > "$ROOT/.claude/shepherd.local.toml"
assert_eq "tier3-beats-tier4" "$(get_key greeting)" "tier3-claude-local"

printf 'greeting = "tier2-namespace"\n' > "$ROOT/.shepherd/shepherd.toml"
assert_eq "tier2-beats-tier3" "$(get_key greeting)" "tier2-namespace"

printf 'greeting = "tier1-namespace-local"\n' > "$ROOT/.shepherd/shepherd.local.toml"
assert_eq "tier1-beats-tier2" "$(get_key greeting)" "tier1-namespace-local"

rm -f "$XDG_CONFIG_HOME/shepherd.toml"

# ---------------------------------------------------------------------------
# 3. .shepherd beats .claude head-to-head (no local-override files involved).
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.shepherd" "$ROOT/.claude"
printf 'greeting = "from-shepherd-toml"\n' > "$ROOT/.shepherd/shepherd.toml"
printf 'greeting = "from-claude-toml"\n' > "$ROOT/.claude/shepherd.toml"
assert_eq "shepherd-beats-claude" "$(get_key greeting)" "from-shepherd-toml"

# ---------------------------------------------------------------------------
# 4. Backward compat: a project with ONLY .claude/shepherd.toml behaves
#    exactly as before v6.4.2 — no .shepherd/ dir exists at all.
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.claude"
printf 'greeting = "legacy-only"\n' > "$ROOT/.claude/shepherd.toml"
assert_eq "claude-only-backward-compat" "$(get_key greeting)" "legacy-only"

# ---------------------------------------------------------------------------
# 5. is_shepherd_project true for EITHER binding.
# ---------------------------------------------------------------------------
reset_all
total=$((total+1))
if check_is_shepherd_project; then fail "is-shepherd-neither-present" "expected false, got true"; else pass "is-shepherd-neither-present"; fi

reset_all
mkdir -p "$ROOT/.claude"; touch "$ROOT/.claude/shepherd.toml"
total=$((total+1))
if check_is_shepherd_project; then pass "is-shepherd-claude-only"; else fail "is-shepherd-claude-only" "expected true, got false"; fi

reset_all
mkdir -p "$ROOT/.shepherd"; touch "$ROOT/.shepherd/shepherd.toml"
total=$((total+1))
if check_is_shepherd_project; then pass "is-shepherd-namespace-only"; else fail "is-shepherd-namespace-only" "expected true, got false"; fi

# ---------------------------------------------------------------------------
# 6. cfg_get and cfg_section_get agree on which file won.
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.shepherd" "$ROOT/.claude"
printf '[hooks]\nquiet_warnings = false\n' > "$ROOT/.claude/shepherd.toml"
printf '[hooks]\nquiet_warnings = true\n' > "$ROOT/.shepherd/shepherd.toml"
assert_eq "cfg-get-scalar-agrees" "$(get_key quiet_warnings)" "true"
assert_eq "cfg-section-get-agrees" "$(get_section_key hooks quiet_warnings)" "true"

# ---------------------------------------------------------------------------
# 7. Legacy .artifacts/ namespace project resolves tiers 1-2 correctly — NOT
#    a hardcoded ".shepherd". resolve_namespace picks the existing .artifacts/
#    dir (no .shepherd/ present), so shctx_config_files' tiers 1-2 must land
#    there.
# ---------------------------------------------------------------------------
reset_all
mkdir -p "$ROOT/.artifacts"
expected_artifacts="$ROOT/.artifacts/shepherd.local.toml
$ROOT/.artifacts/shepherd.toml
$ROOT/.claude/shepherd.local.toml
$ROOT/.claude/shepherd.toml
$USER_HOME/shepherd.local.toml
$USER_HOME/shepherd.toml
$XDG_CONFIG_HOME/shepherd.toml"
assert_eq "artifacts-namespace-tiers-1-2" "$(config_files)" "$expected_artifacts"

printf 'greeting = "artifacts-tier2"\n' > "$ROOT/.artifacts/shepherd.toml"
assert_eq "artifacts-tier2-resolves" "$(get_key greeting)" "artifacts-tier2"

printf 'greeting = "artifacts-tier1-local"\n' > "$ROOT/.artifacts/shepherd.local.toml"
assert_eq "artifacts-tier1-beats-tier2" "$(get_key greeting)" "artifacts-tier1-local"

total=$((total+1))
if check_is_shepherd_project; then pass "is-shepherd-artifacts-namespace"; else fail "is-shepherd-artifacts-namespace" "expected true, got false"; fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"

# ---- v6.4.2 layering: harness + user tiers (operator directive) -------------
# project(local > harness > base) > legacy(.claude) > user(local > harness > base) > xdg
lay="$(mktemp -d)"; ( cd "$lay" && git init -q . && mkdir -p .shepherd )
export SHEPHERD_HOME="$lay/userhome"; mkdir -p "$SHEPHERD_HOME"

t_get() { ( cd "$lay" && SHEPHERD_HARNESS="${2:-claude}" bash -c "source $LIB; cfg_get max_parallel" ); }
w() { printf '[spawn]\nmax_parallel = %s\n' "$2" > "$1"; }

w "$SHEPHERD_HOME/shepherd.toml" 1
assert_eq "layer-user-base"       "$(t_get)" "1"
w "$SHEPHERD_HOME/shepherd.claude.toml" 2
assert_eq "layer-user-harness"    "$(t_get)" "2"
w "$SHEPHERD_HOME/shepherd.local.toml" 3
assert_eq "layer-user-local"      "$(t_get)" "3"
w "$lay/.shepherd/shepherd.toml" 4
assert_eq "layer-project-base"    "$(t_get)" "4"
w "$lay/.shepherd/shepherd.claude.toml" 5
assert_eq "layer-project-harness" "$(t_get)" "5"
w "$lay/.shepherd/shepherd.local.toml" 6
assert_eq "layer-project-local"   "$(t_get)" "6"

# only the ACTIVE harness file is read -- a codex knob must not apply under claude
lay2="$(mktemp -d)"; ( cd "$lay2" && git init -q . && mkdir -p .shepherd )
w "$lay2/.shepherd/shepherd.toml" 30
w "$lay2/.shepherd/shepherd.codex.toml" 31
assert_eq "harness-isolation-claude" \
  "$( cd "$lay2" && SHEPHERD_HARNESS=claude bash -c "source $LIB; cfg_get max_parallel" )" "30"
assert_eq "harness-isolation-codex" \
  "$( cd "$lay2" && SHEPHERD_HARNESS=codex  bash -c "source $LIB; cfg_get max_parallel" )" "31"

# a legacy .claude PROJECT binding outranks the whole USER layer
lay3="$(mktemp -d)"; ( cd "$lay3" && git init -q . && mkdir -p .claude )
export SHEPHERD_HOME="$lay3/uh"; mkdir -p "$SHEPHERD_HOME"
w "$SHEPHERD_HOME/shepherd.local.toml" 21
w "$lay3/.claude/shepherd.toml" 22
assert_eq "legacy-project-beats-user" \
  "$( cd "$lay3" && SHEPHERD_HARNESS=claude bash -c "source $LIB; cfg_get max_parallel" )" "22"
unset SHEPHERD_HOME
rm -rf "$lay" "$lay2" "$lay3"
