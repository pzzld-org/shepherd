#!/usr/bin/env bash
# shepherd hook — Stop: close-finalize completion check (v6.0.7).
# Deterministic replacement for the agent-type prompt (GH #127, fires #1–17).
#
# WHY A SCRIPT, NOT AN AGENT: Ten+ fires across four session types showed that an
# agent-type hook free-forms ok:false from conversation context regardless of whether
# the slug-close detection logic succeeds or fails (fire #10: agent "correctly diagnosed
# everything... and still returned ok:false"). Detection is entirely scriptable — a script
# cannot override its own logic with narrative context.
#
# REQUIRES TWO INDEPENDENT POSITIVE SIGNALS before blocking:
#   Signal A: a sprint-slug-scoped close report committed in HEAD (not --all)
#             Pattern: {NS}/reports/*-v{slug}-close.md
#             (e.g. .artifacts/reports/2026-04-16-v034-dev9-close.md)
#   Signal B: the sprint branch still exists on origin
#
# SIDE CHANNEL (v6.4.1 #59, after Signal A, never a block): warns ONCE per
# session on stderr when a [gates.extra] entry has no recorded invocation in
# this session's gates ledger (<NS>/tmp/gates-ran-<session>.jsonl, written by
# bash_post.sh; `shepherd doctor` reports the same).
#
# FAST-PATHS (all exit 0 silently — fail-open on uncertainty):
#   • HEAD not a sprint branch (*-dev.[0-9]+)
#   • Inside a subworktree (toplevel != pwd) — worktree checkouts refresh mtimes
#     on historical reports; fire-3 showed this creates false positives
#   • Signal A empty — no close report committed for this sprint slug
#   • Signal B empty — branch already gone from origin; finalize complete
#   • Any command failure → exit 0 (never block on uncertainty)
#
# EXCLUDED from detection (all return ok silently):
#   • Plant-mode artifacts: *-planter-mesh.md, *.seed.md — committed to reports/
#     by /shepherd:plant but share no naming convention with close reports
#   • Historical close reports from prior patches: --all scope removed; HEAD only
#   • Worktree-materialized historical reports: subworktree guard
#
# Input  (stdin): Stop JSON (fields optional; not used by this script).
# Output (stdout): {"decision":"block","reason":"..."} to block, else silent.
# Exit: always 0 (fail-open; block carried by stdout JSON, not exit code).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# ── 1. Sprint-branch guard ────────────────────────────────────────────────────
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
[[ -n "$BRANCH" ]] || exit 0
# Must match *-dev.N pattern (sprint branch, not patch/main/feature)
[[ "$BRANCH" =~ -dev\.[0-9]+$ ]] || exit 0

# ── 2. Subworktree guard ─────────────────────────────────────────────────────
# git worktree add materializes EVERY historical close report with current mtimes.
# Any check inside a worktree is unreliable. (fire #3 root cause)
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$TOPLEVEL" ]] || exit 0
[[ "$(pwd -P 2>/dev/null || pwd)" == "$TOPLEVEL" ]] || exit 0

# ── 3. Slug derivation ───────────────────────────────────────────────────────
# v0.3.5-dev.0 → strip 'v' → collapse version dots (0.3.5 → 035) → 035-dev0
# Matches naming convention from seed-template.md §"File path":
#   v{X}.{Y}.{Z}-dev.{N} → v{XYZ}-dev{N} (dots in version triplet collapse)
SLUG="$(echo "$BRANCH" \
  | sed 's/^v//' \
  | sed 's/^\([0-9]*\)\.\([0-9]*\)\.\([0-9]*\)-dev\.\([0-9]*\)$/\1\2\3-dev\4/')"
[[ -n "$SLUG" ]] || exit 0
# Sanity: slug must look like digits-devN
[[ "$SLUG" =~ ^[0-9]+-dev[0-9]+$ ]] || exit 0

NS="$(resolve_namespace 2>/dev/null || echo .artifacts)"

