# tests/_setup.sh — sourced by every test file
set -eu -o pipefail

# Disable commit signing for every throwaway test repo. Runners that enforce
# signing (e.g. a signing-server-backed `gpg.format`/`commit.gpgsign=true` in
# global config) otherwise fail `git commit` in these ephemeral repos, breaking
# the whole suite for environmental reasons. GIT_CONFIG_* applies to all git
# invocations in the test process regardless of per-repo config.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=commit.gpgsign
export GIT_CONFIG_VALUE_0=false

# Canonicalize the temp dir to its physical path. On macOS `mktemp -d` returns a
# path under /var/folders/… which is a symlink to /private/var/folders/…; git
# (`rev-parse --show-toplevel`, used by shctx_repo_root) resolves the symlink, so
# any assertion comparing SHCTX_TEST_TMP against a git-derived path would spuriously
# differ. `pwd -P` resolves it once so both sides agree on every platform.
SHCTX_TEST_TMP="$(cd "$(mktemp -d -t shctx-test.XXXXXX)" && pwd -P)"
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
  local db="$SHCTX_TEST_TMP/.shepherd/shepherd.db"
  mkdir -p "$SHCTX_TEST_TMP/.shepherd"
  sqlite3 "$db" < "$SHCTX_SKILL_ROOT/schema/0001_init.sql" >/dev/null
  echo "$db"
}

export SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
