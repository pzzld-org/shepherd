#!/usr/bin/env bash
# hooks/tests/test_shctx_locator.sh — session_open shctx-CLI locator (v6.1.8).
# Kills the "shctx absent" false negative: even with $CLAUDE_PLUGIN_ROOT unset,
# SessionStart must surface the absolute shctx path resolved from the hook's own
# location, and say so is NOT on PATH. Config off-switch must suppress it.
set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/session_open.sh"
EXPECT_PATH="$ROOT/bin/shepherd"  # v6.5.0: bin/shepherd is the canonical CLI the orientation announces

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

# 2. [context].announce_shctx_path = off → locator line suppressed. (Other v6.2.0
#    surfaces — core-doctrine pointer, adaptation — have their own off-switches,
#    so assert the LOCATOR path is gone, not total silence.)
printf '[context]\nannounce_shctx_path = "off"\n' > .claude/shepherd.toml
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if ! grep -qF "$EXPECT_PATH" <<<"$out"; then echo "  PASS  off-switch-suppresses-locator"; else
  echo "  FAIL  expected no locator path with off-switch, got: $out"; fails=$((fails+1)); fi

# 3. v6.2.0 core-doctrine pointer: on by default, surfaces operating-philosophy.md.
printf '[context]\nannounce_shctx_path = "off"\n' > .claude/shepherd.toml
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if grep -qF "operating-philosophy.md" <<<"$out"; then echo "  PASS  core-doctrine-pointer-default-on"; else
  echo "  FAIL  expected operating-philosophy.md pointer: $out"; fails=$((fails+1)); fi

# 4. All v6.2.0 context surfaces off → true silence on a clean (DB-less) repo.
printf '[context]\nannounce_shctx_path = "off"\nannounce_core_doctrine = "off"\nannounce_adaptation = "off"\n' > .claude/shepherd.toml
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if [[ -z "$out" ]]; then echo "  PASS  all-off-switches-yield-silence"; else
  echo "  FAIL  expected silence with all off, got: $out"; fails=$((fails+1)); fi

exit "$fails"
