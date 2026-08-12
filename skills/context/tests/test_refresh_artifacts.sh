#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

mkdir -p .shepherd/plans .shepherd/reports .shepherd/docs/specs
echo "# seed" > .shepherd/plans/v0.0.1-dev.0.seed.md
echo "# plan" > .shepherd/plans/v0.0.1-dev.0.plan.md
echo "# close" > .shepherd/reports/2026-01-01-v0.0.1-dev.0.close.md
echo "# spec" > .shepherd/docs/specs/2026-01-01-foo.spec.md
# Hyphen-prefixed variants (real-world filenames like 2026-05-04-shepherd-context-design.md).
echo "# design"   > .shepherd/docs/specs/2026-01-02-foo-design.md
echo "# spec2"    > .shepherd/docs/specs/2026-01-03-foo-spec.md
echo "# plan2"    > .shepherd/plans/2026-01-04-foo-plan.md
echo "# addendum" > .shepherd/docs/specs/2026-01-05-foo-addendum.md

"$SHCTX" refresh --scope=artifacts

for k in seed plan close spec design addendum; do
  n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT COUNT(*) FROM artifacts WHERE kind='$k';")
  [[ "$n" -ge 1 ]] || { echo "FAIL: kind=$k not indexed (got $n)" >&2; exit 1; }
done

# Hyphen-variant spec count should be 2 (one with .spec.md, one with -spec.md).
n_spec=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT COUNT(*) FROM artifacts WHERE kind='spec';")
[[ "$n_spec" -ge 2 ]] || { echo "FAIL: hyphen-variant spec not indexed (n=$n_spec)" >&2; exit 1; }
n_plan=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT COUNT(*) FROM artifacts WHERE kind='plan';")
[[ "$n_plan" -ge 2 ]] || { echo "FAIL: hyphen-variant plan not indexed (n=$n_plan)" >&2; exit 1; }

# ---- Auto-refresh on init: a fresh repo seeded BEFORE init should be indexed by init alone ----
SHCTX_TEST_TMP3="$(mktemp -d -t shctx-test.XXXXXX)"
trap 'rm -rf "$SHCTX_TEST_TMP" "$SHCTX_TEST_TMP3"' EXIT
(
  cd "$SHCTX_TEST_TMP3"
  git init -q .
  git config user.email t@t
  git config user.name t
  echo "test" > README.md
  git add README.md && git commit -qm init
  mkdir -p .shepherd/docs/specs
  echo "# pre-existing" > .shepherd/docs/specs/2026-05-04-foo-design.md
  out=$("$SHCTX" init 2>&1)
  if ! grep -qF "auto-indexing" <<< "$out"; then
    echo "FAIL: init did not auto-index pre-existing artifacts" >&2; exit 1
  fi
  n=$(sqlite3 .shepherd/shepherd.db "SELECT COUNT(*) FROM artifacts WHERE kind='design';")
  [[ "$n" -ge 1 ]] || { echo "FAIL: pre-existing design not indexed by init (n=$n)" >&2; exit 1; }
)
