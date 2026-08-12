#!/usr/bin/env bash
# hooks/tests/test_v644_wiring.sh — v6.4.4 doctrine wiring guard.
#
# v6.4.4 is behavioral wiring spread across doctrine + CLI + hooks + scripts,
# with no single tool-layer enforcer. This pins every load-bearing citation so
# a later edit that silently drops a leg fails the gate lane rather than
# shipping a contract that reads correct and enforces nothing.
#
#   (A) #270 — the Agent() completion notification does not arrive; the poll IS
#       the signal, and worktree state is ground truth for a coder.
#   (B) #269 — plan.md/vars.json drift is a wave-boundary gate, and the
#       conductor is told vars.json exists at all.
#   (C) #268 — root has a sanctioned mid-sprint amendment path.
#   (D) #269b — the plugin's helper scripts are cited plugin-root-relative; a
#       bare relative path resolves against the CONSUMER project, where the
#       file does not exist, so the guard measures nothing while reading as
#       though it passed.
#   (E) layout — one knowledge silo, and run-scoped artifacts stay in the run.
#
# Presence of the contract, not prose — deterministic, free, <1s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fails=0
need() { grep -qF -- "$2" "$1" 2>/dev/null || { printf '  FAIL  %s — %s missing %q\n' "$3" "$1" "$2"; fails=$((fails+1)); }; }
deny() { grep -qE -- "$2" "$1" 2>/dev/null && { printf '  FAIL  %s — %s still matches %q\n' "$3" "$1" "$2"; fails=$((fails+1)); }; true; }

# --- (A) #270 defensive poll ------------------------------------------------
need agents/conductor.md "#270"                          "conductor cites #270"
need agents/conductor.md "treat it as absent, not as late" "notification treated as absent, not late"
need agents/conductor.md "status --porcelain"            "worktree poll: git status --porcelain"
need agents/conductor.md "diff --shortstat"              "worktree poll: git diff --shortstat"
need agents/conductor.md "had no active task"            "SendMessage reply recorded as a completion signal"
need skills/shepherd/references/wave-routine.md "#270"   "wave-routine cites #270"
need skills/shepherd/references/invariant-matrix.md "#270" "invariant matrix carries the #270 row"

# --- (B) #269 lane drift ----------------------------------------------------
need agents/conductor.md "vars.json"                     "conductor is told vars.json exists"
need agents/conductor.md "shepherd plan lane-drift"      "conductor runs lane-drift after a correction"
need skills/shepherd/references/wave-routine.md "plan lane-drift" "lane-drift is a wave-boundary gate"
need services/cli/shepherd_cli/commands/plan.py "lane-drift" "CLI implements lane-drift"

# --- (C) #268 plan amend ----------------------------------------------------
need agents/shepherd.md "shctx plan amend"               "root has the sanctioned amendment path"
need agents/shepherd.md "NEVER hand-forge the proof"     "root is told not to forge the proof"
need services/cli/shepherd_cli/commands/plan.py "_cmd_amend" "CLI implements amend"

# --- (D) #269b plugin-root-relative helper scripts --------------------------
# A bare `scripts/<helper>` in doctrine is the defect: it resolves against the
# consumer project. Every citation must carry ${CLAUDE_PLUGIN_ROOT}.
for f in agents/coder.md agents/auditor.md agents/conductor.md agents/shepherd.md \
         commands/start.md skills/shepherd/references/wave-routine.md \
         skills/shepherd/references/pipeline.md \
         skills/shepherd/references/invariant-matrix.md \
         skills/harness/references/workflow-templates.md; do
  # Skip lines that DOCUMENT the rule — wave-routine.md quotes the bad form
  # verbatim ("a bare `scripts/df-guard.sh`") to explain why the prefix is
  # load-bearing, and a naive scan would flag the explanation as the defect.
  if grep -vE '\bbare `' "$f" \
     | grep -qE '(^|[^/{])scripts/(df-guard\.sh|loc-count\.py|journal-status\.sh|team-preflight\.sh)'; then
    printf '  FAIL  unqualified helper-script path in %s\n' "$f"
    fails=$((fails+1))
  fi
done

# --- (E) layout: one silo, run-scoped artifacts in the run ------------------
need skills/context/references/naming-conventions.md "One knowledge silo" "artifact schema documents the one-silo rule"
need skills/context/references/naming-conventions.md "vs \`{run_dir}\` boundary" "artifact schema documents the docs/run boundary"
need agents/auditor.md "{run_dir}/audits/"               "auditor writes run-scoped audits"
need agents/discovery.md "{run_dir}/reports/"            "discovery writes run-scoped reports"
need agents/worker.md "{run_dir}/reports/"               "worker writes run-scoped reports"
need hooks/scripts/lock_guard.sh "/runs/[^/]+/audits/"   "lock_guard enforces the run-scoped audit path"
need hooks/scripts/lock_guard.sh "/runs/[^/]+/reports/"  "lock_guard enforces the run-scoped report path"
# NOT a `deny` on the retired path: prune deliberately still SWEEPS
# memory/snapshots (an un-migrated project's snapshots must stay under
# retention), so its absence would be wrong. The property that matters is that
# cache/ is the CANONICAL entry and comes first — retention is applied over the
# union in that order.
need services/cli/shepherd_cli/commands/prune.py '("cache", "snapshots"),   # canonical' "prune's canonical snapshot dir is cache/"
need services/cli/shepherd_cli/commands/prune.py '("memory", "snapshots"),  # retired'   "prune still sweeps the retired memory/ dir"
need skills/context/scripts/cmd_prune.sh 'wd/cache/snapshots'                             "bash prune sweeps cache/snapshots first"

if [[ "$fails" -eq 0 ]]; then
  printf '  PASS  v6.4.4 wiring — #268 amend, #269 lane-drift + script paths, #270 defensive poll, layout\n'
else
  printf '  FAIL  v6.4.4 wiring — %d missing leg(s)\n' "$fails"
fi
exit "$fails"
