#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# Mock `gh` with a shim on PATH.
mock_dir="$SHCTX_TEST_TMP/mock"
mkdir -p "$mock_dir"
cat > "$mock_dir/gh" <<'SH'
#!/usr/bin/env bash
case "$* " in
  *"issue list"*)    cat <<EOF
[{"number":1,"title":"first","state":"OPEN","labels":[{"name":"bug"}],"milestone":null,"assignees":[],"body":"b","url":"u","createdAt":"2025-01-01T00:00:00Z","updatedAt":"2025-01-02T00:00:00Z"}]
EOF
;;
  *"pr list"*)       echo '[]' ;;
  *"release list"*)  echo '[]' ;;
  *"api"*"milestones"*) echo '[]' ;;
  *"repo view"*)     echo '{"nameWithOwner":"acme/probe"}' ;;
  *) echo '[]' ;;
esac
SH
chmod +x "$mock_dir/gh"
PATH="$mock_dir:$PATH" "$SHCTX" refresh --scope=github

n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/root.db" "SELECT COUNT(*) FROM index_issues;")
assert_eq "issue_count" "$n" "1"
title=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/root.db" "SELECT title FROM index_issues;")
assert_eq "issue_title" "$title" "first"
