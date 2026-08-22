#!/usr/bin/env bash
set -eu -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EVALS="$HERE/../evals"
GOOD="$EVALS/cases/v656/least-authority_good.txt"
BAD="$EVALS/cases/v656/least-authority_bad.txt"

for path in "$GOOD" "$BAD" "$HERE/../rubrics/least-authority.rubric.json"; do
  [[ -s "$path" ]] || { echo "FAIL: missing least-authority eval artifact: $path"; exit 1; }
done

grep -Fq '_pair least-authority v656/least-authority_good.txt v656/least-authority_bad.txt' "$EVALS/run_eval.sh"   || { echo 'FAIL: periodic eval does not run the least-authority pair'; exit 1; }
grep -Fq 'explicit empty scope' "$GOOD"   || { echo 'FAIL: good case does not require explicit non-writable scope'; exit 1; }
grep -Fq 'root-level `*.md`' "$GOOD"   || { echo 'FAIL: good case does not bound root structured writes'; exit 1; }
grep -Fq 'one exact non-glob' "$GOOD"   || { echo 'FAIL: good case does not narrow report-write'; exit 1; }
grep -Fq 'complete root facts' "$GOOD"   || { echo 'FAIL: good case does not require complete root facts'; exit 1; }
grep -Fq 'without shell parsing' "$GOOD"   || { echo 'FAIL: good case does not reject shell inference'; exit 1; }
grep -Fq 'lane-less `write_scope: ["**"]`' "$BAD"   || { echo 'FAIL: bad case does not cover universal fallback'; exit 1; }
grep -Fq 'broad report glob' "$BAD"   || { echo 'FAIL: bad case does not cover broad report authority'; exit 1; }
grep -Fq 'missing or complete root facts' "$BAD"   || { echo 'FAIL: bad case does not cover root opaque-shell authorization'; exit 1; }

printf 'ok: least-authority periodic eval pair is wired
'
