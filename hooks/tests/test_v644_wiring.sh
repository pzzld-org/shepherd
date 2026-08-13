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
# DF-19 (v6.4.5): the original cut of this gate asserted every leg with a
# single grep-for-a-phrase helper. That proves the DOCTRINE STILL SAYS THE
# WORDS; it proves nothing about whether the words are still true. Measured
# live on this branch: the doctrine literally instructs root to run
# `shctx plan amend`, and that exact command errors "unknown subcommand:
# amend" today — the string check could not see it because "shctx plan
# amend" is genuinely present in agents/shepherd.md; only an invocation
# reveals it doesn't work. Every assertion below is now one of two honest
# things:
#   - a REAL invocation of the documented command/mechanism, asserted on its
#     actual exit code / output, OR
#   - an explicit `cite()` call under an `UNVERIFIABLE-IN-TEST` comment, for
#     the minority of claims that describe a live-session/async platform
#     behavior (or state a doctrine convention with no invokable enforcement
#     mechanism) that a bash harness cannot trigger. Kept as a doc-regression
#     tripwire, never mistaken for proof the behavior happens.
#
# Deterministic, no network, no LLM, <2s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fails=0

# cite(file, string, label) — UNVERIFIABLE-IN-TEST doc-citation tripwire ONLY.
# Never used to claim a behavior was proven; every call site sits directly
# under a comment stating why the claim cannot be invoked.
cite() { grep -qF -- "$2" "$1" 2>/dev/null || { printf '  FAIL  %s — %s missing %q\n' "$3" "$1" "$2"; fails=$((fails+1)); }; }

# --- (A) #270 defensive poll -------------------------------------------------
# The only half of #270 a bash process can exercise is the FALLBACK MECHANISM
# itself: do `git status --porcelain` / `git diff --shortstat` really observe
# an uncommitted worktree change? Build a throwaway repo and prove it.
_git_poll_check() {
  local tmp porcelain shortstat
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  git -C "$tmp" init -q .
  git -C "$tmp" config user.email t@t
  git -C "$tmp" config user.name t
  printf 'v1\n' >"$tmp/f.txt"
  git -C "$tmp" add f.txt
  git -C "$tmp" -c commit.gpgsign=false commit -q -m init
  printf 'v2 changed\n' >>"$tmp/f.txt"
  porcelain="$(git -C "$tmp" status --porcelain)"
  shortstat="$(git -C "$tmp" diff --shortstat)"
  if [[ -n "$porcelain" ]]; then
    printf '  PASS  #270 — git status --porcelain detects a real uncommitted change\n'
  else
    printf '  FAIL  #270 — git status --porcelain reported nothing for a real uncommitted file\n'
    fails=$((fails+1))
  fi
  if [[ -n "$shortstat" ]]; then
    printf '  PASS  #270 — git diff --shortstat reports the real change size\n'
  else
    printf '  FAIL  #270 — git diff --shortstat reported nothing for a real modified file\n'
    fails=$((fails+1))
  fi
}
_git_poll_check

# UNVERIFIABLE-IN-TEST: whether the Agent() SDK's completion notification
# ever arrives, and how root/conductor is told to read a `SendMessage` reply,
# are live-session platform behaviors — no bash process can trigger an
# Agent() dispatch or a teammate reply. Kept as doc-regression tripwires only.
for f in agents/conductor.md skills/shepherd/references/wave-routine.md \
         skills/shepherd/references/invariant-matrix.md; do
  cite "$f" "#270" "$f cites #270"
done
cite agents/conductor.md "treat it as absent, not as late" "notification treated as absent, not late"
cite agents/conductor.md "had no active task" "SendMessage reply documented as a completion signal"

# --- (B) #269 lane drift -----------------------------------------------------
# The conductor's documented recovery command, invoked for real. A success
# message of "lane(s) agree (plan.md == vars.json)" only prints after the CLI
# actually located and compared vars.json, so this one real invocation proves
# three original claims at once: vars.json genuinely exists as a materialized
# artifact, the documented recovery command genuinely works, and the CLI
# genuinely implements lane-drift end to end (not just a "lane-drift" string
# in the source).
if ( shepherd plan lane-drift v645 ; test $? -eq 0 ) >/dev/null 2>&1; then
  printf '  PASS  #269 — shepherd plan lane-drift v645 exits 0 (vars.json located, CLI wired)\n'
else
  printf '  FAIL  #269 — shepherd plan lane-drift v645 did not exit 0\n'
  fails=$((fails+1))
fi

# UNVERIFIABLE-IN-TEST: "lane-drift is a wave-boundary gate" is a claim about
# WHEN in a live sprint the conductor invokes the command above, not an
# artifact a bash harness can observe — the invocation itself is proven real
# by the check just above.
cite skills/shepherd/references/wave-routine.md "plan lane-drift" "wave-routine cites plan lane-drift"

