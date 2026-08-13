#!/usr/bin/env bash
# shepherd hook — PreToolUse(Write|Edit) critic-proof integrity guard (DF-22, v6.4.5).
#
# THE DEFECT (lived, not hypothetical — v645 plan.md itself): an engineer runs
# `shctx plan record-critique`, which hash-ties `<slug>.critic-proof.json` to
# the plan's bytes at that instant. Nothing stops the SAME engineer from
# editing the plan again immediately after — in good faith, because the write
# succeeds and a `shctx plan verify` run right after also succeeds (verify
# only checks hash-at-verify-time, not "has anything changed since"). The
# proof silently goes stale. The only thing that ever catches it is someone,
# possibly hours later and in a different role, remembering to run
# `shctx plan verify` by hand before trusting the plan. This hook moves that
# check to the ONLY place a silent invalidation can be prevented instead of
# merely detected: the Write/Edit call that is about to cause it.
#
# Decision: does `shctx plan verify --plan <file> --quiet` CURRENTLY pass
# (exit 0) for the target file? If so, the plan carries a VALID, hash-tied
# attestation — the write is refused. Any other outcome (no proof, already
# stale, unedited, uncritiqued, or the CLI itself unavailable) fails OPEN:
# this guard protects a valid attestation, it never gates ordinary authorship
# of a plan that has none. Reuses `shctx plan verify` rather than
# re-implementing its hash/schema logic here, so the guard can never drift
# from the single source of truth in services/cli/shepherd_cli/commands/plan.py.
#
# Scope: PreToolUse(Write|Edit), gated further to files whose basename is
# `plan.md` (run-scoped: `.shepherd/runs/<run>/plan.md`,
# `.shepherd/runs/<run>/lanes/<lane>/plan.md`) or matches the legacy
# `<slug>.plan.md` convention. A lane plan is a `plan.md` too but is
# CONDUCTOR-rendered and never gains a critic-proof sidecar, so it always
# reads CRITIC-PROOF-MISSING here and is left untouched — no special-casing
# needed to keep the conductor's own lane-plan writes unobstructed.
#
# Recovery is deliberately NOT automatic (see NON-GOALS in the step brief):
# re-recording the proof on the guard's own initiative would forge an
# attestation the critic never made. The deny message names the two
# SANCTIONED existing verbs instead: a fresh `record-critique` after a real
# re-critique, or root's `amend` (#268) for a sanctioned mid-sprint
# correction — never a silent rewrite of the sidecar.
#
# `--self-test`: negative-control mode (see check-workspace.sh's own
# `--self-test` convention) — builds a real plan+proof fixture through the
# actual CLI and asserts the SAME decision function used at hook time denies
# it, rather than asserting on hand-authored prose.
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.{file_path|path}, ... }
# Output (stdout): {"permissionDecision":"deny","message":"..."} | nothing.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
shctx="$plugin_root/bin/shepherd"

# True if $1's basename/segment shape is a plan file this guard cares about.
_is_plan_path() {
  case "$1" in
    */plan.md|plan.md|*.plan.md) return 0 ;;
    *) return 1 ;;
  esac
}

# True (exit 0) iff `shctx plan verify` CURRENTLY passes CLEAN for $1 — the
# one state this guard blocks. Fails open (returns 1 / allow) when the CLI
# binary is missing so a broken install never blocks ordinary authorship.
_plan_proof_clean() {
  local file_path="$1"
  [[ -f "$shctx" ]] || return 1
  bash "$shctx" plan verify --plan "$file_path" --quiet >/dev/null 2>&1
}

