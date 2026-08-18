#!/usr/bin/env bash
# hooks/tests/test_harness_parity_generator.sh — regression + falsification
# gate for hooks/scripts/generate_harness_parity.sh.
#
# Three falsification classes, each demonstrated against a scratch/temp
# fixture, never against the tracked tree:
#
#   1. DRIFT — a hand-edited copy of a generated table must be caught by
#      `generate_harness_parity.sh <path> --check` (regenerate-and-diff).
#   2. SILENT BLANK — deleting one manifest's "hooks" key must never produce
#      a blank cell; every row for that harness must read
#      "manifest missing hooks data", and the generator must still exit 0.
#   3. NON-EMPTINESS — a zero-data-row table, and a table with one whole
#      harness column blanked, must both be caught. A "regenerate and diff"
#      check by itself proves nothing if both sides of the diff can be
#      equally empty; this class exists specifically because that failure
#      mode has already been found four times elsewhere in this sprint's
#      gate machinery (see hook_authority_inventory.py's own self-test for
#      one of the four). The expected row count is derived from the three
#      manifests at run time, never hardcoded, so this check tracks the
#      manifests instead of a number frozen at write time.
#
# Accepts SHEPHERD_HARNESS_PARITY_GENERATOR for an override (not expected to
# be needed; present for symmetry with the env-override pattern this file's
# sibling hooks/tests/test_pi_manifest_drift.sh established).
#
# Bash 3.2 safe: no ${var,,}, no mapfile, no declare -A.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
GENERATOR="${SHEPHERD_HARNESS_PARITY_GENERATOR:-$REPO_ROOT/hooks/scripts/generate_harness_parity.sh}"

CLAUDE_MANIFEST="$REPO_ROOT/hooks/hooks.json"
CODEX_MANIFEST="$REPO_ROOT/plugins/shepherd/codex/hooks/hooks.json"
PI_MANIFEST="$REPO_ROOT/packages/harness-pi/shepherd.pi.json"

checks=0
fails=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s -- %s\n' "$1" "$2" >&2; fails=$((fails + 1)); }

finish() {
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  if [[ "$fails" -eq 0 ]]; then
    printf 'PASS: test_harness_parity_generator\n'
    exit 0
  fi
  printf 'FAIL: test_harness_parity_generator (%d)\n' "$fails" >&2
  exit 1
}

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP: jq is required by test_harness_parity_generator\n'
  exit 0
fi

if [[ ! -f "$GENERATOR" ]]; then
  fail "generator exists" "not found: $GENERATOR"
  finish
fi

WORKDIR="$(mktemp -d -t shep-harness-parity-test.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

# =============================================================================
# Independently-derived ground truth (does NOT reuse the generator's own row
# list — a cross-check that trusted the thing it is checking would not be a
# check). The union of canonical events actually declared across the three
# manifests, computed fresh from the manifests themselves.
# =============================================================================

{
  jq -r '.hooks | keys[]?' "$CLAUDE_MANIFEST" 2>/dev/null
  jq -r '.hooks | keys[]?' "$CODEX_MANIFEST" 2>/dev/null
  jq -r '.hooks[]?.canonicalEvent' "$PI_MANIFEST" 2>/dev/null
} | sed '/^$/d' | sort -u > "$WORKDIR/expected_events.txt"
expected_event_count="$(wc -l < "$WORKDIR/expected_events.txt" | tr -d ' ')"

# The one row this generator adds that is NOT a manifest-declared canonical
# event (write-scope narrowing is a property of the SubagentStart binding,
# not its own manifest key — see generate_harness_parity.sh's header
# comment). Excluded before comparing table rows to expected_events.txt.
SYNTHETIC_ROW_LABEL="SubagentStart — write-scope narrowing"

# =============================================================================
# well_formed FILE LABEL — runs every structural/non-emptiness assertion
# against a table file, printing a one-line count summary per assertion and
# returning the number of failed assertions (0 == fully well-formed).
# =============================================================================