# ── 4. Signal A: close report committed in git (HEAD only, strict slug naming) ─
# Pattern: {NS}/reports/*-v{slug}-close.md
# Example: .artifacts/reports/2026-04-16-v034-dev9-close.md
# NOT matched: 2026-06-04-planter-mesh.md, *.seed.md, historical other-sprint closes
SIG_A="$(git log --oneline --diff-filter=A HEAD \
  -- "${NS}/reports/*-v${SLUG}-close.md" 2>/dev/null | head -1 || true)"
[[ -n "$SIG_A" ]] || exit 0   # No sprint-scoped close report → still in progress

# ── 4b. #59: [gates.extra] recorded-invocation warn (NEVER blocks) ───────────
# A committed close report means this session is at/past CLOSE — every
# [gates.extra] entry should have a recorded invocation in this session's
# gates ledger (<NS>/tmp/gates-ran-<session>.jsonl, appended by bash_post.sh
# whenever a configured gate command runs). Missing entries get ONE stderr
# warning per session (marker-bounded, mirroring the runaway-cap stderr
# idiom above), never a block: extras are a close obligation, not a Stop
# gate. `shepherd doctor` carries the same report as its `gates` section.
GF_SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"; [[ -n "$GF_SESSION" ]] || GF_SESSION="nosession"
GF_SAFE="${GF_SESSION//[^A-Za-z0-9_.-]/_}"
GF_WARNED="$NS/tmp/gates-extra-warned.${GF_SAFE}"
if [[ ! -f "$GF_WARNED" ]]; then
  GF_LEDGER="$NS/tmp/gates-ran-${GF_SAFE}.jsonl"
  GF_MISSING=""
  while IFS= read -r gf_key; do
    [[ -n "$gf_key" ]] || continue
    gf_val="$(cfg_section_get gates.extra "$gf_key" 2>/dev/null || true)"
    [[ -n "$gf_val" ]] || continue
    grep -qE "\"gate\":[[:space:]]*\"extra:${gf_key}\"" "$GF_LEDGER" 2>/dev/null \
      || GF_MISSING="${GF_MISSING:+$GF_MISSING, }$gf_key"
  done < <(cfg_section_keys gates.extra 2>/dev/null || true)
  if [[ -n "$GF_MISSING" ]]; then
    mkdir -p "$NS/tmp" 2>/dev/null || true
    touch "$GF_WARNED" 2>/dev/null || true
    echo "[shctx] close-finalize: [gates.extra] entries with NO recorded invocation this session: ${GF_MISSING} — run them before finalizing (bash_post.sh records each run; 'shepherd doctor' shows the same ledger) (#59)." >&2
    log_event "close_finalize_check" "warn" "Stop" "shepherd" "$GF_SESSION" \
      "$(emit_json_obj missing_gates "$GF_MISSING" slug "$SLUG")" 2>/dev/null || true
  fi
fi

# ── 5. Signal B: sprint branch still exists on origin ────────────────────────
SIG_B="$(git ls-remote --heads origin "$BRANCH" 2>/dev/null | head -1 || true)"
[[ -n "$SIG_B" ]] || exit 0   # Branch gone → finalize complete

# ── 6. Do not re-block a deferred merge forever (#154) ────────────────────────
# Both signals stay positive for as long as the dev→patch merge is DELIBERATELY
# deferred (operator-gated), so an unbounded Stop hook re-blocks EVERY turn-end
# indefinitely — the #154 unbreakable loop (field: fired every ~15-30s for hours).
# Two escapes, both fail-open:
#   (a) explicit operator hold — [close].finalize_hold = "true" silences the block
#       while the merge is intentionally held;
#   (b) a runaway bound per (session, slug, HEAD-sha): after CAP fires on the SAME
#       committed state, fail OPEN and stop nagging (mirrors coordinate_drive_guard.sh's
#       #114 idiom). A NEW commit changes HEAD → a fresh key → the block legitimately
#       re-warns once, so a real new close report is never masked.
case "$(cfg_get finalize_hold 2>/dev/null | tr '[:upper:]' '[:lower:]')" in
  true|held|held-for-operator|yes|on|1) exit 0 ;;
esac

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"; [[ -n "$SESSION" ]] || SESSION="nosession"
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || echo nohead)"
CAP=2
CNT_DIR="$NS/tmp"
key="${SESSION}.${SLUG}.${HEAD_SHA}"; key="${key//[^A-Za-z0-9_.-]/_}"
CNT_FILE="$CNT_DIR/close_finalize_check.${key}.count"
CNT="$(cat "$CNT_FILE" 2>/dev/null || echo 0)"; [[ "$CNT" =~ ^[0-9]+$ ]] || CNT=0
if [[ "$CNT" -ge "$CAP" ]]; then
  echo "[shctx] close-finalize: ${BRANCH} still on origin after ${CAP} nudges — the dev→patch merge looks intentionally deferred; set [close].finalize_hold=\"true\" to silence it until you finish the merge." >&2
  exit 0
fi
mkdir -p "$CNT_DIR" 2>/dev/null || true
echo $((CNT + 1)) > "$CNT_FILE" 2>/dev/null || true

# ── 7. Both signals positive, within bound → flag incomplete finalize ─────────
# No destructive remediation suggested (issue #127 root cause: --delete on live branch).
REASON="CLOSE-FINALIZE INCOMPLETE: close report committed for ${BRANCH} (${SIG_A}) but sprint branch still on origin. Verify dev→patch merge is complete: run \`git log origin/<patch_branch>..${BRANCH} --oneline\` (should be empty if merged). Then run conductor §CLOSE-FINALIZE steps 4–6 via explicit operator-confirmed commands. Confirm merge before removing the sprint branch from origin."

log_event "close_finalize_check" "block" "Stop" "shepherd" "" \
  "$(emit_json_obj branch "$BRANCH" slug "$SLUG" sig_a "${SIG_A:0:80}")" 2>/dev/null || true

emit_json_obj decision "block" reason "$REASON"
exit 0
