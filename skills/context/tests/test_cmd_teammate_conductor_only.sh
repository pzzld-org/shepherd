#!/usr/bin/env bash
# skills/context/tests/test_cmd_teammate_conductor_only.sh
#
# CONDUCTOR-ONLY-TEAMMATE gate (v6.2.7, #180) — cmd_teammate.sh `register` must
# refuse any --type other than conductor/shepherd:conductor. Field incident:
# @critic was spawned as a native teammate twice despite the prose contract,
# because dispatch_guard.sh's PreToolUse(Agent|Task) hook cannot see a native
# teammate-spawn at all (it isn't a tool call). This registration call is the
# one deterministic choke point every teammate passes through — this test pins
# the mechanical refusal.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDIR_T="$(mktemp -d -t shepherd-test-conductor-only.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/shepherd.db"

sqlite3 "$SHCTX_DB" < "$ROOT/skills/context/schema/0001_init.sql"
for f in "$ROOT/skills/context/schema/migrations/"*.sql; do
  sqlite3 "$SHCTX_DB" < "$f" 2>/dev/null || true
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('test-proj', 'test', $(date +%s)000, $(date +%s)000);"

CMD="bash $ROOT/skills/context/scripts/cmd_teammate.sh"
fails=0

# 1. --type=conductor → succeeds, returns an id.
id=$($CMD register conductor-ok --team=team-a --type=conductor) || { echo "FAIL: conductor register rejected"; fails=$((fails+1)); }
[[ -n "${id:-}" ]] || { echo "FAIL: conductor register returned empty id"; fails=$((fails+1)); }

# 2. --type=shepherd:conductor (fully-qualified form) → succeeds.
id2=$($CMD register conductor-ok2 --team=team-a --type=shepherd:conductor) || { echo "FAIL: shepherd:conductor register rejected"; fails=$((fails+1)); }
[[ -n "${id2:-}" ]] || { echo "FAIL: shepherd:conductor register returned empty id"; fails=$((fails+1)); }

# 3. --type=Conductor (case variance) → succeeds.
id3=$($CMD register conductor-ok3 --team=team-a --type=Conductor) || { echo "FAIL: Conductor (mixed case) register rejected"; fails=$((fails+1)); }
[[ -n "${id3:-}" ]] || { echo "FAIL: Conductor register returned empty id"; fails=$((fails+1)); }

# 4. --type=critic → refused, non-zero exit, no row inserted.
if $CMD register critic-oops --team=team-a --type=critic 2>/tmp/cwg_teammate_critic.err; then
  echo "FAIL: critic register was NOT refused"; fails=$((fails+1))
fi
grep -q "CONDUCTOR-ONLY-TEAMMATE" /tmp/cwg_teammate_critic.err || { echo "FAIL: critic refusal missing CONDUCTOR-ONLY-TEAMMATE code"; fails=$((fails+1)); }
n=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates WHERE teammate_name='critic-oops';")
[[ "$n" == "0" ]] || { echo "FAIL: critic-oops row was inserted despite refusal"; fails=$((fails+1)); }

# 5. --type=engineer → refused (classic-mode engineer is a subagent, not a teammate).
if $CMD register engineer-oops --team=team-a --type=engineer 2>/dev/null; then
  echo "FAIL: engineer register was NOT refused"; fails=$((fails+1))
fi

# 6. --type=coder → refused.
if $CMD register coder-oops --team=team-a --type=coder 2>/dev/null; then
  echo "FAIL: coder register was NOT refused"; fails=$((fails+1))
fi

rm -f /tmp/cwg_teammate_critic.err

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL: test_cmd_teammate_conductor_only ($fails failure(s))"
  exit 1
fi
echo "PASS: test_cmd_teammate_conductor_only"
