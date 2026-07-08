#!/usr/bin/env bash
# skills/context/tests/test_cmd_teammate_conductor_only.sh
#
# TEAMMATE-ROLE gate (v6.2.7 #180; widened v6.3.0 #183) — cmd_teammate.sh
# `register` accepts conductor + the self-contained engineer, and refuses every
# other flock role. Field incident (#180): @critic was spawned as a native
# teammate twice despite the prose contract, because dispatch_guard.sh's
# PreToolUse(Agent|Task) hook cannot see a native teammate-spawn (it isn't a
# tool call). This registration call is the one deterministic choke point every
# teammate passes through. #183: refusing @engineer left the self-contained
# engineer unregistered (empty liveness, unflippable TeammateIdle), so it is now
# accepted. This test pins the gate + the idempotent-upsert behavior.

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
grep -q "TEAMMATE-ROLE-INVALID" /tmp/cwg_teammate_critic.err || { echo "FAIL: critic refusal missing TEAMMATE-ROLE-INVALID code"; fails=$((fails+1)); }
n=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates WHERE teammate_name='critic-oops';")
[[ "$n" == "0" ]] || { echo "FAIL: critic-oops row was inserted despite refusal"; fails=$((fails+1)); }

# 5. --type=engineer → ACCEPTED (self-contained engineer is a native teammate, #183).
eng_id=$($CMD register engineer-ok --team=team-a --type=engineer) || { echo "FAIL: engineer register rejected (#183 — self-contained engineer must register)"; fails=$((fails+1)); }
[[ -n "${eng_id:-}" ]] || { echo "FAIL: engineer register returned empty id"; fails=$((fails+1)); }

# 6. --type=coder → refused (subagent only).
if $CMD register coder-oops --team=team-a --type=coder 2>/dev/null; then
  echo "FAIL: coder register was NOT refused"; fails=$((fails+1))
fi

# 7. Idempotent upsert (#183): re-registering the same (team,name) returns the
#    SAME row id, does not error, and does not create a duplicate row.
id_first=$($CMD register conductor-idem --team=team-a --type=conductor) || { echo "FAIL: idempotent first register failed"; fails=$((fails+1)); }
id_again=$($CMD register conductor-idem --team=team-a --type=conductor --session=sess-xyz) || { echo "FAIL: idempotent re-register errored (UNIQUE violation?)"; fails=$((fails+1)); }
[[ "$id_first" == "$id_again" ]] || { echo "FAIL: re-register changed the row id ($id_first != $id_again)"; fails=$((fails+1)); }
dupes=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates WHERE team_name='team-a' AND teammate_name='conductor-idem';")
[[ "$dupes" == "1" ]] || { echo "FAIL: re-register created a duplicate row (count=$dupes)"; fails=$((fails+1)); }
sess=$(sqlite3 "$SHCTX_DB" "SELECT session_id FROM teammates WHERE teammate_name='conductor-idem';")
[[ "$sess" == "sess-xyz" ]] || { echo "FAIL: re-register did not update session_id (got '$sess')"; fails=$((fails+1)); }

# 8. Crashed/retired revival (#183): re-registering a crashed name flips status
#    back to 'booting' (so a respawned teammate is live again) without churning
#    the row id.
id_rev=$($CMD register conductor-rev --team=team-a --type=conductor) || { echo "FAIL: revival setup register failed"; fails=$((fails+1)); }
sqlite3 "$SHCTX_DB" "UPDATE teammates SET status='crashed' WHERE teammate_name='conductor-rev';"
id_rev2=$($CMD register conductor-rev --team=team-a --type=conductor) || { echo "FAIL: re-register of crashed teammate errored"; fails=$((fails+1)); }
[[ "$id_rev" == "$id_rev2" ]] || { echo "FAIL: revival changed the row id ($id_rev != $id_rev2)"; fails=$((fails+1)); }
rev_status=$(sqlite3 "$SHCTX_DB" "SELECT status FROM teammates WHERE teammate_name='conductor-rev';")
[[ "$rev_status" == "booting" ]] || { echo "FAIL: crashed teammate not revived to booting (got '$rev_status')"; fails=$((fails+1)); }

rm -f /tmp/cwg_teammate_critic.err

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL: test_cmd_teammate_conductor_only ($fails failure(s))"
  exit 1
fi
echo "PASS: test_cmd_teammate_conductor_only"
