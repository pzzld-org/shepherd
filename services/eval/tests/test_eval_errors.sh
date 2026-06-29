#!/usr/bin/env bash
# Gate: error paths fail loudly with the right exit code — never a silent pass.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EVAL="$HERE/../eval.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# unknown kind -> exit 2
rc=0; bash "$EVAL" run --kind=nope --input=x >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: unknown kind exit: got $rc"; exit 1; }

# missing --kind -> exit 2
rc=0; bash "$EVAL" run --input=x >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: missing kind exit: got $rc"; exit 1; }

# empty input -> exit 2
rc=0; SHEPHERD_LLM_MOCK_TEXT='{}' bash "$EVAL" run --kind=reflection --input='   ' >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: empty input exit: got $rc"; exit 1; }

# judge returns non-JSON -> exit 4
printf 'I think it is pretty good honestly' > "$TMP/prose"
rc=0; SHEPHERD_LLM_MOCK="$TMP/prose" bash "$EVAL" run --kind=reflection --input=x >/dev/null 2>&1 || rc=$?
[[ "$rc" == 4 ]] || { echo "FAIL: non-JSON judge exit: got $rc"; exit 1; }

# judge omits a required dimension -> exit 4 (validation, not a bogus score)
printf '{"scores":{"specificity":4},"rationale":"partial"}' > "$TMP/partial"
rc=0; SHEPHERD_LLM_MOCK="$TMP/partial" bash "$EVAL" run --kind=reflection --input=x >/dev/null 2>&1 || rc=$?
[[ "$rc" == 4 ]] || { echo "FAIL: missing-dimension exit: got $rc"; exit 1; }

# judge score out of range -> exit 4
printf '{"scores":{"specificity":9,"actionability":4,"grounding":3},"rationale":"x"}' > "$TMP/oor"
rc=0; SHEPHERD_LLM_MOCK="$TMP/oor" bash "$EVAL" run --kind=reflection --input=x >/dev/null 2>&1 || rc=$?
[[ "$rc" == 4 ]] || { echo "FAIL: out-of-range exit: got $rc"; exit 1; }

# unknown flag -> exit 2
rc=0; SHEPHERD_LLM_MOCK_TEXT='{}' bash "$EVAL" run --kind=reflection --bogus >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: unknown flag exit: got $rc"; exit 1; }

echo "ok: eval errors"