well_formed() {
  local file="$1" label="$2" wf_fails=0

  awk -F'|' -v out="$WORKDIR/wf_report.txt" '
    /^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/ {
      rows++
      lbl=$2; gsub(/^[ \t]+|[ \t]+$/, "", lbl)
      claude=$3; codex=$4; pi=$5
      gsub(/^[ \t]+|[ \t]+$/, "", claude)
      gsub(/^[ \t]+|[ \t]+$/, "", codex)
      gsub(/^[ \t]+|[ \t]+$/, "", pi)
      print lbl >> (out ".labels")
      if (lbl == "") blank_label++
      if (claude == "") blank_claude++; else nonblank_claude++
      if (codex == "") blank_codex++; else nonblank_codex++
      if (pi == "") blank_pi++; else nonblank_pi++
    }
    END {
      printf "rows=%d\n", rows + 0
      printf "blank_label=%d\n", blank_label + 0
      printf "blank_claude=%d\n", blank_claude + 0
      printf "nonblank_claude=%d\n", nonblank_claude + 0
      printf "blank_codex=%d\n", blank_codex + 0
      printf "nonblank_codex=%d\n", nonblank_codex + 0
      printf "blank_pi=%d\n", blank_pi + 0
      printf "nonblank_pi=%d\n", nonblank_pi + 0
    }
  ' "$file" > "$WORKDIR/wf_report.txt"
  # shellcheck disable=SC1090
  . "$WORKDIR/wf_report.txt"

  printf '    [%s] rows=%s blank_label=%s claude(non/blank)=%s/%s codex(non/blank)=%s/%s pi(non/blank)=%s/%s\n' \
    "$label" "${rows:-0}" "${blank_label:-0}" \
    "${nonblank_claude:-0}" "${blank_claude:-0}" \
    "${nonblank_codex:-0}" "${blank_codex:-0}" \
    "${nonblank_pi:-0}" "${blank_pi:-0}"

  if [[ "${rows:-0}" -eq 0 ]]; then
    printf '    [%s] FAIL: zero data rows\n' "$label"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${blank_label:-0}" -gt 0 ]]; then
    printf '    [%s] FAIL: %s row(s) with a blank label\n' "$label" "$blank_label"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${nonblank_claude:-0}" -eq 0 ]]; then
    printf '    [%s] FAIL: harness column entirely absent: Claude\n' "$label"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${nonblank_codex:-0}" -eq 0 ]]; then
    printf '    [%s] FAIL: harness column entirely absent: Codex\n' "$label"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${nonblank_pi:-0}" -eq 0 ]]; then
    printf '    [%s] FAIL: harness column entirely absent: Pi\n' "$label"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${blank_claude:-0}" -gt 0 ]]; then
    printf '    [%s] FAIL: %s blank Claude cell(s)\n' "$label" "$blank_claude"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${blank_codex:-0}" -gt 0 ]]; then
    printf '    [%s] FAIL: %s blank Codex cell(s)\n' "$label" "$blank_codex"
    wf_fails=$((wf_fails + 1))
  fi
  if [[ "${blank_pi:-0}" -gt 0 ]]; then
    printf '    [%s] FAIL: %s blank Pi cell(s)\n' "$label" "$blank_pi"
    wf_fails=$((wf_fails + 1))
  fi

  if [[ -f "$WORKDIR/wf_report.txt.labels" ]]; then
    grep -vF "$SYNTHETIC_ROW_LABEL" "$WORKDIR/wf_report.txt.labels" | sort -u > "$WORKDIR/actual_events.txt"
  else
    : > "$WORKDIR/actual_events.txt"
  fi
  actual_event_count="$(wc -l < "$WORKDIR/actual_events.txt" | tr -d ' ')"
  printf '    [%s] event rows (excl. synthetic write-scope row)=%s expected (derived from manifests)=%s\n' \
    "$label" "$actual_event_count" "$expected_event_count"
  if ! diff -q "$WORKDIR/expected_events.txt" "$WORKDIR/actual_events.txt" >/dev/null 2>&1; then
    printf '    [%s] FAIL: table event-row set does not match the manifest-derived event set\n' "$label"
    diff -u "$WORKDIR/expected_events.txt" "$WORKDIR/actual_events.txt" | sed 's/^/      /'
    wf_fails=$((wf_fails + 1))
  fi

  rm -f "$WORKDIR/wf_report.txt.labels"
  return "$wf_fails"
}

