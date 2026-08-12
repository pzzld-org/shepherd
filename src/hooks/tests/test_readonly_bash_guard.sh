#!/usr/bin/env bash
# hooks/tests/test_readonly_bash_guard.sh — bash_guard.sh Check 3 read-only-mutate
# gate for @discovery AND @critic (v6.3.8).
#
# @critic gained the Bash grant in v6.3.8 (its Step 0.5 runs shctx); this pins the
# matching mechanical guard so a read-only reviewer cannot mutate source/filesystem
# via shell — while shctx registry writes and read-only inspection still pass. Also
# backfills the previously-untested @discovery leg. Role is resolved via the
# dispatch record (.shepherd/dispatch/<sprint>/<tool_use_id>.json), same path
# bash_guard.sh reads in production.
#
#   critic + rm -rf            → DENY + CRITIC-MUTATE
#   critic + redirect > file   → DENY + CRITIC-MUTATE
#   critic + git commit        → DENY (mutate pattern)
#   critic + shctx audit insert→ PASS (registry write allowed)
#   critic + rg (read-only)    → PASS
#   discovery + rm -rf         → DENY + DISCOVERY-MUTATE (regression)
#   discovery + shctx insert   → PASS

set -uo pipefail
cd "$(dirname "$0")"
SCRIPT="$(cd .. && pwd)/scripts/bash_guard.sh"

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "$2"; }

if ! command -v jq >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — neither jq nor python3 for role resolution\n'; exit 0
fi

tmp=$(mktemp -d -t shep-robg.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
mkdir -p .claude; touch .claude/shepherd.toml
git add .claude/shepherd.toml; git -c commit.gpgsign=false commit -q -m init
sprint=$(git rev-parse --abbrev-ref HEAD)
mkdir -p ".shepherd/dispatch/$sprint"
printf '{"agent_role":"critic"}'    > ".shepherd/dispatch/$sprint/crit1.json"
printf '{"agent_role":"discovery"}' > ".shepherd/dispatch/$sprint/disc1.json"

emit() { # emit <tool_use_id> <command>
  printf '{"session_id":"s","tool_name":"Bash","tool_use_id":"%s","tool_input":{"command":"%s"}}' "$1" "$2" \
    | bash "$SCRIPT" 2>/dev/null || true
}
want_deny() { # want_deny <label> <tid> <cmd> <code>
  local out; out=$(emit "$2" "$3")
  if is_deny "$out" && has_code "$out" "$4"; then pass "$1"
  else fail "$1" "expected deny+$4, got: ${out:0:80}"; fi
}
want_pass() { # want_pass <label> <tid> <cmd>
  local out; out=$(emit "$2" "$3")
  if is_deny "$out"; then fail "$1" "expected pass, got deny: ${out:0:80}"; else pass "$1"; fi
}

want_deny "critic + rm -rf → CRITIC-MUTATE"        crit1 "rm -rf build"            "CRITIC-MUTATE"
want_deny "critic + redirect > file → CRITIC-MUTATE" crit1 "echo x > out.txt"      "CRITIC-MUTATE"
want_deny "critic + git commit → blocked"          crit1 "git commit -m y"         "CRITIC-MUTATE"
want_pass "critic + shctx audit insert → allowed"  crit1 "shctx audit insert --concern=critic"
want_pass "critic + rg (read-only) → allowed"      crit1 "rg TODO src"
want_deny "discovery + rm -rf → DISCOVERY-MUTATE"  disc1 "rm -rf build"            "DISCOVERY-MUTATE"
want_pass "discovery + shctx insert → allowed"     disc1 "shctx discovery insert --run=r1"

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d read-only bash-guard assertion(s) failed\n' "$fails" >&2; exit 1
fi
printf '  PASS  read-only reviewers (@critic/@discovery) blocked from shell mutation; shctx passes\n'
