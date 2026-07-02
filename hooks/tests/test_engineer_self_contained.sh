#!/usr/bin/env bash
# hooks/tests/test_engineer_self_contained.sh — v6.2.5 wiring guard.
#
# v6.2.5 is behavioral wiring spread across three new doctrines + profiles + the
# CLI + the invariant matrix, with no single tool-layer enforcer:
#   (A) engineer self-contained plan + hash-tied critic-proof (#169)
#   (B) the [models] per-role model map (#170)
#   (C) workdir prune (#171)
# This pins every load-bearing reference so a future edit that silently drops a
# leg (a citation, a CLI verb, a config block, the Agent scope bound) fails the
# gate lane. Presence of the contract, not prose — deterministic, free, <1s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fails=0
need_file() { [[ -f "$1" ]] || { printf '  FAIL  missing file: %s\n' "$1"; fails=$((fails+1)); }; }
need() { grep -qF -- "$2" "$1" 2>/dev/null || { printf '  FAIL  %s — %s missing %q\n' "$3" "$1" "$2"; fails=$((fails+1)); }; }

DOC="skills/shepherd/doctrines/engineer-self-contained-plan.md"
MM="skills/shepherd/doctrines/model-map.md"
WP="skills/shepherd/doctrines/workdir-prune.md"

# 1. The three doctrines exist.
need_file "$DOC"; need_file "$MM"; need_file "$WP"

# 2. (A) engineer self-contained + critic-proof wiring (clarified v6.2.6, #172).
need agents/engineer.md "engineer-self-contained-plan.md" "engineer cites doctrine"
need agents/engineer.md "self-contained"                  "engineer self-contained mode"
need agents/engineer.md "shctx plan record-critique"      "engineer records critic-proof"
if ! grep -qE '^tools:.*(^|[, ])Agent([, ]|$)' agents/engineer.md; then
  printf '  FAIL  engineer.md tools: lacks Agent (self-contained sub-flock dispatch)\n'; fails=$((fails+1))
fi
# The read-only sub-flock scope = {discovery, auditor, critic} — all three tokens.
need agents/engineer.md "shepherd:discovery"              "engineer sub-flock: discovery"
need agents/engineer.md "shepherd:auditor"               "engineer sub-flock: auditor (intro wave)"
need agents/engineer.md "shepherd:critic"                "engineer sub-flock: critic (self-gate)"
# Clarified contract: real @critic dispatch tagged with the self-gate marker;
# hard mode determination; named-teammate topology; no nested/phantom engineer.
need agents/engineer.md "engineer-self-contained"        "engineer @critic self-gate marker"
need agents/engineer.md "named teammate"                 "engineer named-teammate topology"
need agents/engineer.md "no code"                        "engineer sub-flock is read-only (no code)"
if ! grep -qiE 'never .*@engineer|no nested/phantom engineer' agents/engineer.md; then
  printf '  FAIL  engineer.md — missing the no-nested/phantom-engineer prohibition\n'; fails=$((fails+1))
fi
# The mechanical topology + marker guards live in dispatch_guard.sh.
need hooks/scripts/dispatch_guard.sh "ENGINEER-TOPOLOGY-MISMATCH" "guard: self-contained-as-subagent block"
need hooks/scripts/dispatch_guard.sh "engineer-self-contained"    "guard: @critic self-gate marker"
need agents/shepherd.md  "engineer-self-contained-plan.md" "root cites doctrine"
need agents/shepherd.md  "shctx plan verify"               "root thin acceptance gate"
need agents/shepherd.md  "CRITIC-PROOF-MISSING"            "root critic-proof halt code"
need agents/shepherd.md  "PLAN-UNEDITED"                   "root unedited halt code"
need skills/shepherd/flock.md "engineer-self-contained-plan.md" "flock cites doctrine"
need skills/shepherd/flock.md "critic-proof"                    "flock critic-proof"
need skills/shepherd/doctrines/invariant-enforcement-matrix.md \
     "engineer-self-contained-plan.md" "invariant matrix coverage row"

# 3. (B) model-map wiring.
need agents/shepherd.md   "model-map.md"                  "root cites model-map"
need agents/shepherd.md   "shctx models resolve"          "root resolves model from map"
need agents/conductor.md  "model-map.md"                  "conductor cites model-map"
need agents/conductor.md  "shctx models resolve"          "conductor resolves model from map"
need commands/spawn.md    "shctx models resolve conductor" "spawn resolves conductor model"
need .claude/shepherd.toml "[models]"                     "dogfood [models] block"

# 4. (C) workdir-prune wiring.
need .claude/shepherd.toml "[prune]"          "dogfood [prune] block"
need .gitignore ".artifacts/memory/"          "gitignore .artifacts/memory leak fix"
need .gitignore ".shepherd/memory/"           "gitignore .shepherd/memory leak fix"

# 5. shctx registers the new subcommands + carries the critic-proof verbs.
need skills/context/scripts/shctx "|models|prune)"  "shctx dispatcher registers models+prune"
need skills/context/scripts/cmd_plan.sh "record-critique" "cmd_plan record-critique verb"
need skills/context/scripts/cmd_plan.sh "verify"          "cmd_plan verify verb"

# 6. Dangling-citation resolution across all three new doctrines.
for d in "$DOC" "$MM" "$WP"; do
  [[ -f "$d" ]] || continue
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    if [[ ! -f "skills/shepherd/doctrines/$ref" ]]; then
      printf '  FAIL  dangling citation in %s: doctrines/%s\n' "$d" "$ref"
      fails=$((fails+1))
    fi
  done < <(grep -oE 'doctrines/[a-z0-9-]+\.md' "$d" | sed 's#doctrines/##' | sort -u)
done

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d v6.2.5 wiring assertion(s) failed\n' "$fails" >&2
  exit 1
fi
printf '  PASS  v6.2.5 wiring — engineer self-contained + critic-proof (#169), model map (#170), workdir prune (#171)\n'
