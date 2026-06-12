#!/usr/bin/env bash
# hooks/tests/test_toolkit_surface.sh — tests for toolkit_surface.sh (v6.1.3).
#
# Covers the SessionStart toolkit-roster hook:
#   1. No shepherd.toml → exit 0, no output (not a shepherd project).
#   2. Empty / absent toolkit.json → graceful-empty (no output).
#   3. Local + global merge → global-only tool surfaces; local wins on collision.
#   4. Pinned entries surface first (ahead of alphabetically-earlier unpinned).
#   5. >12 merged tools → roster capped at 12 entries (matches the doctrine + md).

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/toolkit_surface.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }

if ! command -v jq >/dev/null 2>&1; then
  echo "  SKIP  jq unavailable — toolkit_surface requires jq"
  echo "—— 0/0 passed (skipped) ——"; exit 0
fi

run_hook()  { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; return 0; }
roster()    { printf '%s' "$1" | jq -r '.additionalContext // ""' 2>/dev/null || true; }
PAYLOAD='{"session_id":"sess-tk","source":"startup","hook_event_name":"SessionStart"}'

# 1. No shepherd.toml → silent.
total=$((total+1))
bare=$(mktemp -d -t shep-tks-bare.XXXXXX)
(
  cd "$bare"; git init -q .; git config user.email t@t; git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(run_hook "$PAYLOAD")
  [[ -z "$out" ]] && printf '  PASS  no-shepherd-toml: silent\n' \
                  || { printf '  FAIL  no-shepherd-toml: got %s\n' "${out:0:60}"; exit 1; }
) || fails=$((fails+1))
rm -rf "$bare"

# Shared shepherd-flagged repo with an isolated XDG (global) tier under tmp.
tmp=$(mktemp -d -t shep-tks.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"; git init -q .; git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .artifacts; touch .claude/shepherd.toml
export XDG_CONFIG_HOME="$tmp/xdg"; mkdir -p "$XDG_CONFIG_HOME/shepherd"
LOCAL=".artifacts/toolkit.json"
GLOBAL="$XDG_CONFIG_HOME/shepherd/toolkit.json"
write_tk() { printf '{"version":1,"scope":"local","updated_at":1,"tools":%s}\n' "$2" > "$1"; }

# 2. Empty toolkit → graceful-empty.
total=$((total+1))
write_tk "$LOCAL" '[]'
out=$(run_hook "$PAYLOAD")
[[ -z "$out" ]] && pass "empty-toolkit: silent" || fail "empty-toolkit: silent" "got ${out:0:80}"

# 3. Local ∪ global merge; local wins on name collision.
total=$((total+1))
write_tk "$GLOBAL" '[{"name":"ctx7","scope":"global","type":"mcp","capabilities":["docs"],"description":"GLOBAL-ctx7"},{"name":"laptop","scope":"global","type":"cli","capabilities":["ssh"],"description":"ssh dev box"}]'
write_tk "$LOCAL"  '[{"name":"ctx7","scope":"local","type":"mcp","capabilities":["docs"],"description":"LOCAL-ctx7"}]'
r=$(roster "$(run_hook "$PAYLOAD")")
if grep -q "laptop" <<<"$r" && grep -q "LOCAL-ctx7" <<<"$r" && ! grep -q "GLOBAL-ctx7" <<<"$r"; then
  pass "merge: local wins on collision; global-only tool surfaces"
else
  fail "merge" "roster=$(printf '%s' "$r" | tr '\n' '|')"
fi

# 4. Pinned first (zzz pinned must precede alphabetically-earlier aaa).
total=$((total+1))
write_tk "$GLOBAL" '[]'
write_tk "$LOCAL" '[{"name":"aaa","scope":"local","type":"cli","capabilities":["x"],"description":"unpinned-a"},{"name":"zzz","scope":"local","type":"cli","capabilities":["x"],"description":"pinned-z","pinned":true}]'
r=$(roster "$(run_hook "$PAYLOAD")")
zl=$(grep -n 'zzz' <<<"$r" | head -1 | cut -d: -f1)
al=$(grep -n 'aaa' <<<"$r" | head -1 | cut -d: -f1)
if [[ -n "$zl" && -n "$al" && "$zl" -lt "$al" ]]; then
  pass "pinned-first: zzz(pinned) before aaa(unpinned)"
else
  fail "pinned-first" "zzz@$zl aaa@$al"
fi

# 5. >12 merged tools → capped at 12.
total=$((total+1))
tools='['
for i in $(seq 1 20); do
  sep=','; [[ "$i" -eq 1 ]] && sep=''
  tools="${tools}${sep}{\"name\":\"tool$(printf '%02d' "$i")\",\"scope\":\"local\",\"type\":\"cli\",\"capabilities\":[\"x\"],\"description\":\"d$i\"}"
done
tools="${tools}]"
write_tk "$LOCAL" "$tools"
write_tk "$GLOBAL" '[]'
r=$(roster "$(run_hook "$PAYLOAD")")
nbul=$(grep -c '•' <<<"$r" || true)
if [[ "$nbul" -eq 12 ]]; then
  pass "cap-12: exactly 12 of 20 tools surfaced"
else
  fail "cap-12" "bullets=$nbul (expected 12)"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