# =============================================================================
# Part A — baseline generation
# =============================================================================

baseline="$WORKDIR/baseline.md"
gen_output="$(bash "$GENERATOR" "$baseline" 2>&1)"
gen_exit=$?
if [[ "$gen_exit" -eq 0 && -s "$baseline" ]]; then
  pass "generator exits 0 and writes a non-empty file"
else
  fail "generator exits 0 and writes a non-empty file" "exit=$gen_exit output=$gen_output"
  finish
fi

# =============================================================================
# Part B — non-emptiness / count well-formedness on the real baseline
# (REQUIRED: this must actually assert something, not just diff two empty
# things against each other — see header comment)
# =============================================================================

printf '  -- well-formedness (baseline, must be fully well-formed) --\n'
if well_formed "$baseline" "baseline"; then
  pass "baseline table is well-formed (rows>0, all 3 harness columns non-empty, no blank cells, row set matches manifests)"
else
  fail "baseline table is well-formed" "see well_formed() output above"
fi

# =============================================================================
# Part C — known-cell content assertions (the brief's explicit acceptance set)
# =============================================================================

row_line() {
  # row_line FILE LABEL — the one table data row whose first column is
  # exactly LABEL (anchored, so "SubagentStart" does not also match
  # "SubagentStart — write-scope narrowing").
  grep -E "^\| ${2} \|" "$1"
}

line="$(row_line "$baseline" "SubagentStart")"
if [[ "$line" == *"7d5492e"* && "$line" == *"native_hook.rs"* ]]; then
  pass "Claude SubagentStart cites commit 7d5492e (writes dispatch records, not inert)"
else
  fail "Claude SubagentStart cites commit 7d5492e" "row: $line"
fi
if [[ "$line" == *"Implemented and effective"* ]]; then
  claude_col="$(printf '%s\n' "$line" | awk -F'|' '{print $3}')"
  if [[ "$claude_col" == *"Implemented and effective"* ]]; then
    pass "Claude SubagentStart column state is Implemented and effective"
  else
    fail "Claude SubagentStart column state is Implemented and effective" "col: $claude_col"
  fi
else
  fail "Claude SubagentStart column state is Implemented and effective" "row: $line"
fi

line="$(row_line "$baseline" "SubagentStop")"
codex_col="$(printf '%s\n' "$line" | awk -F'|' '{print $4}')"
if [[ "$codex_col" == *"Unsupported"* && "$codex_col" == *"no trusted spawn-to-child correlation"* && "$codex_col" == *"native_hook.rs"* ]]; then
  pass "Codex SubagentStop is Unsupported, citing no-trusted-correlation + native_hook.rs"
else
  fail "Codex SubagentStop is Unsupported with correct reason/citation" "col: $codex_col"
fi

line="$(row_line "$baseline" "SubagentStart")"
codex_col="$(printf '%s\n' "$line" | awk -F'|' '{print $4}')"
if [[ "$codex_col" == *"Unsupported"* && "$codex_col" == *"no trusted spawn-to-child correlation"* && "$codex_col" == *"native_hook.rs"* ]]; then
  pass "Codex SubagentStart is Unsupported, citing no-trusted-correlation + native_hook.rs"
else
  fail "Codex SubagentStart is Unsupported with correct reason/citation" "col: $codex_col"
fi

