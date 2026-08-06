#!/usr/bin/env bash
# scripts/team-preflight.sh — /shepherd:spawn Check 3, in deterministic space.
#
# WHY: #267. Check 3's INTENT is "no OTHER lead's team is running" (one team per
# lead). Its predicate was "`ls ~/.claude/teams/` non-empty with a config.json
# carrying members[]" — a different question, and one the normal case fails.
#
# The harness initializes a team file for the CURRENT session at startup holding
# a single `team-lead` member. That satisfies "non-empty with members[]", so
# Check 3 refused on a perfectly clean session.
#
# The trap that made it expensive: THE TEAM DIRECTORY ID DOES NOT MATCH THE
# SESSION/CONVERSATION ID. A session `37a86c89-…` gets a team dir
# `session-376146fb` — no string relationship, so an operator cannot identify
# their own team by matching an id they already know. A single-`team-lead`
# directory with a recent mtime is, by inspection, indistinguishable from an
# abandoned husk. So the documented remedy (`/shepherd:cleanup`) prunes it, and
# every subsequent spawn dies with `team file for "session-XXXX" not found`,
# unrecoverable without knowing to restore the directory. In the reported
# incident five conductor spawns failed at once.
#
# Answering "is a FOREIGN team active?" is same-input-same-output: it is a read
# of the teams directory, not a judgment. So it belongs here, not in a model's
# head — a lead reasoning about `ls` output re-derives (and re-misjudges) this
# every spawn.
#
# The rule: a team is ACTIVE iff its members[] contains at least one member that
# is not the lead placeholder. A lead-only team is the freshly-initialized state
# every session has, including this one, and blocks nothing.
#
# Usage: team-preflight.sh [--teams-dir=<path>] [--json]
#   --teams-dir=<path>  teams root (default ${CLAUDE_TEAMS_DIR:-~/.claude/teams})
#   --json              machine-readable result
#   -h|--help           print usage, exit 0
#
# Exit: 0 clear to spawn, 1 a foreign active team exists, 2 usage error.
set -euo pipefail

usage() {
  echo "Usage: team-preflight.sh [--teams-dir=<path>] [--json]"
  echo "  --teams-dir=<path>  teams root (default \${CLAUDE_TEAMS_DIR:-~/.claude/teams})"
  echo "  --json              machine-readable result"
  echo "  -h|--help           print usage, exit 0"
}

teams_dir="${CLAUDE_TEAMS_DIR:-$HOME/.claude/teams}"
json=0
for arg in "$@"; do
  case "$arg" in
    --teams-dir=*) teams_dir="${arg#--teams-dir=}" ;;
    --json)        json=1 ;;
    -h|--help)     usage; exit 0 ;;
    *)             echo "team-preflight: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

emit() {  # <status> <count> <message> <names-csv>
  if [[ "$json" == "1" ]]; then
    printf '{"status":"%s","active_teams":%s,"message":"%s","names":"%s"}\n' "$1" "$2" "$3" "$4"
  else
    printf 'team-preflight: %s\n' "$3"
  fi
}

# No teams directory at all is the cleanest possible state, not an error.
if [[ ! -d "$teams_dir" ]]; then
  emit ok 0 "no teams directory at $teams_dir — clear to spawn" ""
  exit 0
fi

# Count members that are NOT the lead placeholder. A team-lead-only roster is
# the harness's startup state; anything beyond it means a real team is running.
#
# A member is exempt (counts as "the lead placeholder") ONLY when BOTH `name`
# and `agentType` say team-lead — hence the OR below, which selects the
# complement. Checking either field alone would exempt a real teammate that
# merely happens to be named "team-lead", turning the fix for a false REFUSE
# into a false CLEAR: spawning a second team over a live one, which is the
# exact condition this gate exists to prevent.
non_lead_members() {  # <config.json> -> count on stdout
  local cfg="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -r '[.members // [] | .[]
            | select(((.name // "") != "team-lead") or ((.agentType // "") != "team-lead"))]
           | length' "$cfg" 2>/dev/null || echo 0
    return
  fi
  python3 - "$cfg" <<'PY' 2>/dev/null || echo 0
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print(0); raise SystemExit
members = doc.get("members") or []
print(sum(
    1 for m in members
    if isinstance(m, dict)
    and (m.get("name") != "team-lead" or m.get("agentType") != "team-lead")
))
PY
}

active_names=()
for cfg in "$teams_dir"/*/config.json; do
  [[ -f "$cfg" ]] || continue
  count="$(non_lead_members "$cfg")"
  [[ "$count" =~ ^[0-9]+$ ]] || count=0
  if [[ "$count" -gt 0 ]]; then
    active_names+=("$(basename "$(dirname "$cfg")")")
  fi
done

if [[ ${#active_names[@]} -eq 0 ]]; then
  emit ok 0 "no active team (lead-only rosters do not count) — clear to spawn" ""
  exit 0
fi

names_csv="$(IFS=,; echo "${active_names[*]}")"
emit blocked "${#active_names[@]}" \
  "${#active_names[@]} active team(s) with non-lead members: ${names_csv} — refuse (one team per lead)" \
  "$names_csv"
exit 1