# The deny message. Names the exact recovery verbs (real flags, taken from
# `shctx plan -h`) rather than inventing a fictitious "unlock" command.
_plan_proof_locked_message() {
  local file_path="$1"
  cat <<MSG
[shepherd] PLAN-PROOF-LOCKED — $file_path carries a currently-VALID critic-proof (\`shctx plan verify\` passes CLEAN for it right now).
  This Write/Edit would silently invalidate that attestation: the proof is hash-tied to the plan's
  CURRENT bytes, and nothing else warns at record time or edit time -- 'shctx plan verify' only
  catches drift if someone remembers to run it later (DF-22).
  Recovery -- pick the one that matches what actually happened, never hand-edit the sidecar:
    1. A genuine further revision needing a fresh critic pass:
         shctx plan hash "$file_path"
         # ... get the plan re-reviewed by @critic with that hash as --pre ...
         shctx plan record-critique --plan "$file_path" --pre <hash> --verdict <PASS|...> [--iterations N] [--findings N]
    2. Root's sanctioned mid-sprint correction (#268) -- re-ties the EXISTING proof, no new critic pass:
         shctx plan amend --plan "$file_path" --reason "<why>"
  Edit through a channel this guard does not gate (e.g. Bash) to perform the change itself, THEN run
  one of the two commands above -- 'shctx plan verify' will report PLAN-UNEDITED/CRITIC-PROOF-STALE
  until you do.
See skills/shepherd/references/pipeline.md §INTRO.
MSG
}

if [[ "${1:-}" == "--self-test" ]]; then
  echo "self-test: prove plan_proof_guard CAN block a write against a CLEAN critic-proof"
  echo
  fail=0
  if [[ ! -f "$shctx" ]]; then
    echo "SKIP: $shctx not found -- cannot self-test without the shepherd CLI"
    exit 0
  fi

  tmp="$(mktemp -d -t plan-proof-guard-selftest.XXXXXX)"
  trap 'rm -rf "$tmp"' EXIT
  plan="$tmp/plan.md"
  printf '# Fixture Plan\n\nv1 pre-critic draft.\n' > "$plan"
  pre="$(bash "$shctx" plan hash "$plan")"
  printf '# Fixture Plan\n\nv2 post-critic revision.\n' > "$plan"
  bash "$shctx" plan record-critique --plan "$plan" --pre "$pre" --verdict PASS --iterations 1 --findings 0 >/dev/null

  if _plan_proof_clean "$plan"; then echo "  positive control (CLEAN proof detected)  ... ok"
  else echo "  positive control (CLEAN proof detected)  ... DID NOT DETECT -- guard cannot block"; fail=1
  fi

  msg="$(_plan_proof_locked_message "$plan")"
  if printf '%s' "$msg" | grep -q 'record-critique'; then echo "  deny message names record-critique       ... ok"
  else echo "  deny message names record-critique       ... MISSING"; fail=1
  fi
  printf '%s\n' "$msg"

  printf '# Fixture Plan\n\nv3 silently edited AFTER the proof was recorded.\n' > "$plan"
  if _plan_proof_clean "$plan"; then echo "  negative control (STALE proof allowed)    ... DID NOT ALLOW -- would obstruct authoring"; fail=1
  else echo "  negative control (STALE proof allowed)    ... ok"
  fi

  no_proof="$tmp/no-proof.plan.md"
  printf '# Never critiqued\n' > "$no_proof"
  if _plan_proof_clean "$no_proof"; then echo "  negative control (NO proof allowed)       ... DID NOT ALLOW"; fail=1
  else echo "  negative control (NO proof allowed)       ... ok"
  fi

  echo
  if [[ "$fail" -eq 0 ]]; then
    echo "ok: plan_proof_guard blocks a CLEAN critic-proof and allows every other state."
    exit 0
  fi
  echo "::error:: plan_proof_guard self-test failed."
  exit 1
fi

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Write|Edit) ;; *) exit 0 ;; esac

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
[[ -n "$file_path" ]] || exit 0

_is_plan_path "$file_path" || exit 0

session=$(json_field "$input" '.session_id')

if _plan_proof_clean "$file_path"; then
  emit_deny "$(_plan_proof_locked_message "$file_path")" "plan_proof_guard" "$tool" "unknown" "$session"
fi

pass_silent "plan_proof_guard" "$tool" "unknown" "$session"
