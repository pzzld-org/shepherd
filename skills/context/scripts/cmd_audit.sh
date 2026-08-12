#!/usr/bin/env bash
# shctx audit — read-only validation pipeline (v5.0.4)
#
#   lint  →  doctor  →  status
#
# No writes. Used by the conductor as a pre-dispatch sanity check, and
# by CI for "is this project's context registry healthy?".
#
# v5.1.7+: also exposes `insert` subverb that writes a structured row into
# audit_findings (see skills/context/SKILL.md).
# Reading body from stdin keeps the legacy flag-parsing path untouched.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# ---------------------------------------------------------------------------
# v5.1.7+ insert subverb — must be checked BEFORE the legacy flag loop so
# `shctx audit insert ...` does not get parsed by the validation-pipeline path.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "insert" ]]; then
  shift
  concern=""; severity=""; hypothesis=""; falsification=""; confidence=""
  evidence=""; gh=""; sprint=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --concern=*)       concern="${1#*=}";;
    --severity=*)      severity="${1#*=}";;
    --hypothesis=*)    hypothesis="${1#*=}";;
    --falsification=*) falsification="${1#*=}";;
    --confidence=*)    confidence="${1#*=}";;
    --evidence=*)      evidence="${1#*=}";;
    --gh-issue=*)      gh="${1#*=}";;
    --sprint=*)        sprint="${1#*=}";;
    *) echo "unknown flag: $1" >&2; exit 2;;
  esac; shift; done
  [[ -n "$concern" && -n "$severity" && -n "$hypothesis" ]] \
    || { echo "ERR: --concern, --severity, --hypothesis required" >&2; exit 2; }
  finding="$(cat)"
  if [[ -n "$evidence" ]]; then
    echo "$evidence" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' \
      >/dev/null 2>&1 || evidence=""
  fi
  DB="${SHCTX_DB:-$(shctx_db_path)}"
  [[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
  pid="$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")"
  ts=$(($(date +%s) * 1000))
  safe_hyp="${hypothesis//\'/''}"; safe_fal="${falsification//\'/''}"
  safe_fin="${finding//\'/''}"; safe_ev="${evidence//\'/''}"
  safe_sp="${sprint//\'/''}"
  id=$(sqlite3 "$DB" "INSERT INTO audit_findings (project_id, sprint_branch, concern, severity, hypothesis, falsification, confidence, finding, evidence_refs, gh_issue, created_at) VALUES ('$pid', NULLIF('$safe_sp',''), '$concern', '$severity', '$safe_hyp', NULLIF('$safe_fal',''), NULLIF('$confidence',''), '$safe_fin', NULLIF('$safe_ev',''), NULLIF('$gh',''), $ts) RETURNING id;")
  echo "$id"
  exit 0
fi

verbose=0
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) verbose=1 ;;
    -h|--help)
      cat <<'EOF'
shctx audit [--verbose]
shctx audit insert --concern=<c> --severity=<s> --hypothesis=<h>
                   [--falsification=<f>] [--confidence=<low|medium|high>]
                   [--evidence=<json>] [--gh-issue=<n>] [--sprint=<branch>]
                   < finding-body.md

Read-only validation: lint → doctor → status.
Exits 0 if all green, 1 if any FAIL, 2 if only WARNs (matches doctor).

v5.1.7+: `insert` subverb writes a structured row into audit_findings.
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

run_stage() {
  local name="$1"; shift
  if (( verbose )); then echo "─── $name ───"; "$@"
  else "$@" >/dev/null 2>&1 || return $?
  fi
}

rc_lint=0; rc_doctor=0; rc_status=0
run_stage lint   bash "$HERE/cmd_lint.sh"   || rc_lint=$?
bash "$HERE/cmd_doctor.sh" >/dev/null 2>&1 || rc_doctor=$?
run_stage status bash "$HERE/cmd_status.sh" || rc_status=$?

# Always print doctor at end (it's the user-relevant signal).
bash "$HERE/cmd_doctor.sh"

echo
echo "shctx audit:"
echo "  lint:   $([[ $rc_lint   -eq 0 ]] && echo ok || echo "fail (rc=$rc_lint)")"
echo "  doctor: $([[ $rc_doctor -eq 0 ]] && echo ok || ([[ $rc_doctor -eq 2 ]] && echo "warn" || echo "fail (rc=$rc_doctor)"))"
echo "  status: $([[ $rc_status -eq 0 ]] && echo ok || echo "fail (rc=$rc_status)")"

if (( rc_lint != 0 || rc_doctor == 1 || rc_status != 0 )); then exit 1; fi
if (( rc_doctor == 2 )); then exit 2; fi
exit 0
