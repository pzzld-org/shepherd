#!/usr/bin/env bash
# hooks/tests/test_team_preflight.sh — GH #267 spawn Check 3.
#
# Check 3's INTENT is "no OTHER lead's team is running". Its predicate was
# "`ls ~/.claude/teams/` non-empty with a config.json carrying members[]" — a
# different question, which the NORMAL case fails: the harness initializes a
# team file for the current session at startup holding a single `team-lead`
# member, so Check 3 refused on a perfectly clean session.
#
# The cost came from the follow-on. The team directory id has no string
# relationship to the session id (`37a86c89-…` -> `session-376146fb`), so an
# operator cannot recognize their own team, and a lead-only directory is
# indistinguishable by inspection from an abandoned husk. Running the documented
# remedy then deletes it, and every later spawn dies with
# `team file for "session-XXXX" not found` — five conductor spawns at once, in
# the report.
#
# Deterministic, no network, no LLM. <2s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/team-preflight.sh"

total=0; fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
TEAMS="$tmp/teams"

# Write a team roster. Args after the dir name are member "name:agentType" pairs.
mk_team() {
  local dir="$1"; shift
  mkdir -p "$TEAMS/$dir"
  local members="" m name atype
  for m in "$@"; do
    name="${m%%:*}"; atype="${m#*:}"
    [[ -n "$members" ]] && members+=","
    members+="{\"name\":\"$name\",\"agentType\":\"$atype\",\"backendType\":\"in-process\"}"
  done
  printf '{"members":[%s]}\n' "$members" > "$TEAMS/$dir/config.json"
}

# `|| true` is load-bearing: a blocked result exits 1, and under `set -e` an
# assignment from command substitution propagates that and kills the run.
run_pf() { bash "$SCRIPT" --teams-dir="$TEAMS" "$@" 2>&1 || true; }
rc_pf()  { local rc=0; bash "$SCRIPT" --teams-dir="$TEAMS" >/dev/null 2>&1 || rc=$?; echo "$rc"; }

# ---------------------------------------------------------------------------
# 1. The #267 false positive: the session's OWN freshly-initialized team.
# ---------------------------------------------------------------------------
total=$((total+1))
mk_team "session-376146fb" "team-lead:team-lead"
if [[ "$(rc_pf)" == "0" ]]; then
  pass "lead-only roster: CLEAR (the #267 false positive is gone)"
else
  fail "lead-only clear" "$(run_pf)"
fi

# ---------------------------------------------------------------------------
# 2. A genuinely active team still refuses — the gate's real purpose.
# ---------------------------------------------------------------------------
total=$((total+1))
mk_team "session-other" "team-lead:team-lead" "l2-moneypath:conductor"
if [[ "$(rc_pf)" == "1" ]]; then
  pass "team with a non-lead member: REFUSE (one team per lead still holds)"
else
  fail "active team refused" "$(run_pf)"
fi

total=$((total+1))
out="$(run_pf)"
if printf '%s' "$out" | grep -q 'session-other' && ! printf '%s' "$out" | grep -q 'session-376146fb'; then
  pass "refusal names the OFFENDING team, not the session's own"
else
  fail "refusal names offender" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# 3. No teams directory at all is the cleanest state, not an error.
# ---------------------------------------------------------------------------
total=$((total+1))
rm -rf "$TEAMS"
if [[ "$(rc_pf)" == "0" ]]; then
  pass "absent teams dir: CLEAR (not an error)"
else
  fail "absent teams dir clear" "$(run_pf)"
fi

# ---------------------------------------------------------------------------
# 4. An empty roster, and a config with no members key at all, are both clear.
# ---------------------------------------------------------------------------
total=$((total+1))
mk_team "session-empty"
mkdir -p "$TEAMS/session-nomembers"
printf '{}\n' > "$TEAMS/session-nomembers/config.json"
if [[ "$(rc_pf)" == "0" ]]; then
  pass "empty roster + members-less config: CLEAR"
else
  fail "empty rosters clear" "$(run_pf)"
fi

# ---------------------------------------------------------------------------
# 5. Malformed JSON must not crash or block — a broken husk is not evidence
#    that a team is running, and blocking on it would strand the operator.
# ---------------------------------------------------------------------------
total=$((total+1))
mkdir -p "$TEAMS/session-corrupt"
printf 'not json at all{{{\n' > "$TEAMS/session-corrupt/config.json"
if [[ "$(rc_pf)" == "0" ]]; then
  pass "malformed config.json: CLEAR (degrades safe, never crashes)"
else
  fail "malformed config clear" "$(run_pf)"
fi

# ---------------------------------------------------------------------------
# 6. A real teammate merely NAMED team-lead is not exempted — the exemption
#    keys on the member looking like a lead on BOTH fields.
# ---------------------------------------------------------------------------
total=$((total+1))
rm -rf "$TEAMS"; mk_team "session-x" "team-lead:conductor"
if [[ "$(rc_pf)" == "1" ]]; then
  pass "member named team-lead but agentType=conductor: REFUSE (not exempted)"
else
  fail "name-only lead not exempted" "$(run_pf)"
fi

# ---------------------------------------------------------------------------
# 7. --json shape, for a caller that parses rather than reads.
# ---------------------------------------------------------------------------
total=$((total+1))
out="$(bash "$SCRIPT" --teams-dir="$TEAMS" --json 2>&1 || true)"
if printf '%s' "$out" | grep -q '"status":"blocked"' && printf '%s' "$out" | grep -q '"active_teams":1'; then
  pass "--json emits status + active_teams"
else
  fail "--json shape" "out=${out:0:200}"
fi

total=$((total+1))
flag_rc=0; bash "$SCRIPT" --bogus-flag >/dev/null 2>&1 || flag_rc=$?
if [[ "$flag_rc" == "2" ]]; then
  pass "unknown flag is a usage error (exit 2), not a silent default"
else
  fail "unknown flag exits 2" "rc=$flag_rc"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
