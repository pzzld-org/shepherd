#!/usr/bin/env bash
# test_lead_workflow_tool.sh — regression pin for #207 (v6.3.6).
#
# #207: the `@engineer` and `@conductor` LEADS are doctrinally required to
# compile gate-free fan-out into Dynamic Workflows (conductor.md §WORKFLOW
# SELF-CHECK: "compiling gate-free fan-out to a Dynamic Workflow is the default,
# not the exception"), and both run at `[spawn].lead_effort=ultracode` which
# mandates that path. But the `Workflow` grant was ABSENT from their `tools:`
# frontmatter for versions, so the mandated self-check took its "Absent → slow
# in-context Agent()" branch on every spawn — the single highest-leverage
# wave-speed regression. Fixed in v6.3.5 (frontmatter grant) + pinned by the new
# lead-mandated-tool-presence block in lint_agent_capabilities.sh (v6.3.6).
#
# This test proves the guard is REAL in both directions, using the lint's own
# SHEPHERD_LINT_AGENTS_DIR override so it never mutates the tracked tree:
#   1. the real agents/ (post-fix) PASSES the lint;
#   2. an agents/ copy with `Workflow` stripped from a lead FAILS the lint with
#      the #207 diagnostic — i.e. the bug, reintroduced, is caught by the gate.
#
# Exit 0 on pass; exit 1 with a diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LINT="$HERE/lint_agent_capabilities.sh"

fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$LINT" ]] || { note "MISSING: $LINT"; exit 1; }

# --- 1. the shipped tree GRANTS Workflow to both leads → lint PASSES ----------
for role in engineer conductor; do
  f="$ROOT/agents/$role.md"
  if [[ ! -f "$f" ]]; then
    note "FAIL: agents/$role.md missing"; fails=$((fails+1)); continue
  fi
  tools="$(awk '/^tools:[[:space:]]/ {sub(/^tools:[[:space:]]*/, ""); print; exit}' "$f")"
  if ! printf '%s' "$tools" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Workflow'; then
    note "FAIL $role: shipped frontmatter does not grant 'Workflow' (#207 not fixed at source)"
    fails=$((fails+1))
  fi
done

if ! lint_out="$(bash "$LINT" 2>&1)"; then
  note "FAIL: lint_agent_capabilities.sh fails on the real (fixed) tree — should be green:"
  printf '%s\n' "$lint_out" | sed 's/^/      /'
  fails=$((fails+1))
fi

# --- 2. strip Workflow from each lead in an isolated copy → lint must FAIL -----
# Uses the lint's SHEPHERD_LINT_AGENTS_DIR override; the tracked agents/ is
# never touched. Both leads are exercised independently so neither grant can
# silently rot behind the other.
for role in engineer conductor; do
  tmp="$(mktemp -d -t shep-207.XXXXXX)" || { note "mktemp failed"; exit 1; }
  cp -r "$ROOT/agents" "$tmp/agents"
  target="$tmp/agents/$role.md"
  # Drop the exact `Workflow` token from the tools: line, whatever its position
  # (", Workflow," | ", Workflow$" | ": Workflow,"), leaving the rest intact.
  awk '
    /^tools:[[:space:]]/ && !done {
      n = split($0, a, /,[[:space:]]*/)
      out = ""
      for (i = 1; i <= n; i++) {
        t = a[i]; gsub(/[[:space:]]+$/, "", t)
        if (t == "Workflow" || t ~ /[[:space:]]Workflow$/) continue
        out = (out == "" ? t : out ", " t)
      }
      print out; done = 1; next
    }
    { print }
  ' "$ROOT/agents/$role.md" > "$target"

  if awk '/^tools:[[:space:]]/{print;exit}' "$target" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -qx 'Workflow'; then
    note "FAIL: harness could not strip Workflow from $role.md (test setup broken)"
    fails=$((fails+1)); rm -rf "$tmp"; continue
  fi

  if out="$(SHEPHERD_LINT_AGENTS_DIR="$tmp/agents" bash "$LINT" 2>&1)"; then
    note "FAIL: lint PASSED with 'Workflow' stripped from $role — #207 guard is not enforcing"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  elif ! printf '%s' "$out" | grep -q "FAIL $role:.*Workflow.*#207"; then
    note "FAIL: lint failed for stripped $role but not via the #207 mandated-tool diagnostic:"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  fi
  rm -rf "$tmp"
done

if [[ "$fails" -gt 0 ]]; then
  printf 'test_lead_workflow_tool: %d failure(s) — the #207 lead-Workflow guard is not solid\n' "$fails"
  exit 1
fi
printf 'test_lead_workflow_tool: OK — engineer + conductor grant Workflow; stripping it fails the lint (#207 regression pinned)\n'
exit 0
