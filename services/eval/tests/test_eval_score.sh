#!/usr/bin/env bash
# Gate: the deterministic verdict — weighted overall, threshold pass/fail, exit
# code, json shape — given a mocked judge. reflection rubric: scale=5,
# weights specificity=2 actionability=2 grounding=1 (total 5), threshold=60.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EVAL="$HERE/../eval.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

run() { # $1=mockfile  rest=args ; echoes stdout, sets RC
  RC=0; OUT="$(SHEPHERD_LLM_MOCK="$1" bash "$EVAL" run --kind=reflection "${@:2}")" || RC=$?
}

# 4,4,3 -> ws=19 -> overall=round(100*19/25)=76 -> PASS, exit 0
printf '{"scores":{"specificity":4,"actionability":4,"grounding":3},"rationale":"ok"}' > "$TMP/m1"
run "$TMP/m1" --input='x' --json
[[ "$RC" == 0 ]] || { echo "FAIL: pass exit: got $RC"; exit 1; }
[[ "$(jq -r .overall <<<"$OUT")" == 76 ]] || { echo "FAIL: overall: $(jq -r .overall <<<"$OUT")"; exit 1; }
[[ "$(jq -r .passed  <<<"$OUT")" == true ]] || { echo "FAIL: passed flag"; exit 1; }

# 1,1,1 -> overall=20 -> FAIL, exit 1
printf '{"scores":{"specificity":1,"actionability":1,"grounding":1},"rationale":"meh"}' > "$TMP/m2"
run "$TMP/m2" --input='x' --json
[[ "$RC" == 1 ]] || { echo "FAIL: fail exit: got $RC"; exit 1; }
[[ "$(jq -r .overall <<<"$OUT")" == 20 ]] || { echo "FAIL: overall low: $(jq -r .overall <<<"$OUT")"; exit 1; }
[[ "$(jq -r .passed  <<<"$OUT")" == false ]] || { echo "FAIL: passed=false"; exit 1; }

# weighting actually matters: 1,1,5 -> ws=1*2+1*2+5*1=9 -> overall=36 (not the
# unweighted mean 36.7→… both round near; pick a case that differs from mean).
# 5,5,1 -> ws=5*2+5*2+1=21 -> overall=84 ; unweighted mean would be 73.3 -> 73.
printf '{"scores":{"specificity":5,"actionability":5,"grounding":1},"rationale":"w"}' > "$TMP/m3"
run "$TMP/m3" --input='x' --json
[[ "$(jq -r .overall <<<"$OUT")" == 84 ]] || { echo "FAIL: weighting: expected 84 got $(jq -r .overall <<<"$OUT")"; exit 1; }

# threshold override flips the verdict: overall 76 with --threshold=80 -> FAIL
run "$TMP/m1" --input='x' --threshold=80 --json
[[ "$RC" == 1 ]] || { echo "FAIL: threshold override exit: got $RC"; exit 1; }
[[ "$(jq -r .threshold <<<"$OUT")" == 80 ]] || { echo "FAIL: threshold echoed"; exit 1; }

# json output is the ONLY thing on stdout (clean machine contract)
run "$TMP/m1" --input='x' --json
echo "$OUT" | jq -e . >/dev/null || { echo "FAIL: json not clean: $OUT"; exit 1; }

# model is recorded (default opus when not forwarded)
[[ "$(jq -r .model <<<"$OUT")" == opus ]] || { echo "FAIL: model: $(jq -r .model <<<"$OUT")"; exit 1; }
# forwarded model is echoed
run "$TMP/m1" --input='x' --model=haiku --json
[[ "$(jq -r .model <<<"$OUT")" == haiku ]] || { echo "FAIL: model forward: $(jq -r .model <<<"$OUT")"; exit 1; }

echo "ok: eval score"
