#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

cat > .shepherd/profiles/skip-critic-xs.toml <<'EOF'
name = "skip-critic-xs"
kind = "modifier"
[config]
skip_critic_for = ["XS"]
EOF

"$SHCTX" profile sync
n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" \
  "SELECT COUNT(*) FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "synced" "$n" "1"

"$SHCTX" profile disable skip-critic-xs
a=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" \
  "SELECT active FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "disabled" "$a" "0"

"$SHCTX" profile enable skip-critic-xs
a=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" \
  "SELECT active FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "enabled" "$a" "1"
