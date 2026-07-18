#!/usr/bin/env bash
# test_lead_workflow_tool.sh — regression pin for the #220/#217 Workflow-tool
# GRANT partition (v6.3.9, supersedes the v6.3.6/#207 "both leads grant Workflow"
# pin, which was correct only for root).
#
# The `Workflow` tool is a TOP-LEVEL-SESSION primitive — hard-denied inside
# subagents ("Workflow is not available inside subagents", CC 2.1.212, #220). So
# the grant partitions by tier, and this test pins BOTH halves against
# lint_agent_capabilities.sh via its SHEPHERD_LINT_AGENTS_DIR override (the
# tracked tree is never mutated):
#   • ROOT (shepherd) MUST grant Workflow (drives /shepherd:start, #217) —
#     stripping it FAILS the lint.
#   • Teammate leads (engineer, conductor) MUST NOT grant Workflow (denied one
#     tier down, #220) — an inert grant misleads; ADDING it FAILS the lint.
#
# Exit 0 on pass; exit 1 with a diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LINT="$HERE/lint_agent_capabilities.sh"

fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$LINT" ]] || { note "MISSING: $LINT"; exit 1; }

# grants_workflow <agent-file> → 0 if 'Workflow' is a token on the tools: line.
grants_workflow() {
  awk '/^tools:[[:space:]]/ {sub(/^tools:[[:space:]]*/, ""); print; exit}' "$1" \
    | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Workflow'
}

# --- 1. shipped tree: root GRANTS Workflow; teammate leads do NOT -------------
if ! grants_workflow "$ROOT/agents/shepherd.md"; then
  note "FAIL: shipped agents/shepherd.md does not grant 'Workflow' (root must — #217)"
  fails=$((fails+1))
fi
for role in engineer conductor; do
  f="$ROOT/agents/$role.md"
  if [[ ! -f "$f" ]]; then note "FAIL: agents/$role.md missing"; fails=$((fails+1)); continue; fi
  if grants_workflow "$f"; then
    note "FAIL: shipped agents/$role.md grants 'Workflow' but the teammate tier is denied it (#220)"
    fails=$((fails+1))
  fi
done

# --- 2. the shipped tree PASSES the lint --------------------------------------
if ! lint_out="$(bash "$LINT" 2>&1)"; then
  note "FAIL: lint_agent_capabilities.sh fails on the real (fixed) tree — should be green:"
  printf '%s\n' "$lint_out" | sed 's/^/      /'
  fails=$((fails+1))
fi

# --- 3. strip Workflow from ROOT → lint must FAIL (#217 root guard) -----------
tmp="$(mktemp -d -t shep-220-root.XXXXXX)" || { note "mktemp failed"; exit 1; }
cp -r "$ROOT/agents" "$tmp/agents"
awk '
  /^tools:[[:space:]]/ && !done {
    n = split($0, a, /,[[:space:]]*/); out = ""
    for (i = 1; i <= n; i++) { t = a[i]; gsub(/[[:space:]]+$/, "", t)
      if (t == "Workflow" || t ~ /[[:space:]]Workflow$/) continue
      out = (out == "" ? t : out ", " t) }
    print out; done = 1; next
  }
  { print }
' "$ROOT/agents/shepherd.md" > "$tmp/agents/shepherd.md"
if grants_workflow "$tmp/agents/shepherd.md"; then
  note "FAIL: harness could not strip Workflow from shepherd.md (test setup broken)"
  fails=$((fails+1))
elif out="$(SHEPHERD_LINT_AGENTS_DIR="$tmp/agents" bash "$LINT" 2>&1)"; then
  note "FAIL: lint PASSED with 'Workflow' stripped from shepherd — #217 root guard not enforcing"
  printf '%s\n' "$out" | sed 's/^/      /'
  fails=$((fails+1))
elif ! printf '%s' "$out" | grep -q "FAIL shepherd:.*Workflow.*#217"; then
  note "FAIL: lint failed for stripped shepherd but not via the #217 root diagnostic:"
  printf '%s\n' "$out" | sed 's/^/      /'
  fails=$((fails+1))
fi
rm -rf "$tmp"

# --- 4. ADD Workflow to each teammate lead → lint must FAIL (#220 inverse) ----
for role in engineer conductor; do
  tmp="$(mktemp -d -t shep-220-tm.XXXXXX)" || { note "mktemp failed"; exit 1; }
  cp -r "$ROOT/agents" "$tmp/agents"
  awk '
    /^tools:[[:space:]]/ && !done { print $0 ", Workflow"; done = 1; next }
    { print }
  ' "$ROOT/agents/$role.md" > "$tmp/agents/$role.md"
  if ! grants_workflow "$tmp/agents/$role.md"; then
    note "FAIL: harness could not add Workflow to $role.md (test setup broken)"
    fails=$((fails+1)); rm -rf "$tmp"; continue
  fi
  if out="$(SHEPHERD_LINT_AGENTS_DIR="$tmp/agents" bash "$LINT" 2>&1)"; then
    note "FAIL: lint PASSED with 'Workflow' added to $role — #220 inverse guard not enforcing"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  elif ! printf '%s' "$out" | grep -q "FAIL $role:.*Workflow.*#220"; then
    note "FAIL: lint failed for $role+Workflow but not via the #220 inverse diagnostic:"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  fi
  rm -rf "$tmp"
done

if [[ "$fails" -gt 0 ]]; then
  printf 'test_lead_workflow_tool: %d failure(s) — the #220/#217 Workflow-grant partition is not solid\n' "$fails"
  exit 1
fi
printf 'test_lead_workflow_tool: OK — root grants Workflow (strip fails #217); teammate leads do NOT (adding it fails #220)\n'
exit 0
