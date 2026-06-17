#!/usr/bin/env bash
# hooks/tests/test_shctx_locator.sh — session_open shctx-CLI locator (v6.1.8).
# Kills the "shctx absent" false negative: even with $CLAUDE_PLUGIN_ROOT unset,
# SessionStart must surface the absolute shctx path resolved from the hook's own
# location, and say so is NOT on PATH. Config off-switch must suppress it.
set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/session_open.sh"
EXPECT_PATH="$ROOT/skills/context/scripts/shctx"

tmp=$(mktemp -d -t shep-locator.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
: > .claude/shepherd.toml

fails=0
payload='{"session_id":"s1","hook_event_name":"SessionStart","source":"startup"}'

# 1. CLAUDE_PLUGIN_ROOT UNSET → must still surface the correct absolute path.
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if grep -qF "$EXPECT_PATH" <<<"$out"; then echo "  PASS  surfaces-abs-path-when-CLAUDE_PLUGIN_ROOT-unset"; else
  echo "  FAIL  expected '$EXPECT_PATH' in: $out"; fails=$((fails+1)); fi
if grep -qF "absent BY DESIGN" <<<"$out"; then echo "  PASS  carries-not-on-PATH-note"; else
  echo "  FAIL  missing 'absent BY DESIGN' note: $out"; fails=$((fails+1)); fi
if grep -qF "UNSET" <<<"$out"; then echo "  PASS  reports-CLAUDE_PLUGIN_ROOT-unset"; else
  echo "  FAIL  expected UNSET marker: $out"; fails=$((fails+1)); fi

# 2. [context].announce_shctx_path = off → suppressed (silent on a clean repo).
printf '[context]\nannounce_shctx_path = "off"\n' > .claude/shepherd.toml
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if [[ -z "$out" ]]; then echo "  PASS  off-switch-suppresses-locator"; else
  echo "  FAIL  expected silence with off-switch, got: $out"; fails=$((fails+1)); fi

exit "$fails"