line="$(row_line "$baseline" "$SYNTHETIC_ROW_LABEL")"
claude_col="$(printf '%s\n' "$line" | awk -F'|' '{print $3}')"
if [[ "$claude_col" == *"Unsupported"* && "$claude_col" == *'`**`'* && "$claude_col" == *"native_hook.rs"* ]]; then
  pass "Claude write-scope narrowing is Unsupported, citing ** and native_hook.rs"
else
  fail "Claude write-scope narrowing is Unsupported with correct reason/citation" "col: $claude_col"
fi

for ev in CwdChanged PreCompact; do
  line="$(row_line "$baseline" "$ev")"
  claude_col="$(printf '%s\n' "$line" | awk -F'|' '{print $3}')"
  if [[ "$claude_col" == *"Implemented and effective"* && "$claude_col" == *"portable.rs"* && "$claude_col" == *"Ignored"* ]]; then
    pass "Claude $ev is Implemented and effective, noting native-inert via portable.rs"
  else
    fail "Claude $ev is Implemented and effective with native-inert note" "col: $claude_col"
  fi
done

line="$(row_line "$baseline" "SessionShutdown")"
pi_col="$(printf '%s\n' "$line" | awk -F'|' '{print $5}')"
if [[ "$pi_col" == *"Registered but inert"* ]]; then
  pass "Pi SessionShutdown is Registered but inert (defended choice)"
else
  fail "Pi SessionShutdown is Registered but inert" "col: $pi_col"
fi

# =============================================================================
# Part D — exec bits (filesystem, not git index — test_exec_bits.sh owns the
# git-index check separately once these are staged)
# =============================================================================

for f in "$GENERATOR" "$HERE/test_harness_parity_generator.sh"; do
  if [[ -x "$f" ]]; then
    pass "$(basename "$f") is executable on disk"
  else
    fail "$(basename "$f") is executable on disk" "mode: $(stat -f '%Lp' "$f" 2>/dev/null || stat -c '%a' "$f" 2>/dev/null)"
  fi
done

# =============================================================================
# Part E — determinism (same inputs, byte-identical output)
# =============================================================================

rerun="$WORKDIR/rerun.md"
bash "$GENERATOR" "$rerun" >/dev/null 2>&1
if diff -q "$baseline" "$rerun" >/dev/null 2>&1; then
  pass "regeneration is byte-identical (determinism)"
else
  fail "regeneration is byte-identical" "$(diff -u "$baseline" "$rerun" | head -20)"
fi

# =============================================================================
# FALSIFICATION 1 — DRIFT: hand-edit one cell, prove --check catches it
# =============================================================================

printf '  -- FALSIFICATION 1: drift (regenerate-and-diff) --\n'
corrupted="$WORKDIR/corrupted.md"
sed 's/Implemented and effective/Implemented and effective (HAND-EDITED)/' "$baseline" > "$corrupted"
# corrupted differs from baseline by construction; sanity-check the sed hit.
if diff -q "$baseline" "$corrupted" >/dev/null 2>&1; then
  fail "falsification 1 setup: sed actually changed the corrupted copy" "sed found nothing to edit"
else
  pass "falsification 1 setup: corrupted copy differs from baseline by exactly one hand-edit"
fi

f1_output="$(bash "$GENERATOR" "$corrupted" --check 2>&1)"
f1_exit=$?
printf '%s\n' "$f1_output" | sed 's/^/    /'
if [[ "$f1_exit" -ne 0 ]]; then
  pass "generate_harness_parity.sh --check exits nonzero against a hand-edited copy (exit=$f1_exit)"
else
  fail "generate_harness_parity.sh --check detects the hand-edit" "exit=$f1_exit"
fi

# =============================================================================
# FALSIFICATION 2 — SILENT BLANK: delete one manifest's "hooks" key entirely
# =============================================================================

printf '  -- FALSIFICATION 2: silent blank (missing hooks key, per manifest) --\n'

