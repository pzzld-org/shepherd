# tests/_setup.sh — sourced by every test file
set -eu -o pipefail

SHCTX_TEST_TMP="$(mktemp -d -t shctx-test.XXXXXX)"
trap 'rm -rf "$SHCTX_TEST_TMP"' EXIT

# Stand up a fake repo root with .shepherd skeleton.
shctx_test_repo() {
  cd "$SHCTX_TEST_TMP"
  git init -q .
  git config user.email t@t
  git config user.name t
  echo "test" > README.md
  git add README.md && git commit -qm init
}

# Produce a fresh, empty DB initialized with schema 0001.
shctx_test_db() {
  local db="$SHCTX_TEST_TMP/.shepherd/root.db"
  mkdir -p "$SHCTX_TEST_TMP/.shepherd"
  sqlite3 "$db" < "$SHCTX_SKILL_ROOT/schema/0001_init.sql" >/dev/null
  echo "$db"
}

export SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
