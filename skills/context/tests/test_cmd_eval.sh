#!/usr/bin/env bash
# test_cmd_eval.sh — shctx eval (v6.2.3 eval-harness glue).
#   run     resolves a subject (explicit input or the stored reflection note),
#           calls services/eval through the mocked judge, records to eval_runs.
#   report  latest verdict per subject (v_eval_latest).
#   list    recent eval_runs.
# The judge is MOCKED (SHEPHERD_LLM_MOCK) so this gate is deterministic + free.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" migrate >/dev/null            # applies 0018 (eval_runs) among others
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

# eval_runs table + view exist after migrate
assert_table "$DB" eval_runs
v=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='view' AND name='v_eval_latest';")
assert_eq "view-exists" "$v" "1"

# Point the glue at the real eval service; mock the judge response.
export SHEPHERD_EVAL_SVC="$(cd "$SHCTX_SKILL_ROOT/../.." && pwd)/services/eval/eval.sh"
assert_file "$SHEPHERD_EVAL_SVC"
MOCK="$SHCTX_TEST_TMP/judge.json"
printf '{"scores":{"specificity":4,"actionability":4,"grounding":3},"rationale":"sharp"}' > "$MOCK"
export SHEPHERD_LLM_MOCK="$MOCK"

# --- run with explicit input + record (4,4,3 -> 76 PASS, exit 0) ---
rc=0; out=$("$SHCTX" eval run --kind=reflection --input='front-load the dups gate next sprint' --record --json) || rc=$?
assert_eq "run-pass-exit" "$rc" "0"
assert_eq "run-overall" "$(jq -r .overall <<<"$out")" "76"
assert_eq "run-passed"  "$(jq -r .passed  <<<"$out")" "true"
n=$(sqlite3 "$DB" "SELECT count(*) FROM eval_runs WHERE kind='reflection';")
assert_eq "recorded-row" "$n" "1"
sc=$(sqlite3 "$DB" "SELECT score FROM eval_runs WHERE kind='reflection' LIMIT 1;")
assert_eq "recorded-score" "$sc" "76"

# --- threshold override flips verdict to FAIL (exit 1), still records ---
rc=0; out=$("$SHCTX" eval run --kind=reflection --input='x' --threshold=90 --record --json) || rc=$?
assert_eq "run-fail-exit" "$rc" "1"
assert_eq "run-fail-passed" "$(jq -r .passed <<<"$out")" "false"
nfail=$(sqlite3 "$DB" "SELECT count(*) FROM eval_runs WHERE passed=0;")
assert_eq "recorded-fail" "$nfail" "1"

# --- pull the stored reflection note from the registry by sprint ---
"$SHCTX" adapt reflect --sprint=demo --note="lanes were oversized for a docs sprint" >/dev/null
rc=0; out=$("$SHCTX" eval run --kind=reflection --sprint=demo --record --json) || rc=$?
assert_eq "run-sprint-exit" "$rc" "0"
sr=$(sqlite3 "$DB" "SELECT subject_ref FROM eval_runs WHERE subject_ref='demo' LIMIT 1;")
assert_eq "recorded-subject" "$sr" "demo"

# missing stored reflection -> usage error (exit 2), no crash
rc=0; "$SHCTX" eval run --kind=reflection --sprint=absent >/dev/null 2>&1 || rc=$?
assert_eq "missing-reflection-exit" "$rc" "2"

# --- report + list surface the recorded verdicts ---
out=$("$SHCTX" eval report --md)
assert_contains "report-md" "$out" "reflection"
out=$("$SHCTX" eval report --json)
assert_contains "report-json" "$out" "\"kind\""
out=$("$SHCTX" eval list)
assert_contains "list-text" "$out" "reflection"

# v_eval_latest keeps the latest per (kind, subject) — demo recorded once here
latest=$(sqlite3 "$DB" "SELECT count(*) FROM v_eval_latest WHERE subject_ref='demo';")
assert_eq "latest-one-per-subject" "$latest" "1"

# --- error paths ---
rc=0; "$SHCTX" eval run --kind=nope --input=x >/dev/null 2>&1 || rc=$?
assert_eq "unknown-kind-exit" "$rc" "2"
rc=0; "$SHCTX" eval run --kind=reflection >/dev/null 2>&1 || rc=$?   # no input, no sprint
assert_eq "no-input-exit" "$rc" "2"

# --- dash surfaces an EVAL row once something is recorded ---
out=$("$SHCTX" dash 2>/dev/null || true)
assert_contains "dash-eval-row" "$out" "EVAL"

echo "test_cmd_eval: ok"