falsify_missing_hooks() {
  local harness="$1" real_manifest="$2" env_var="$3" col_index="$4"
  local broken="$WORKDIR/broken-${harness}.json"
  jq 'del(.hooks)' "$real_manifest" > "$broken"
  local out="$WORKDIR/degraded-${harness}.md"
  local f2_output f2_exit
  f2_output="$(env "$env_var=$broken" bash "$GENERATOR" "$out" 2>&1)"
  f2_exit=$?
  printf '    [%s] generator exit=%s\n' "$harness" "$f2_exit"
  if [[ "$f2_exit" -ne 0 ]]; then
    fail "$harness missing-hooks-key: generator exits 0 (graceful degrade)" "exit=$f2_exit: $f2_output"
    return
  fi
  local missing_count total_count
  total_count="$(awk '/^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/' "$out" | wc -l | tr -d ' ')"
  missing_count="$(awk -F'|' -v c="$col_index" '/^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/ { if ($c ~ /manifest missing hooks data/) n++ } END{print n+0}' "$out")"
  printf '    [%s] rows with "manifest missing hooks data" in the %s column: %s / %s data rows\n' \
    "$harness" "$harness" "$missing_count" "$total_count"
  if [[ "$missing_count" -gt 0 && "$missing_count" -eq "$total_count" ]]; then
    pass "$harness missing-hooks-key: every row's $harness column reads 'manifest missing hooks data' ($missing_count/$total_count)"
  else
    fail "$harness missing-hooks-key: every row's $harness column reads 'manifest missing hooks data'" \
      "$missing_count/$total_count rows matched"
  fi
  local wf_out
  if well_formed "$out" "degraded-$harness"; then
    pass "$harness missing-hooks-key output is still well-formed (no blank cells anywhere, incl. other harnesses)"
  else
    fail "$harness missing-hooks-key output is still well-formed" "see well_formed() output above"
  fi
}

falsify_missing_hooks "Claude" "$CLAUDE_MANIFEST" "SHEPHERD_PARITY_CLAUDE_MANIFEST" 3
falsify_missing_hooks "Codex" "$CODEX_MANIFEST" "SHEPHERD_PARITY_CODEX_MANIFEST" 4
falsify_missing_hooks "Pi" "$PI_MANIFEST" "SHEPHERD_PARITY_PI_MANIFEST" 5

# Bonus: a manifest that is not valid JSON at all must hard-error, never
# produce a table (there is nothing honest to say about unparsable input).
printf 'not json {{{' > "$WORKDIR/invalid.json"
invalid_output="$(env "SHEPHERD_PARITY_CLAUDE_MANIFEST=$WORKDIR/invalid.json" bash "$GENERATOR" "$WORKDIR/invalid-out.md" 2>&1)"
invalid_exit=$?
if [[ "$invalid_exit" -ne 0 && "$invalid_output" == *"not valid JSON"* ]]; then
  pass "invalid-JSON manifest hard-errors instead of producing a table (exit=$invalid_exit)"
else
  fail "invalid-JSON manifest hard-errors" "exit=$invalid_exit output=$invalid_output"
fi

# =============================================================================
# FALSIFICATION 3 — NON-EMPTINESS: a zero-row table and a one-column-missing
# table must both be caught by well_formed(). A "diff two files" check alone
# cannot catch this class (an empty table diffed against another empty table
# is a clean diff) — this is why well_formed() exists as its own assertion,
# not folded into the drift check.
# =============================================================================

printf '  -- FALSIFICATION 3: non-emptiness (zero rows / missing column) --\n'

zero_row="$WORKDIR/zero_row.md"
awk '{print} /^\|---\|---\|---\|---\|$/{exit}' "$baseline" > "$zero_row"
zero_rows_actual="$(awk '/^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/' "$zero_row" | wc -l | tr -d ' ')"
printf '    zero-row fixture has %s data row(s) (constructed to have 0)\n' "$zero_rows_actual"
if well_formed "$zero_row" "zero-row"; then
  fail "well_formed() rejects a zero-data-row table" "well_formed() returned 0 (pass) on a 0-row fixture"
