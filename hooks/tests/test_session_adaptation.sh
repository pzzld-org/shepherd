#!/usr/bin/env bash
# hooks/tests/test_session_adaptation.sh — session_open adaptation surface (v6.2.0).
# Inverts the pre-v6.2.0 behavior that spoke ONLY when the registry was empty:
# a NON-empty registry must now surface the sprint/prior counts + newest lesson at
# session start, and the [context].announce_adaptation off-switch must suppress it.
set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/session_open.sh"
SHCTX="$ROOT/skills/context/scripts/shctx"

command -v sqlite3 >/dev/null 2>&1 || { echo "  SKIP  sqlite3 unavailable"; exit 0; }

tmp=$(mktemp -d -t shep-adapt.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
: > .claude/shepherd.toml

fails=0
payload='{"session_id":"s1","hook_event_name":"SessionStart","source":"startup"}'

# Empty registry first: the cold-start note fires (not the populated surface).
"$SHCTX" init >/dev/null 2>&1
"$SHCTX" migrate >/dev/null 2>&1
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if grep -qF "adaptation: empty" <<<"$out"; then echo "  PASS  empty-registry-cold-start-note"; else
  echo "  FAIL  expected 'adaptation: empty' on cold start: $out"; fails=$((fails+1)); fi

# Seed a non-empty registry: one sprint + one reflection prior.
"$SHCTX" adapt roll --sprint=v620-dev1 --grade=B --lanes=3 >/dev/null 2>&1
"$SHCTX" adapt reflect --sprint=v620-dev1 --note="lanes oversized for a docs sprint" >/dev/null 2>&1

# 1. Non-empty registry → sprint count + latest lesson surface.
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if grep -qF "adaptation: 1 sprint" <<<"$out"; then echo "  PASS  surfaces-sprint-count"; else
  echo "  FAIL  expected 'adaptation: 1 sprint' in: $out"; fails=$((fails+1)); fi
if grep -qF "latest lesson:" <<<"$out"; then echo "  PASS  surfaces-latest-lesson"; else
  echo "  FAIL  expected 'latest lesson:' in: $out"; fails=$((fails+1)); fi

# 1b. With >=3 worsening sprints (recurring HIGH concern + grade down + cost up),
#     the surface carries the TREND ALERT line (the n>=3 trend-probe branch).
for s in sa sb sc; do
  echo "duplicated helper across two lanes" | "$SHCTX" audit insert \
    --concern=duplication --severity=high --hypothesis="recurs" --sprint=$s >/dev/null 2>&1
done
"$SHCTX" adapt roll --sprint=sa --grade=A --wall-min=60  --api=100 >/dev/null 2>&1
"$SHCTX" adapt roll --sprint=sb --grade=B --wall-min=90  --api=150 >/dev/null 2>&1
"$SHCTX" adapt roll --sprint=sc --grade=C --wall-min=140 --api=260 >/dev/null 2>&1
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if grep -qF "TREND ALERT active" <<<"$out"; then echo "  PASS  surfaces-trend-alert"; else
  echo "  FAIL  expected 'TREND ALERT active' in: $out"; fails=$((fails+1)); fi

# 2. [context].announce_adaptation = off → adaptation line suppressed.
printf '[context]\nannounce_adaptation = "off"\n' > .claude/shepherd.toml
out=$(env -u CLAUDE_PLUGIN_ROOT bash "$HOOK" <<<"$payload" 2>/dev/null || true)
if ! grep -qF "adaptation:" <<<"$out"; then echo "  PASS  off-switch-suppresses-adaptation"; else
  echo "  FAIL  expected no adaptation line with off-switch: $out"; fails=$((fails+1)); fi

exit "$fails"
