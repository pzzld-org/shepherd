#!/usr/bin/env bash
# Gate: every shipped rubric is structurally valid. A malformed rubric would make
# `eval run` produce garbage scores silently — so this fails loudly instead.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUBRICS="$HERE/../rubrics"

n=0
for f in "$RUBRICS"/*.rubric.json; do
  n=$((n+1))
  name="$(basename "$f")"
  jq -e . "$f" >/dev/null 2>&1 || { echo "FAIL: $name is not valid JSON"; exit 1; }

  # filename kind must equal the .kind field
  fkind="${name%.rubric.json}"
  jkind="$(jq -r '.kind' "$f")"
  [[ "$fkind" == "$jkind" ]] || { echo "FAIL: $name kind mismatch (file=$fkind json=$jkind)"; exit 1; }

  # scale + threshold are positive integers; threshold within 0..100
  jq -e '(.scale|type=="number") and (.scale|floor==.) and .scale>=2' "$f" >/dev/null \
    || { echo "FAIL: $name scale must be integer >=2"; exit 1; }
  jq -e '(.threshold|type=="number") and .threshold>=0 and .threshold<=100' "$f" >/dev/null \
    || { echo "FAIL: $name threshold must be 0..100"; exit 1; }

  # at least one dimension; each has key/weight(>0 int)/desc; keys unique
  jq -e '(.dimensions|length)>=1' "$f" >/dev/null || { echo "FAIL: $name has no dimensions"; exit 1; }
  jq -e '.dimensions | all(.key and (.weight|type=="number") and (.weight|floor==.) and .weight>0 and (.desc|length>0))' "$f" >/dev/null \
    || { echo "FAIL: $name has a malformed dimension"; exit 1; }
  jq -e '(.dimensions|map(.key)|unique|length) == (.dimensions|length)' "$f" >/dev/null \
    || { echo "FAIL: $name has duplicate dimension keys"; exit 1; }
done

[[ "$n" -ge 1 ]] || { echo "FAIL: no rubrics found"; exit 1; }
echo "ok: $n rubric(s) valid"