# --- (C) #268 plan amend -----------------------------------------------------
# agents/shepherd.md instructs root to run `shctx plan amend --plan <path>
# --reason "..."` verbatim. Invoke it for real, with NO real args (this must
# never touch the live sprint's actual plan.md/critic-proof) — a genuinely
# wired subcommand fails on ITS OWN argument validation, never with
# "unknown subcommand".
amend_bash_out="$(shctx plan amend 2>&1)" || true
if printf '%s' "$amend_bash_out" | grep -q 'unknown subcommand: amend'; then
  printf '  FAIL  #268 — shctx plan amend is documented in agents/shepherd.md but NOT wired: %s\n' \
    "$(printf '%s' "$amend_bash_out" | head -1)"
  fails=$((fails+1))
else
  printf '  PASS  #268 — shctx plan amend is CLI-reachable\n'
fi

# The Python CLI's own amend implementation, invoked the same way — this is
# what agents/shepherd.md's "_cmd_amend" claim is actually about underneath
# the `shctx` wrapper.
amend_py_out="$(shepherd plan amend 2>&1)" || true
if printf '%s' "$amend_py_out" | grep -qE 'unknown subcommand|not yet implemented'; then
  printf '  FAIL  #268 — shepherd plan amend (_cmd_amend) is unreachable: %s\n' \
    "$(printf '%s' "$amend_py_out" | head -1)"
  fails=$((fails+1))
else
  printf '  PASS  #268 — the CLI implements amend (rejects on its own --plan validation, not on dispatch)\n'
fi

# UNVERIFIABLE-IN-TEST: "NEVER hand-forge the proof" is a judgment warning
# aimed at root's future behavior, not a mechanism a bash harness can trigger
# or withhold.
cite agents/shepherd.md "NEVER hand-forge the proof" "root is told not to forge the proof"

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
# The two enforceable claims here — @discovery/@auditor may only write into
# {run_dir}/reports|audits/ — have a dedicated live behavior gate already:
# hooks/tests/test_lock_guard_write_path.sh builds a scratch repo, feeds
# lock_guard.sh real PreToolUse payloads per role, and asserts allow/deny.
# Run it for real instead of re-grepping the regex it exercises.
lockguard_test="$ROOT/hooks/tests/test_lock_guard_write_path.sh"
if bash "$lockguard_test" >/dev/null 2>&1; then
  printf '  PASS  layout — run-scoped audit/discovery write paths enforced (%s)\n' "$lockguard_test"
else
  printf '  FAIL  layout — %s did not pass; run-scoped write-path enforcement is broken\n' "$lockguard_test"
  fails=$((fails+1))
fi

# UNVERIFIABLE-IN-TEST: worker.md's "{run_dir}/reports/" claim has NO
# invokable enforcement to exercise — lock_guard.sh's own header says so
# explicitly ("conductor / engineer / critic / worker / unknown — no
# write-path constraint at hook layer"). Unlike discovery/auditor above, this
# is a pure, mechanically-unenforced doctrine convention.
cite agents/worker.md "{run_dir}/reports/" "worker.md documents (unenforced) run-scoped reports"

# UNVERIFIABLE-IN-TEST: "one knowledge silo" / "docs vs run_dir boundary" are
# the CONVENTION naming-conventions.md documents; its enforcement is the real
# behavior check above (and prune's order check below), not a fact this
# citation itself can execute.
cite skills/context/references/naming-conventions.md "One knowledge silo" "naming-conventions documents the one-silo rule"
# shellcheck disable=SC2016  # literal backticks in the search string, not expansion
cite skills/context/references/naming-conventions.md 'vs `{run_dir}` boundary' "naming-conventions documents the docs/run boundary"

# UNVERIFIABLE-IN-TEST: canonical-vs-retired snapshot sweep ORDER is a source-
# level invariant (a literal tuple/array order), not something a wiring gate
# may exercise live — doing so would require `prune --confirm` against the
# ACTIVE sprint's real .shepherd workdir, which this test must never mutate.
# Checked directly against the constant that drives the order instead.
cite services/cli/shepherd_cli/commands/prune.py '("cache", "snapshots"),   # canonical' "prune's canonical snapshot dir is cache/"
cite services/cli/shepherd_cli/commands/prune.py '("memory", "snapshots"),  # retired'   "prune still sweeps the retired memory/ dir"
cite skills/context/scripts/cmd_prune.sh 'wd/cache/snapshots' "bash prune sweeps cache/snapshots first"

if [[ "$fails" -eq 0 ]]; then
  printf '  PASS  v6.4.4 wiring — #268 amend, #269 lane-drift + script paths, #270 defensive poll, layout\n'
else
  printf '  FAIL  v6.4.4 wiring — %d missing leg(s)\n' "$fails"
fi
exit "$fails"
