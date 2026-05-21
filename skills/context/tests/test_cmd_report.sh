#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-report.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"
sqlite3 "$SHCTX_DB" "INSERT INTO discovery_findings (project_id, sprint_branch, discovery_run, section, title, body, created_at) VALUES ('p','v5.1.7','D-TEST','confirmed','Auth flow works','Detailed body',1);"
sqlite3 "$SHCTX_DB" "INSERT INTO audit_findings (project_id, sprint_branch, concern, severity, hypothesis, finding, created_at) VALUES ('p','v5.1.7','code-quality','high','spawn brief duplicates cargo discipline','duplicate found in 2 files',1);"

CMD="bash $ROOT/skills/context/scripts/cmd_report.sh"

$CMD discovery --run=D-TEST | grep -c "Auth flow works" >/dev/null || { echo "FAIL: discovery report missing finding"; exit 1; }
$CMD audit --sprint=v5.1.7 | grep -c "spawn brief duplicates" >/dev/null || { echo "FAIL: audit report missing finding"; exit 1; }
$CMD audit --sprint=v5.1.7 --severity=high | grep -c "high" >/dev/null || { echo "FAIL: audit report severity filter"; exit 1; }
$CMD teammates >/dev/null || { echo "FAIL: teammates report errored"; exit 1; }

echo "PASS: test_cmd_report"
