#!/usr/bin/env bash
# hooks/tests/test_seed_preflight_check.sh — PreToolUse(Write) seed gate (v6.2.1).
#
# The deterministic seed pre-flight as a Write guard. Verifies it denies a seed
# Write whose file_scope path is hallucinated (block mode), passes a clean seed
# silently, honors [seed].seed_gate = warn (additionalContext, never deny) and
# = off (silent), and fast-paths non-seed / Edit / non-shepherd writes.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/seed_preflight_check.sh"
export CLAUDE_PLUGIN_ROOT="$ROOT"

tmp=$(mktemp -d -t shep-seed-hook.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q . >/dev/null
git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude src
echo x > src/real.rs
printf '[project]\nname="t"\n' > .claude/shepherd.toml

cat > good.txt <<'EOF'
---
title: t
branch: v6.2.1
kind: sprint-seed
milestone: 1
file_scope:
  exclusive:
    - src/real.rs
---

### D  [CRITICAL]

- **GH:** #1
- **Priority:** CRITICAL
- **Acceptance:** grep -q x
EOF
sed 's#src/real.rs#src/ghost.rs#' good.txt > bad.txt

payload() { # contentfile file_path tool -> JSON
  local cf="$1" fp="$2" tool="${3:-Write}" key="content"
  [[ "$tool" == "Edit" ]] && key="new_string"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg fp "$fp" --arg tool "$tool" --arg key "$key" --rawfile c "$cf" \
      '{tool_name:$tool,session_id:"s",tool_input:({file_path:$fp}+{($key):$c})}'
  else
    python3 -c 'import json,sys
tool,fp,key,cf=sys.argv[1:5]
print(json.dumps({"tool_name":tool,"session_id":"s","tool_input":{"file_path":fp,key:open(cf).read()}}))' "$tool" "$fp" "$key" "$cf"
  fi
}

fails=0
ck() { # name payload want_substr  (empty want => expect no output)
  local name="$1" pl="$2" want="$3" out
  out=$(printf '%s' "$pl" | bash "$HOOK" 2>/dev/null || true)
  if [[ -z "$want" ]]; then
    if [[ -z "$out" ]]; then echo "  PASS  $name"; else echo "  FAIL  $name: expected silence, got: $out"; fails=$((fails+1)); fi
  else
    if grep -qF -- "$want" <<<"$out"; then echo "  PASS  $name"; else echo "  FAIL  $name: want '$want' in: $out"; fails=$((fails+1)); fi
  fi
}

GOOD_PL=$(payload good.txt "$tmp/x.seed.md" Write)
BAD_PL=$(payload bad.txt "$tmp/x.seed.md" Write)

# default (block) mode
ck "clean-seed-passes"   "$GOOD_PL" ""
ck "bad-seed-denies"     "$BAD_PL"  '"permissionDecision":"deny"'
ck "deny-explains-path"  "$BAD_PL"  'does not resolve'

# warn mode → additionalContext, never deny
printf '[project]\nname="t"\n[seed]\nseed_gate = "warn"\n' > .claude/shepherd.toml
ck "warn-mode-context"   "$BAD_PL"  'additionalContext'
out=$(printf '%s' "$BAD_PL" | bash "$HOOK" 2>/dev/null || true)
if grep -qF '"deny"' <<<"$out"; then echo "  FAIL  warn-mode-must-not-deny"; fails=$((fails+1)); else echo "  PASS  warn-mode-no-deny"; fi

# off mode → silent
printf '[project]\nname="t"\n[seed]\nseed_gate = "off"\n' > .claude/shepherd.toml
ck "off-mode-silent"     "$BAD_PL"  ""

# back to default
printf '[project]\nname="t"\n' > .claude/shepherd.toml

# non-seed file path → silent
ck "non-seed-file-silent" "$(payload bad.txt notes.md Write)" ""
# Edit tool (only Write is gated) → silent
ck "edit-tool-silent"     "$(payload bad.txt "$tmp/x.seed.md" Edit)" ""

# non-shepherd repo → silent
rm -f .claude/shepherd.toml
ck "non-shepherd-silent"  "$BAD_PL"  ""
printf '[project]\nname="t"\n' > .claude/shepherd.toml

if [[ "$fails" -eq 0 ]]; then echo "PASS: test_seed_preflight_check"; exit 0; else echo "FAIL: test_seed_preflight_check ($fails)"; exit 1; fi
