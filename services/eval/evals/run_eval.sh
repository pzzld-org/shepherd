#!/usr/bin/env bash
# services/eval/evals/run_eval.sh — the PERIODIC eval lane (paid, real judge).
#
# This is the eval suite that proves the harness GENERALIZES: a real Claude Code
# judge must pass the golden-good cases, fail the golden-bad cases, and separate
# them by a clear margin. It spends LLM calls, so it is NOT part of the <2s gate
# lane — run it before ship and nightly.
#
#   SHEPHERD_EVAL_LIVE=1 bash services/eval/evals/run_eval.sh
#   SHEPHERD_EVAL_LIVE=1 SHEPHERD_LLM_MODEL=haiku bash .../run_eval.sh   # cheaper
#
# Default judge model: opus (best by default). Override via SHEPHERD_LLM_MODEL.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EVAL="$HERE/../eval.sh"
CASES="$HERE/cases"

if [[ "${SHEPHERD_EVAL_LIVE:-0}" != "1" ]]; then
  echo "skip: live eval lane is gated — set SHEPHERD_EVAL_LIVE=1 to run (spends LLM calls)."
  exit 0
fi
# A stray mock from a parent shell would make this lane a lie — refuse it.
unset SHEPHERD_LLM_MOCK SHEPHERD_LLM_MOCK_TEXT

# Minimum score gap required between a good case and its bad sibling.
MARGIN="${SHEPHERD_EVAL_MARGIN:-15}"

_score() { # kind file -> echoes overall ; returns nonzero only on a real judge error
  # eval.sh exits 1 for a below-threshold verdict (the bad cases SHOULD do this),
  # so capture stdout regardless and treat only exit >=2 as a genuine error.
  local out rc=0
  out="$(bash "$EVAL" run --kind="$1" --input-file="$2" --json)" || rc=$?
  (( rc >= 2 )) && return 1
  printf '%s' "$out" | jq -r '.overall'
}

fails=0
_pair() { # kind  good-case  bad-case
  local kind="$1" good="$2" bad="$3" gs bs
  echo "── $kind"
  gs="$(_score "$kind" "$CASES/$good")" || { echo "  ERROR scoring $good"; fails=$((fails+1)); return; }
  bs="$(_score "$kind" "$CASES/$bad")"  || { echo "  ERROR scoring $bad";  fails=$((fails+1)); return; }
  echo "  good ($good) = $gs/100"
  echo "  bad  ($bad)  = $bs/100"
  local thr; thr="$(jq -r '.threshold' "$HERE/../rubrics/$kind.rubric.json")"
  (( gs >= thr )) || { echo "  FAIL: good case scored below threshold ($thr)"; fails=$((fails+1)); }
  (( bs <  thr )) || { echo "  FAIL: bad case scored at/above threshold ($thr)"; fails=$((fails+1)); }
  (( gs - bs >= MARGIN )) || { echo "  FAIL: margin good-bad=$((gs-bs)) < $MARGIN"; fails=$((fails+1)); }
}

_pair reflection reflection_good.txt reflection_bad.txt
_pair discovery  discovery_good.txt  discovery_bad.txt
_pair dispatch   dispatch_good.txt   dispatch_bad.txt
_pair pi-tool-correlation pi_tool_call_id_good.txt pi_tool_call_id_bad.txt
_pair pi-bootstrap pi-bootstrap_good.txt pi-bootstrap_bad.txt
_pair least-authority v656/least-authority_good.txt v656/least-authority_bad.txt
_pair first-run v656/first-run_good.txt v656/first-run_bad.txt
_pair content    content_good.txt    content_bad.txt
_pair plugin-distribution plugin_distribution_good.txt plugin_distribution_bad.txt
_pair cargo-native-distribution cargo_native_distribution_good.txt cargo_native_distribution_bad.txt
_pair gate-provenance v656/gate-provenance_good.txt v656/gate-provenance_bad.txt
_pair release-trust v656/release-trust_good.txt v656/release-trust_bad.txt

if (( fails == 0 )); then
  echo "—— live eval lane PASSED (judge discriminates good from bad) ——"
  exit 0
fi
echo "—— live eval lane FAILED: $fails check(s) ——"
exit 1
