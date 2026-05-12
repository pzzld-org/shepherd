#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# ---- Mode 1: default (.shepherd/) ----
"$SHCTX" init

assert_file "$SHCTX_TEST_TMP/.shepherd/root.db"
assert_file "$SHCTX_TEST_TMP/.shepherd/project.json"
assert_file "$SHCTX_TEST_TMP/.shepherd/CONVENTIONS.md"
assert_file "$SHCTX_TEST_TMP/.shepherd/.gitignore"
for d in ctx plans reports docs/handoffs docs/specs docs/diagrams docs/journal logs tmp profiles; do
  [[ -d "$SHCTX_TEST_TMP/.shepherd/$d" ]] || { echo "FAIL: missing dir: .shepherd/$d" >&2; exit 1; }
done
# Default mode MUST NOT create .artifacts/.
[[ ! -d "$SHCTX_TEST_TMP/.artifacts" ]] || { echo "FAIL: .artifacts/ unexpectedly created in default mode" >&2; exit 1; }

# Exactly one project row, with id matching project.json.
pid=$(jq -r '.id' "$SHCTX_TEST_TMP/.shepherd/project.json")
db_pid=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/root.db" "SELECT id FROM projects;")
assert_eq "project_id" "$db_pid" "$pid"

# Idempotent: second init does NOT overwrite project.json.
"$SHCTX" init
pid2=$(jq -r '.id' "$SHCTX_TEST_TMP/.shepherd/project.json")
assert_eq "project_id_stable" "$pid2" "$pid"

# Auto-detect: with .shepherd/ now present, plain init keeps using it (no .artifacts/).
[[ ! -d "$SHCTX_TEST_TMP/.artifacts" ]] || { echo "FAIL: auto-detect drifted to .artifacts/" >&2; exit 1; }

# ---- Mode 2: --artifacts opt-in (fresh repo) ----
SHCTX_TEST_TMP2="$(mktemp -d -t shctx-test.XXXXXX)"
trap 'rm -rf "$SHCTX_TEST_TMP" "$SHCTX_TEST_TMP2"' EXIT
(
  cd "$SHCTX_TEST_TMP2"
  git init -q .
  git config user.email t@t
  git config user.name t
  echo "test" > README.md
  git add README.md && git commit -qm init
  "$SHCTX" init --artifacts
)

assert_file "$SHCTX_TEST_TMP2/.artifacts/root.db"
assert_file "$SHCTX_TEST_TMP2/.artifacts/project.json"
assert_file "$SHCTX_TEST_TMP2/.artifacts/CONVENTIONS.md"
assert_file "$SHCTX_TEST_TMP2/.artifacts/.gitignore"
for d in ctx plans reports docs/handoffs docs/specs docs/diagrams docs/journal logs tmp profiles; do
  [[ -d "$SHCTX_TEST_TMP2/.artifacts/$d" ]] || { echo "FAIL: missing dir: .artifacts/$d" >&2; exit 1; }
done
# Opt-in mode MUST NOT create .shepherd/.
[[ ! -d "$SHCTX_TEST_TMP2/.shepherd" ]] || { echo "FAIL: .shepherd/ unexpectedly created in --artifacts mode" >&2; exit 1; }

# Re-running plain `init` in the .artifacts/ project keeps using .artifacts/ (auto-detect).
(cd "$SHCTX_TEST_TMP2" && "$SHCTX" init)
[[ ! -d "$SHCTX_TEST_TMP2/.shepherd" ]] || { echo "FAIL: auto-detect drifted from .artifacts/ to .shepherd/" >&2; exit 1; }
