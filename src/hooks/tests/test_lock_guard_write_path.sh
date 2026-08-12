#!/usr/bin/env bash
# hooks/tests/test_lock_guard_write_path.sh — v6.4.4 run-scoped write-path gate.
#
# lock_guard.sh Check 1 is the enforcement layer for the artifact schema's
# read-only-role write paths. Until v6.4.4 it pinned both roles to
# `{paths.reports}/<date>-...` (= .shepherd/docs/reports/), contradicting
# `skills/context/references/naming-conventions.md §Run layout`, which has said
# `{run_dir}/reports/` and `{run_dir}/audits/` since v6.4.1. The consequence was
# a run's own audits and discovery reports being ledgered into the CROSS-RUN
# docs tree while the run-scoped dirs sat empty.
#
# These cases pin BOTH directions: the run-scoped path is allowed, and the
# legacy docs/reports/ target is DENIED with a message naming the right one.
# A guard that only allowed the new path would leave the old one working.
#
# Deterministic, no network, no LLM. <2s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$ROOT/hooks/scripts/lock_guard.sh"

total=0; fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq missing"; exit 0; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
branch="$(git rev-parse --abbrev-ref HEAD)"

NS="$tmp/.shepherd"
mkdir -p "$NS/dispatch/$branch" .claude
# `is_shepherd_project` gates the whole guard — without a config the hook exits
# 0 immediately and EVERY case would pass vacuously, including the deny ones.
printf '[project]\nname="t"\n' > .claude/shepherd.toml

# Register a dispatch record per role, so `current_role` resolves by
# tool_use_id exactly as it does at runtime.
for role in discovery auditor; do
  printf '{"agent_role":"%s"}\n' "$role" > "$NS/dispatch/$branch/tu-$role.json"
done

# Drive the guard and echo its decision ("deny" or "allow").
decide() {  # <role> <file_path>
  local role="$1" path="$2" out
  out="$(printf '{"session_id":"s1","tool_name":"Write","tool_use_id":"tu-%s","tool_input":{"file_path":"%s"}}' \
         "$role" "$path" | bash "$GUARD" 2>/dev/null || true)"
  if printf '%s' "$out" | jq -e '.permissionDecision == "deny"' >/dev/null 2>&1; then
    printf 'deny\n'
  else
    printf 'allow\n'
  fi
}

# Capture the deny message for assertions on its content.
deny_msg() {  # <role> <file_path>
  local role="$1" path="$2"
  printf '{"session_id":"s1","tool_name":"Write","tool_use_id":"tu-%s","tool_input":{"file_path":"%s"}}' \
    "$role" "$path" | bash "$GUARD" 2>/dev/null | jq -r '.message // ""' 2>/dev/null || true
}

RUN="$NS/runs/v644-dev0"

# ---------------------------------------------------------------------------
# @discovery — {run_dir}/reports/discovery-<id>.md
# ---------------------------------------------------------------------------
total=$((total+1))
if [[ "$(decide discovery "$RUN/reports/discovery-cache-layer.md")" == "allow" ]]; then
  pass "discovery: run-scoped reports/discovery-<id>.md ALLOWED"
else
  fail "discovery run-scoped allowed" "$(deny_msg discovery "$RUN/reports/discovery-cache-layer.md")"
fi

total=$((total+1))
if [[ "$(decide discovery "$NS/docs/reports/2026-08-06-discovery-cache-layer.md")" == "deny" ]]; then
  pass "discovery: legacy docs/reports/<date>-discovery-*.md DENIED"
else
  fail "discovery legacy denied" "legacy target was accepted — the fix is not enforced"
fi

total=$((total+1))
msg="$(deny_msg discovery "$NS/docs/reports/2026-08-06-discovery-cache-layer.md")"
if printf '%s' "$msg" | grep -q 'CROSS-RUN' && printf '%s' "$msg" | grep -q '{run_dir}/reports/'; then
  pass "discovery: deny message names the CROSS-RUN mistake and the correct path"
else
  fail "discovery deny message actionable" "msg=${msg:0:200}"
fi

total=$((total+1))
if [[ "$(decide discovery "$RUN/audits/audit-code-quality.md")" == "deny" ]]; then
  pass "discovery: may not write into the auditor's audits/ dir"
else
  fail "discovery cross-role denied" "discovery wrote an audit"
fi

# ---------------------------------------------------------------------------
# @auditor — {run_dir}/audits/{intro-,}audit-<concern>.md
# ---------------------------------------------------------------------------
total=$((total+1))
if [[ "$(decide auditor "$RUN/audits/audit-code-quality.md")" == "allow" ]]; then
  pass "auditor: run-scoped audits/audit-<concern>.md ALLOWED"
else
  fail "auditor run-scoped allowed" "$(deny_msg auditor "$RUN/audits/audit-code-quality.md")"
fi

total=$((total+1))
if [[ "$(decide auditor "$RUN/audits/intro-audit-regression.md")" == "allow" ]]; then
  pass "auditor: intro-mode audits/intro-audit-<concern>.md ALLOWED"
else
  fail "auditor intro allowed" "$(deny_msg auditor "$RUN/audits/intro-audit-regression.md")"
fi

total=$((total+1))
if [[ "$(decide auditor "$RUN/audits/audit-wave-review-lane-a-w2.md")" == "allow" ]]; then
  pass "auditor: wave-review audits/audit-wave-review-<lane>-w<N>.md ALLOWED"
else
  fail "auditor wave-review allowed" "$(deny_msg auditor "$RUN/audits/audit-wave-review-lane-a-w2.md")"
fi

total=$((total+1))
if [[ "$(decide auditor "$NS/docs/reports/2026-08-06-audit-code-quality.md")" == "deny" ]]; then
  pass "auditor: legacy docs/reports/<date>-audit-*.md DENIED"
else
  fail "auditor legacy denied" "legacy target was accepted — the fix is not enforced"
fi

total=$((total+1))
msg="$(deny_msg auditor "$NS/docs/reports/2026-08-06-audit-code-quality.md")"
if printf '%s' "$msg" | grep -q 'CROSS-RUN' && printf '%s' "$msg" | grep -q '{run_dir}/audits/'; then
  pass "auditor: deny message names the CROSS-RUN mistake and the correct path"
else
  fail "auditor deny message actionable" "msg=${msg:0:200}"
fi

# ---------------------------------------------------------------------------
# The date prefix is gone: the run dir carries identity, so a dated filename
# inside it is the misplaced shape `shctx lint` flags.
# ---------------------------------------------------------------------------
total=$((total+1))
if [[ "$(decide auditor "$RUN/audits/2026-08-06-audit-code-quality.md")" == "deny" ]]; then
  pass "auditor: date-prefixed filename inside the run dir DENIED"
else
  fail "auditor date prefix denied" "a dated run-dir filename was accepted"
fi

# ---------------------------------------------------------------------------
# Unconstrained roles still pass through (the guard is not a global write lock).
# ---------------------------------------------------------------------------
total=$((total+1))
printf '{"agent_role":"conductor"}\n' > "$NS/dispatch/$branch/tu-conductor.json"
if [[ "$(decide conductor "$NS/docs/specs/2026-08-06-anything.md")" == "allow" ]]; then
  pass "conductor: unconstrained role passes through"
else
  fail "conductor passthrough" "an unconstrained role was blocked"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
