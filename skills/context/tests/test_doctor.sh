#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# Doctor on uninitialized project: expect FAIL (no project.json).
out=$("$SHCTX" doctor 2>&1 || true)
assert_contains "doctor pre-init flags missing project.json" "$out" "project.json"
assert_contains "doctor pre-init flags missing namespace dir" "$out" "namespace dir"

# After init: doctor should be clean (or warn-only) on the test repo.
"$SHCTX" init >/dev/null
out=$("$SHCTX" doctor 2>&1 || true)
assert_contains "doctor post-init reports project_id"  "$out" "id="
assert_contains "doctor post-init reports root.db"     "$out" "root.db"
assert_contains "doctor post-init reports schema_version" "$out" "schema_version"

# JSON output is valid.
json=$("$SHCTX" doctor --json 2>&1 || true)
echo "$json" | jq -e '.summary, .checks' >/dev/null \
  || { echo "FAIL: doctor --json missing .summary/.checks" >&2; exit 1; }
echo "PASS: doctor"
