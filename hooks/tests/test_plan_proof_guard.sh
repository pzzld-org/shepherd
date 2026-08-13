#!/usr/bin/env bash
# hooks/tests/test_plan_proof_guard.sh — PreToolUse(Write|Edit) critic-proof
# integrity guard (DF-22, v6.4.5).
#
# Negative-control pattern (not grep-for-prose): every fixture is built
# through the REAL `shctx plan hash` / `record-critique` CLI, so each
# assertion exercises the same code path `shctx plan verify` uses at hook
# time. A typo'd guard condition fails a fixture, not a hand-authored
# expectation string.
#
# Usage:
#   test_plan_proof_guard.sh             # full suite
#   test_plan_proof_guard.sh --no-proof  # isolate the "no critic-proof exists
#                                         # -> write is allowed" negative control
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/plan_proof_guard.sh"
SHCTX="$ROOT/bin/shepherd"
export CLAUDE_PLUGIN_ROOT="$ROOT"

tmp=$(mktemp -d -t shep-plan-proof-hook.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q . >/dev/null
git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
printf '[project]\nname="t"\n' > .claude/shepherd.toml

payload() { # file_path tool -> PreToolUse JSON on stdout
  local fp="$1" tool="${2:-Write}"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg fp "$fp" --arg tool "$tool" \
      '{tool_name:$tool,session_id:"s",tool_use_id:"tu1",tool_input:{file_path:$fp}}'
  else
    python3 -c 'import json,sys
tool,fp=sys.argv[1:3]
print(json.dumps({"tool_name":tool,"session_id":"s","tool_use_id":"tu1","tool_input":{"file_path":fp}}))' \
      "$tool" "$fp"
  fi
}

fails=0
ck() { # name file_path tool want_substr  (empty want => expect silence)
  local name="$1" fp="$2" tool="$3" want="$4" out
  out=$(payload "$fp" "$tool" | bash "$HOOK" 2>/dev/null || true)
  if [[ -z "$want" ]]; then
    if [[ -z "$out" ]]; then echo "  PASS  $name"; else echo "  FAIL  $name: expected silence, got: $out"; fails=$((fails+1)); fi
  else
    if grep -qF -- "$want" <<<"$out"; then echo "  PASS  $name"; else echo "  FAIL  $name: want '$want' in: $out"; fails=$((fails+1)); fi
  fi
}

# ---- fixtures, built through the REAL CLI (no hand-forged JSON/hashes) ----
clean_plan="$tmp/clean.plan.md"
printf '# Clean\n\nv1 pre-critic draft.\n' > "$clean_plan"
pre=$(bash "$SHCTX" plan hash "$clean_plan")
printf '# Clean\n\nv2 post-critic revision.\n' > "$clean_plan"
bash "$SHCTX" plan record-critique --plan "$clean_plan" --pre "$pre" --verdict PASS --iterations 1 --findings 0 >/dev/null

stale_plan="$tmp/stale.plan.md"
printf '# Stale\n\nv1 pre-critic draft.\n' > "$stale_plan"
pre2=$(bash "$SHCTX" plan hash "$stale_plan")
printf '# Stale\n\nv2 post-critic revision.\n' > "$stale_plan"
bash "$SHCTX" plan record-critique --plan "$stale_plan" --pre "$pre2" --verdict PASS --iterations 1 --findings 0 >/dev/null
printf '# Stale\n\nv3 silently edited AFTER the proof was recorded (the DF-22 defect).\n' > "$stale_plan"

no_proof_plan="$tmp/fresh.plan.md"
printf '# Fresh\n\nnever critiqued.\n' > "$no_proof_plan"

no_proof_run="$tmp/.shepherd/runs/v900/plan.md"
mkdir -p "$(dirname "$no_proof_run")"
printf '# Run-scoped, never critiqued.\n' > "$no_proof_run"

if [[ "${1:-}" == "--no-proof" ]]; then
  echo "== test_plan_proof_guard --no-proof (isolated: no proof exists -> always allowed) =="
  ck "no-proof-write-allowed"      "$no_proof_plan" Write ""
  ck "no-proof-edit-allowed"       "$no_proof_plan" Edit  ""
  ck "no-proof-run-scoped-allowed" "$no_proof_run"  Write ""
  if [[ "$fails" -eq 0 ]]; then echo "PASS: test_plan_proof_guard --no-proof"; exit 0
  else echo "FAIL: test_plan_proof_guard --no-proof ($fails)"; exit 1
  fi
fi

echo "== test_plan_proof_guard (full suite) =="

# clean proof -> BLOCK (the whole point of the guard: DF-22)
ck "clean-proof-write-denied" "$clean_plan" Write '"permissionDecision":"deny"'
ck "clean-proof-edit-denied"  "$clean_plan" Edit  '"permissionDecision":"deny"'
ck "deny-names-plan-locked"   "$clean_plan" Write 'PLAN-PROOF-LOCKED'
ck "deny-names-record-critique" "$clean_plan" Write 'record-critique'
ck "deny-names-amend"         "$clean_plan" Write 'plan amend'

# stale proof (already broken) -> ALLOW; the guard protects a VALID attestation only
ck "stale-proof-write-allowed" "$stale_plan" Write ""
ck "stale-proof-edit-allowed"  "$stale_plan" Edit  ""

# no proof at all -> ALLOW; ordinary authoring must never be obstructed
ck "no-proof-write-allowed"      "$no_proof_plan" Write ""
ck "no-proof-run-scoped-allowed" "$no_proof_run"  Write ""

# non-plan file -> silent fast path (no shctx invocation at all)
ck "non-plan-file-silent" "$tmp/notes.md" Write ""

# non-Write/Edit tool -> silent fast path even against a clean-proof plan
ck "bash-tool-silent" "$clean_plan" Bash ""

# non-shepherd repo -> silent
rm -f .claude/shepherd.toml
ck "non-shepherd-silent" "$clean_plan" Write ""
printf '[project]\nname="t"\n' > .claude/shepherd.toml

if [[ "$fails" -eq 0 ]]; then echo "PASS: test_plan_proof_guard"; exit 0
else echo "FAIL: test_plan_proof_guard ($fails)"; exit 1
fi
