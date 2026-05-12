#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null

# Seed an artifact + a symbol so search has substrate.
mkdir -p .shepherd/docs
cat > .shepherd/docs/2026-05-05-search-probe.spec.md <<'EOF'
# Search probe — BookSnapshot

Project state for the BookSnapshot type used by the QuestDB writer.
EOF
"$SHCTX" refresh --scope=artifacts >/dev/null

db=".shepherd/root.db"
project_id=$(jq -r '.id' .shepherd/project.json)
now=$(date +%s)
sqlite3 "$db" <<SQL
INSERT INTO index_symbols
  (id, project_id, name, kind, package, file_path, line, visibility, signature, doc_summary, language, hash, refreshed_at)
VALUES
  ('test-uid-1','$project_id','BookSnapshot','struct','probe','probe/src/lib.rs',12,'pub',
   'pub struct BookSnapshot','OHLCV book snapshot row','rust','sha-1',$now);
SQL

# Search by symbol name.
out=$("$SHCTX" search "BookSnapshot" --scope=symbols --limit=5)
echo "$out" | grep -q "BookSnapshot" || { echo "FAIL: BookSnapshot not in --scope=symbols result" >&2; echo "$out"; exit 1; }

# Search by artifact content.
out=$("$SHCTX" search "BookSnapshot" --scope=artifacts --limit=5)
echo "$out" | grep -q "search-probe.spec.md" || { echo "FAIL: artifact not in --scope=artifacts result" >&2; echo "$out"; exit 1; }

# JSON mode should be valid JSON.
out=$("$SHCTX" search "BookSnapshot" --scope=symbols --json)
echo "$out" | jq . >/dev/null || { echo "FAIL: --json output is not valid JSON" >&2; echo "$out"; exit 1; }

echo "PASS: test_search.sh"
