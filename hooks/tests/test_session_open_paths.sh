#!/usr/bin/env bash
# hooks/tests/test_session_open_paths.sh — session_open.sh plan-validity is
# [paths]-aware (v6.4.1; fixes the pre-existing hardcoded-plans/ bug res_12 §1c).
#
# Pre-v6.4.1 the plan-validity check HARDCODED "$ns/plans" — a repo whose
# config put plans under docs/plans (this dogfood repo's own shape) got a
# false "no plan.md" warning at every session start. Now:
#   • [paths].plans is honored for the legacy {branch|slug}.plan.md forms;
#   • the run-scoped {paths.runs}/{slug}/plan.md satisfies the check too;
#   • the multi-plan reconciliation surface (issue #26) reads the same
#     configured plans dir.
#
# Conventions mirror hooks/tests/test_coordinate_drive_guard.sh.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

open() { # echoes session_open.sh stdout
  printf '{"session_id":"s1","hook_event_name":"SessionStart","source":"startup"}' \
    | bash "$HOOKS_DIR/session_open.sh" 2>/dev/null || true
}
has_no_plan_warn() { printf '%s' "$1" | grep -q 'has no plan.md'; }

tmp=$(mktemp -d -t shep-sop-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
git checkout -q -b v1.0.0-dev.0
mkdir -p .claude .shepherd
cat > .claude/shepherd.toml <<'TOML'
[paths]
plans = ".shepherd/docs/plans"
runs  = ".shepherd/runs"
TOML

# ---------------------------------------------------------------------------
# 1. No plan anywhere → the warning fires and names the configured locations.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(open)
if has_no_plan_warn "$out" && printf '%s' "$out" | grep -q 'runs/v100-dev0/plan.md'; then
  pass "no plan anywhere: warning names the run-scoped location"
else
  fail "no plan anywhere: warning" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# 2. Plan at the CONFIGURED [paths].plans dir (slug form) → no warning.
#    (Pre-v6.4.1 this exact layout false-warned: the hook only read $ns/plans.)
# ---------------------------------------------------------------------------
total=$((total+1))
mkdir -p .shepherd/docs/plans
echo plan > .shepherd/docs/plans/v100-dev0.plan.md
out=$(open)
if ! has_no_plan_warn "$out"; then
  pass "[paths].plans honored: configured-dir plan silences the warning"
else
  fail "[paths].plans honored" "out=${out:0:200}"
fi
rm -f .shepherd/docs/plans/v100-dev0.plan.md

# ---------------------------------------------------------------------------
# 3. Plan ONLY at the run-scoped {paths.runs}/{slug}/plan.md → no warning.
# ---------------------------------------------------------------------------
total=$((total+1))
mkdir -p .shepherd/runs/v100-dev0
echo plan > .shepherd/runs/v100-dev0/plan.md
out=$(open)
if ! has_no_plan_warn "$out"; then
  pass "run-scoped runs/{slug}/plan.md satisfies plan validity"
else
  fail "run-scoped plan satisfies validity" "out=${out:0:200}"
fi
rm -f .shepherd/runs/v100-dev0/plan.md

# ---------------------------------------------------------------------------
# 4. Multi-plan surface (issue #26) reads the CONFIGURED plans dir: two
#    addendum-form plans there → the reconcile warning lists both.
# ---------------------------------------------------------------------------
total=$((total+1))
echo plan > .shepherd/docs/plans/v1.0.0-dev.0.plan.md
echo plan > .shepherd/docs/plans/v1.0.0-dev.0b.plan.md
out=$(open)
if printf '%s' "$out" | grep -q 'plan files for sprint' \
   && printf '%s' "$out" | grep -q 'v1.0.0-dev.0b.plan.md'; then
  pass "multi-plan reconciliation reads the configured plans dir"
else
  fail "multi-plan reads configured dir" "out=${out:0:250}"
fi

# ---------------------------------------------------------------------------
# 5. Default fallback: no [paths] config → legacy $ns/plans still works.
# ---------------------------------------------------------------------------
total=$((total+1))
printf '' > .claude/shepherd.toml
rm -rf .shepherd/docs
mkdir -p .shepherd/plans
echo plan > .shepherd/plans/v100-dev0.plan.md
out=$(open)
if ! has_no_plan_warn "$out"; then
  pass "no [paths] config: legacy \$ns/plans default still satisfies"
else
  fail "legacy default satisfies" "out=${out:0:200}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