else
  wf_rc=$?
  pass "well_formed() rejects a zero-data-row table ($wf_rc failing assertion(s) reported above)"
fi

col_missing="$WORKDIR/col_missing.md"
awk -F'|' 'BEGIN{OFS="|"} /^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/ { $5=" " } {print}' "$baseline" > "$col_missing"
pi_nonblank_check="$(awk -F'|' '/^\| / && $0 !~ /^\|---/ && $0 !~ /^\| Event \|/ { v=$5; gsub(/^[ \t]+|[ \t]+$/,"",v); if (v!="") c++ } END{print c+0}' "$col_missing")"
printf '    column-missing fixture: Pi column non-blank cell count = %s (constructed to be 0)\n' "$pi_nonblank_check"
if well_formed "$col_missing" "col-missing"; then
  fail "well_formed() rejects a table with the Pi column entirely blanked" "well_formed() returned 0 (pass) with Pi column emptied"
else
  wf_rc=$?
  pass "well_formed() rejects a table with the Pi column entirely blanked ($wf_rc failing assertion(s) reported above)"
fi

# =============================================================================
# FALSIFICATION 4 — UNKNOWN FLAG: a mistyped flag must be rejected, never
# silently reinterpreted as an output path (that would write a file named
# after the typo and exit 0 — a wrong invocation indistinguishable from a
# correct one).
# =============================================================================

printf '  -- FALSIFICATION 4: unrecognized flag is rejected, not a filename --\n'

badflag_dir="$WORKDIR/badflag"
mkdir -p "$badflag_dir"
badflag_before="$(ls -A "$badflag_dir" | wc -l | tr -d ' ')"
badflag_output="$(cd "$badflag_dir" && bash "$GENERATOR" --chekc 2>&1)"
badflag_exit=$?
badflag_after="$(ls -A "$badflag_dir" | wc -l | tr -d ' ')"
printf '    exit=%s files-before=%s files-after=%s\n' "$badflag_exit" "$badflag_before" "$badflag_after"
printf '%s\n' "$badflag_output" | sed 's/^/    /'
if [[ "$badflag_exit" -ne 0 ]]; then
  pass "unrecognized flag --chekc exits nonzero (exit=$badflag_exit)"
else
  fail "unrecognized flag --chekc exits nonzero" "exit=$badflag_exit"
fi
if [[ "$badflag_after" -eq "$badflag_before" ]]; then
  pass "unrecognized flag --chekc creates no file (dir entry count unchanged: $badflag_before -> $badflag_after)"
else
  fail "unrecognized flag --chekc creates no file" "dir entry count changed: $badflag_before -> $badflag_after"
fi

help_output="$(bash "$GENERATOR" --help 2>&1)"
help_exit=$?
if [[ "$help_exit" -eq 0 && "$help_output" == *"Usage:"* ]]; then
  pass "--help prints usage and exits 0"
else
  fail "--help prints usage and exits 0" "exit=$help_exit output=$help_output"
fi

# =============================================================================
# Part F — real committed artifact (only once a later wave lands it; this
# wave deliberately does not write .shepherd/runs/v646/harness-parity.md, so
# SKIP rather than FAIL is correct here)
# =============================================================================

committed="$REPO_ROOT/.shepherd/runs/v646/harness-parity.md"
if [[ -f "$committed" ]]; then
  check_output="$(bash "$GENERATOR" --check 2>&1)"
  check_exit=$?
  if [[ "$check_exit" -eq 0 ]]; then
    pass "committed harness-parity.md matches a fresh regeneration"
  else
    fail "committed harness-parity.md matches a fresh regeneration" "$check_output"
  fi
else
  printf '  SKIP  committed .shepherd/runs/v646/harness-parity.md does not exist yet (later wave writes it)\n'
fi

finish
