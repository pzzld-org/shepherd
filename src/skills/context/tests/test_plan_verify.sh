#!/usr/bin/env bash
# skills/context/tests/test_plan_verify.sh — critic-proof gate (v6.2.5, #169).
#
# Deterministic: `shctx plan hash` / `record-critique` / `verify` prove the plan
# was critiqued AND edited at least once, hash-tied to the live plan bytes. A
# proof with edited=false, a stale hash, or a missing proof MUST fail with the
# named code. Runs cmd_plan.sh inside an ephemeral git repo.

set -uo pipefail
SCRIPTS="$(cd "$(dirname "$0")/../scripts" && pwd)"
CMD="$SCRIPTS/cmd_plan.sh"

fails=0
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fails=$((fails+1)); }

tmp=$(mktemp -d -t shep-planverify-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
mkdir -p .claude; printf '[project]\nname="t"\n' > .claude/shepherd.toml
plan="$tmp/v625.plan.md"

# 1. hash echoes sha256:
printf '# plan v1\nwave-1\n' > "$plan"
PRE="$(bash "$CMD" hash "$plan" 2>/dev/null)"
case "$PRE" in sha256:*) ok "hash emits sha256" ;; *) bad "hash emits sha256 (got $PRE)" ;; esac

# 2. Happy path: edit the plan after the pre-hash, record, verify passes.
printf '# plan v2 (revised per critic)\nwave-1\nwave-2\n' > "$plan"
bash "$CMD" record-critique --plan "$plan" --pre "$PRE" --verdict PASS --iterations 1 --findings 2 >/dev/null 2>&1
proof="$tmp/v625.critic-proof.json"
[[ -f "$proof" ]] && ok "record-critique wrote proof" || bad "record-critique wrote proof"
if bash "$CMD" verify --plan "$plan" --quiet >/dev/null 2>&1; then ok "verify passes on edited+critiqued plan"; else bad "verify passes on edited+critiqued plan"; fi

# 3. PLAN-UNEDITED: pre == current (no edit between hash and record).
printf '# plan unedited\n' > "$plan"
HASH_NOW="$(bash "$CMD" hash "$plan" 2>/dev/null)"
bash "$CMD" record-critique --plan "$plan" --pre "$HASH_NOW" --verdict PASS --iterations 1 >/dev/null 2>&1
out="$(bash "$CMD" verify --plan "$plan" 2>&1)"; rc=$?
if [[ $rc -ne 0 && "$out" == *PLAN-UNEDITED* ]]; then ok "unedited plan → PLAN-UNEDITED"; else bad "unedited plan → PLAN-UNEDITED (rc=$rc out=$out)"; fi

# 4. CRITIC-PROOF-STALE: valid proof, then the plan changes underneath it.
printf '# plan A\n' > "$plan"; PRE2="$(bash "$CMD" hash "$plan" 2>/dev/null)"
printf '# plan B (revised)\n' > "$plan"
bash "$CMD" record-critique --plan "$plan" --pre "$PRE2" --verdict PASS --iterations 1 >/dev/null 2>&1
printf '# plan C (edited AFTER the proof)\n' > "$plan"
out="$(bash "$CMD" verify --plan "$plan" 2>&1)"; rc=$?
if [[ $rc -ne 0 && "$out" == *CRITIC-PROOF-STALE* ]]; then ok "post-proof edit → CRITIC-PROOF-STALE"; else bad "post-proof edit → CRITIC-PROOF-STALE (rc=$rc out=$out)"; fi

# 5. CRITIC-PROOF-MISSING: no proof for the plan.
rm -f "$proof"
plan2="$tmp/noproof.plan.md"; printf '# no proof\n' > "$plan2"
out="$(bash "$CMD" verify --plan "$plan2" 2>&1)"; rc=$?
if [[ $rc -ne 0 && "$out" == *CRITIC-PROOF-MISSING* ]]; then ok "no proof → CRITIC-PROOF-MISSING"; else bad "no proof → CRITIC-PROOF-MISSING (rc=$rc out=$out)"; fi

if [[ "$fails" -gt 0 ]]; then
  printf 'test_plan_verify: %d failure(s)\n' "$fails"; exit 1
fi
printf 'test_plan_verify: OK — hash/record/verify + PLAN-UNEDITED + CRITIC-PROOF-STALE + CRITIC-PROOF-MISSING\n'
