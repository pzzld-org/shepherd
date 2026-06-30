#!/usr/bin/env bash
# hooks/tests/test_flock_output_review.sh — wiring guard for the FLOCK-OUTPUT
# REVIEW gate + REDO loop (v6.2.4, #167).
#
# WHY: the gate is behavioral wiring spread across a doctrine + four profiles +
# the invariant matrix. No single hook enforces it at the tool layer, so the
# regression risk is a future edit silently deleting one leg (the mandatory
# review, the redo cap, the root delegation) and leaving the feature half-wired.
# This test pins every load-bearing reference so a drop fails the gate lane.
# It checks presence of the contract, not prose — deterministic, free, <1s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fails=0

# need_file <path> — the path must exist.
need_file() {
  if [[ ! -f "$1" ]]; then
    printf '  FAIL  missing file: %s\n' "$1"
    fails=$((fails+1))
  fi
}

# need <file> <fixed-string> <why> — the fixed string must appear in the file.
need() {
  if ! grep -qF -- "$2" "$1" 2>/dev/null; then
    printf '  FAIL  %s — %s missing %q\n' "$3" "$1" "$2"
    fails=$((fails+1))
  fi
}

DOC="skills/shepherd/doctrines/flock-output-review.md"

# 1. The doctrine — the single source of truth — exists.
need_file "$DOC"

# 2. conductor.md wires the gate, the redo loop, and the cap halt code.
need agents/conductor.md "flock-output-review.md"   "conductor cites doctrine"
need agents/conductor.md "FLOCK-OUTPUT REVIEW"       "conductor gate name"
need agents/conductor.md "wave-review mode"          "conductor reviewer mode"
need agents/conductor.md "REDO loop"                 "conductor redo loop"
need agents/conductor.md "REDO-CAP-EXCEEDED"         "conductor redo cap halt code"

# 3. shepherd.md (root) delegates the verdict and forces redo through the teammate.
need agents/shepherd.md  "flock-output-review.md"    "root cites doctrine"
need agents/shepherd.md  "REDO-DIRECTIVE"            "root redo directive"
need agents/shepherd.md  "review_verdict"            "root review-evidence gate"
need agents/shepherd.md  "REDO-CAP-EXCEEDED"         "root redo cap halt code"

# 4. auditor.md carries the wave-review mode and its verdict shape.
need agents/auditor.md   "wave-review"               "auditor wave-review mode"
need agents/auditor.md   "WAVE-REVIEW VERDICT"       "auditor verdict block"
need agents/auditor.md   "flock-output-review.md"    "auditor cites doctrine"

# 4-bis. The wave-review report path MUST keep the `audit-` prefix so it stays
# inside lock_guard.sh's @auditor write-allow regex (/<date>-(intro-)?audit-.+\.md$).
# A rename that drops `audit-` would hard-block the wave-review auditor's Write.
if ! grep -qF -- '{paths.reports}/<date>-audit-wave-review-' agents/auditor.md; then
  printf '  FAIL  wave-review report path lacks the audit- prefix — lock_guard.sh would block it\n'
  fails=$((fails+1))
fi

# 5. flock.md dispatch reference carries the mandatory per-wave review.
need skills/shepherd/flock.md "wave-review"          "flock dispatch ref mode"
need skills/shepherd/flock.md "flock-output-review.md" "flock cites doctrine"

# 6. The invariant matrix records the enforcement coverage.
need skills/shepherd/doctrines/invariant-enforcement-matrix.md \
     "flock-output-review.md" "invariant matrix coverage row"

# 7. Citation resolution — every doctrines/<x>.md referenced inside the new
#    doctrine must exist (no dangling cross-references).
if [[ -f "$DOC" ]]; then
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    if [[ ! -f "skills/shepherd/doctrines/$ref" ]]; then
      printf '  FAIL  dangling citation in %s: doctrines/%s\n' "$DOC" "$ref"
      fails=$((fails+1))
    fi
  done < <(grep -oE 'doctrines/[a-z0-9-]+\.md' "$DOC" | sed 's#doctrines/##' | sort -u)
fi

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d flock-output-review wiring assertion(s) failed\n' "$fails" >&2
  exit 1
fi

printf '  PASS  flock-output-review gate + redo loop fully wired (#167)\n'
