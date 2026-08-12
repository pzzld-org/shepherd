#!/usr/bin/env bash
# hooks/tests/test_changelog_current.sh — changelog-currency gate (v6.3.6, #130-adjacent).
#
# v6.3.4 and v6.3.5 shipped as tagged releases (#204, #205) with NO CHANGELOG.md
# entry — and v6.3.5 was the #207 Workflow-tool fix itself, so the single most
# consequential recent fix went unrecorded. `.github/workflows/release.yml`
# silently fell back to GitHub auto-generated notes when a `## v<version>`
# section was missing, so nothing flagged the omission.
#
# This gate asserts CHANGELOG.md carries an entry for the version currently
# declared in .claude-plugin/plugin.json — so a version bump can never again
# ship without its changelog entry. Deterministic, offline, <2s: gate-test lane.
#
# Exit 0 on pass; exit 1 with a diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PLUGIN="$ROOT/.claude-plugin/plugin.json"
CHANGELOG="$ROOT/CHANGELOG.md"

fail() { printf 'test_changelog_current: FAIL — %s\n' "$1"; exit 1; }

[[ -f "$PLUGIN" ]]    || fail ".claude-plugin/plugin.json not found"
[[ -f "$CHANGELOG" ]] || fail "CHANGELOG.md not found"

# Parse the plugin version without a jq dependency (X.Y.Z from the "version" key).
VER="$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"' "$PLUGIN" \
        | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
[[ -n "$VER" ]] || fail "could not parse a semver \"version\" from plugin.json"

# The changelog header for this version must exist: `## vX.Y.Z` (optionally
# followed by a space + date, or end of line). Escape the dots for the regex.
esc="${VER//./\\.}"
if ! grep -qE "^## v${esc}( |\$)" "$CHANGELOG"; then
  fail "plugin.json is v${VER} but CHANGELOG.md has no '## v${VER}' entry — add the changelog entry in the same change that bumps the version (this is exactly how v6.3.4/v6.3.5 shipped undocumented)"
fi

printf 'test_changelog_current: OK — CHANGELOG.md documents the current plugin version v%s\n' "$VER"
exit 0
