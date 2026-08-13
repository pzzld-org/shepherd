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
# Inverse of `need`: assert a REGEX has no match. Regex, not fixed-string, so a
# rule can be denied by whole-line anchor while prose mentioning it still passes.
deny() { grep -qE -- "$2" "$1" 2>/dev/null && { printf '  FAIL  %s — %s still matches %q\n' "$3" "$1" "$2"; fails=$((fails+1)); }; true; }

DOC="skills/shepherd/references/pipeline.md"
MM="skills/context/references/model-map.md"
WP="skills/context/SKILL.md"

# 1. The three doctrines exist.
need_file "$DOC"; need_file "$MM"; need_file "$WP"

# 2. (A) engineer self-contained + critic-proof wiring (clarified v6.2.6, #172).
need agents/engineer.md "references/pipeline.md §INTRO" "engineer cites INTRO contract"
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
need agents/engineer.md 'NEVER `@coder`'                 "engineer sub-flock is read-only (no code)"
if ! grep -qiE 'never .*@engineer|no nested/phantom engineer' agents/engineer.md; then
  printf '  FAIL  engineer.md — missing the no-nested/phantom-engineer prohibition\n'; fails=$((fails+1))
fi
# The mechanical topology + marker guards live in dispatch_guard.sh.
need hooks/scripts/dispatch_guard.sh "ENGINEER-TOPOLOGY-MISMATCH" "guard: self-contained-as-subagent block"
need hooks/scripts/dispatch_guard.sh "engineer-self-contained"    "guard: @critic self-gate marker"
need agents/shepherd.md  "references/pipeline.md §INTRO"   "root cites INTRO contract"
need agents/shepherd.md  "shctx plan verify"               "root thin acceptance gate"
need agents/shepherd.md  "CRITIC-PROOF-MISSING"            "root critic-proof halt code"
need agents/shepherd.md  "PLAN-UNEDITED"                   "root unedited halt code"
need skills/shepherd/references/flock.md "ENGINEER-SUBFLOCK-VIOLATION" "flock sub-flock guard"
need skills/shepherd/references/flock.md "critic-proof"               "flock critic-proof"
need skills/shepherd/references/invariant-matrix.md \
     "engineer-self-contained" "invariant matrix coverage row"

# 3. (B) model-map wiring.
need agents/shepherd.md   "model-map.md"                  "root cites model-map"
need agents/shepherd.md   "shctx models resolve"          "root resolves model from map"
need agents/conductor.md  "model-map.md"                  "conductor cites model-map"
need agents/conductor.md  "shctx models resolve"          "conductor resolves model from map"
need commands/spawn.md    "shctx models resolve conductor" "spawn resolves conductor model"
need .shepherd/shepherd.toml "[models]"                    "dogfood [models] block"

# 4. (C) workdir-prune wiring.
# v6.4.5: canonical live config moved to .shepherd/shepherd.toml
# (docs/configuration.md#config-resolution); .claude/shepherd.toml is the
# legacy fallback tier, still honored, but this dogfood project's real
# binding lives at the canonical path — assert against that, not the tier
# this project no longer uses.
need .shepherd/shepherd.toml "[prune]"        "dogfood [prune] block"
# v6.4.4: memory/ is RETIRED, and is deliberately NOT gitignored any more —
# ignoring it is what made it a silent knowledge sink. Assert the INVERSE: no
# memory/ ignore rule may come back, and the retirement is documented.
deny .gitignore "^\\.artifacts/memory/$"   "no .artifacts/memory ignore rule (retired)"
deny .gitignore "^\\.shepherd/memory/$"    "no .shepherd/memory ignore rule (retired)"
need .gitignore "is RETIRED (v6.4.4)"       "gitignore explains the memory/ retirement"

# 5. shctx registers the new subcommands + carries the critic-proof verbs.
need skills/context/scripts/shctx "|models|prune)"  "shctx dispatcher registers models+prune"
need skills/context/scripts/cmd_plan.sh "record-critique" "cmd_plan record-critique verb"
need skills/context/scripts/cmd_plan.sh "verify"          "cmd_plan verify verb"

# 6. Citation lint: the doctrine dir is dissolved (v6.2.8) — no plugin-doctrine
# path may survive anywhere in the contract files. The only legal doctrines/
# form is the consumer-project extension dir `.claude/doctrines/`.
for d in "$DOC" "$MM" "$WP" agents/engineer.md agents/shepherd.md; do
  [[ -f "$d" ]] || continue
  while IFS= read -r hit; do
    [[ -n "$hit" ]] || continue
    printf '  FAIL  stale plugin-doctrine citation in %s: %s\n' "$d" "$hit"
    fails=$((fails+1))
  done < <(grep -oE '(^|[^a-z./])doctrines/[a-z0-9-]+\.md' "$d" | grep -v '\.claude/doctrines/' | sort -u)
done

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d v6.2.5 wiring assertion(s) failed\n' "$fails" >&2
  exit 1
fi
printf '  PASS  v6.2.5 wiring — engineer self-contained + critic-proof (#169), model map (#170), workdir prune (#171)\n'
