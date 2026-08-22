#!/usr/bin/env bash
set -eu -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EVALS="$HERE/../evals"

for path in \
  "$EVALS/cases/pi-bootstrap_good.txt" \
  "$EVALS/cases/pi-bootstrap_bad.txt" \
  "$HERE/../rubrics/pi-bootstrap.rubric.json"; do
  [[ -s "$path" ]] || { echo "FAIL: missing Pi bootstrap eval artifact: $path"; exit 1; }
done

grep -Fq '_pair pi-bootstrap pi-bootstrap_good.txt pi-bootstrap_bad.txt' "$EVALS/run_eval.sh" \
  || { echo 'FAIL: periodic eval does not run the Pi bootstrap pair'; exit 1; }
grep -Fq 'seven' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not require seven provider-visible roles'; exit 1; }
grep -Fq 'getAllTools' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not require public generic provider readiness'; exit 1; }
grep -Fq 'exact terminal correlation' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not keep terminal lockout behind exact correlation'; exit 1; }
grep -Fq 'Luna at max' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not require explicit Luna max fanout'; exit 1; }
grep -Fq 'Sol at xhigh' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not require explicit Sol xhigh leads'; exit 1; }
grep -Fq 'including reasoning-high engineer and conductor carriers' "$EVALS/cases/pi-bootstrap_good.txt" \
  || { echo 'FAIL: good case does not require sentinels for project-neutral reasoning leads'; exit 1; }
grep -Fq 'silently inherit the expensive parent/default' "$EVALS/cases/pi-bootstrap_bad.txt" \
  || { echo 'FAIL: bad case does not reject expensive silent inheritance'; exit 1; }
grep -Fqi 'hand-copy' "$EVALS/cases/pi-bootstrap_bad.txt" \
  || { echo 'FAIL: bad case does not cover duplicate generated role authority'; exit 1; }
grep -Fq 'active tools' "$EVALS/cases/pi-bootstrap_bad.txt" \
  || { echo 'FAIL: bad case does not reject active-only provider probing'; exit 1; }

printf 'ok: Pi bootstrap periodic eval pair is wired\n'
