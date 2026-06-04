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

# ── 5. Signal B: sprint branch still exists on origin ────────────────────────
SIG_B="$(git ls-remote --heads origin "$BRANCH" 2>/dev/null | head -1 || true)"
[[ -n "$SIG_B" ]] || exit 0   # Branch gone → finalize complete

# ── 6. Both signals positive → flag incomplete finalize ──────────────────────
# No destructive remediation suggested (issue #127 root cause: --delete on live branch).
REASON="CLOSE-FINALIZE INCOMPLETE: close report committed for ${BRANCH} (${SIG_A}) but sprint branch still on origin. Verify dev→patch merge is complete: run \`git log origin/<patch_branch>..${BRANCH} --oneline\` (should be empty if merged). Then run conductor §CLOSE-FINALIZE steps 4–6 via explicit operator-confirmed commands. Confirm merge before removing the sprint branch from origin."

log_event "close_finalize_check" "block" "Stop" "shepherd" "" \
  "$(emit_json_obj branch "$BRANCH" slug "$SLUG" sig_a "${SIG_A:0:80}")" 2>/dev/null || true

emit_json_obj decision "block" reason "$REASON"
exit 0
