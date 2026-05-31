#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-mailbox.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"

for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/migrations/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('test-proj', 'test', 1, 1);"

CMD="bash $ROOT/skills/context/scripts/cmd_mailbox.sh"

# send with valid JSON payload
id=$(echo '{"line":"pub mod volume;"}' | $CMD send --to=obs-init --kind=heartbeat_payload --target-file=crates/config/src/lib.rs --requires-ack)
[[ -n "$id" ]] || { echo "FAIL: send returned no id"; exit 1; }

# recv as recipient finds the message
$CMD recv --as=obs-init --unread-only | grep -c '"recipient_name":"obs-init"' >/dev/null || { echo "FAIL: recv missing message"; exit 1; }

# recv with --mark-read flips read_at
$CMD recv --as=obs-init --mark-read >/dev/null
read_at=$(sqlite3 "$SHCTX_DB" "SELECT read_at FROM mailbox WHERE id=$id;")
[[ -n "$read_at" && "$read_at" != "" ]] || { echo "FAIL: read_at not set"; exit 1; }

# ack flips acked_at
$CMD ack $id
acked=$(sqlite3 "$SHCTX_DB" "SELECT acked_at FROM mailbox WHERE id=$id;")
[[ -n "$acked" && "$acked" != "" ]] || { echo "FAIL: acked_at not set"; exit 1; }

# send refuses invalid JSON
if echo 'not-json' | $CMD send --to=x --kind=generic 2>/dev/null; then
  echo "FAIL: send accepted invalid JSON"; exit 1
fi

echo "PASS: test_cmd_mailbox"
