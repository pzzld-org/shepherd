#!/usr/bin/env bash
# scripts/check-workflow-meta.sh — every Dynamic Workflow's `meta` block is a
# PURE LITERAL (DF-69).
#
# WHY THIS EXISTS.
#
# `workflows/wave.js` once shipped with `meta.whenToUse` built by `+` string
# concatenation across three fragments, and stayed unloadable. The Workflow
# tool's contract is explicit: "The `meta` object must be a PURE LITERAL — no
# variables, function calls, spreads, or template interpolation." The loader
# rejects a violation with `meta must be a pure literal: non-literal node
# type in meta: BinaryExpression` — and it rejects it at DISPATCH time, after
# the operator has already paid for the turn. `node --check` does NOT catch
# this: the file is syntactically valid JavaScript; the constraint is
# semantic and enforced only inside Claude Code's Workflow loader. Nothing
# else in the repo inspected `workflows/*.js` at all, so the break shipped
# green and was discovered only when a live conductor tried to invoke it.
#
# APPROACH.
#
# This is a string-aware state machine, not a JS parser — it does not need to
# be one. It only has to (1) find the exact substring of the `meta` OBJECT
# LITERAL in a file, matching braces while correctly ignoring any brace that
# sits inside a string, then (2) mask every string literal's CONTENT — never
# its delimiter — with a neutral filler character before scanning for
# disallowed tokens.
#
# Step (2) is not optional. The naive version of this check scans the RAW
# text and trips on a `+`, a `(`, a `)` or an apostrophe that legitimately
# sits inside a quoted description string — that already produced a false
# positive once on this run and cost a debugging cycle. Masking string
# CONTENT first (while keeping the quote delimiters, so a bare backtick
# string is still visible as one) is what makes the scan safe: after
# masking, anything left outside a quoted region is real JS syntax, not
# prose. Single, double and backtick-quoted strings are all handled, with
# backslash-escape awareness so `'it\'s fine'` does not end the string early.
#
# Once masked, the object literal cannot legally contain: a backtick
# delimiter (TemplateLiteral), a `+` (BinaryExpression — exactly DF-69's
# shape), `...` (SpreadElement), a parenthesis (CallExpression — a plain
# object/array/string/number/boolean/null literal never needs one), or a
# bare word in value position that is not `true`/`false`/`null` (Identifier).
# Any of the above fails the file.
#
# Usage:
#   scripts/check-workflow-meta.sh              # check every workflows/*.js
#   scripts/check-workflow-meta.sh --self-test   # prove the check can fail
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

AWK_SCRIPT=""
TMP_DIRS=()

cleanup() {
  [[ -n "${AWK_SCRIPT}" && -f "${AWK_SCRIPT}" ]] && rm -f "${AWK_SCRIPT}"
  local d
  for d in "${TMP_DIRS[@]+"${TMP_DIRS[@]}"}"; do
    [[ -n "${d}" ]] && rm -rf "${d}"
  done
}
trap cleanup EXIT

# The awk program lives in its own file (written once, here) rather than
# inline in an `awk '...'` call: it needs literal single quotes, double
# quotes and backslashes in its own source, all of which fight bash's own
# quoting if embedded directly. A quoted heredoc delimiter passes its body
# through completely untouched — no bash expansion, no escaping games.
AWK_SCRIPT="$(mktemp -t check-workflow-meta-awk.XXXXXX)"
cat > "${AWK_SCRIPT}" <<'AWK_EOF'
# extract_meta_block, in awk: locate `export const meta = {`, then walk
# forward one character at a time tracking brace depth and string state
# (quote char + backslash-escape) until the opening brace's matching close.
# Emits:
#   NOTFOUND                                    — no meta block in this file
#   UNCLOSED                                    — opened, never balanced
#   FOUND\n===RAW===\n<raw>\n===MASKED===\n<masked>
# <raw> is the untouched block text; <masked> is the same block with every
# string literal's CONTENT replaced by `x`, delimiters intact.
BEGIN {
  state = "search"; depth = 0; instr = 0; qchar = ""; esc = 0
  raw = ""; masked = ""; found = 0; done_flag = 0; buf = ""
}
{
  line = $0
  n = length(line)
  for (i = 1; i <= n; i++) {
    c = substr(line, i, 1)
    if (state == "search") {
      buf = buf c
      if (length(buf) > 200) buf = substr(buf, length(buf) - 199)
      if (buf ~ /export[ \t]+const[ \t]+meta[ \t]*=[ \t]*\{[ \t]*$/) {
        state = "capture"; depth = 1; raw = "{"; masked = "{"; found = 1
      }
      continue
    }
    raw = raw c
    if (instr) {
      if (esc)              { masked = masked "x"; esc = 0 }
      else if (c == "\\")   { esc = 1; masked = masked "x" }
      else if (c == qchar)  { instr = 0; masked = masked c }
      else                  { masked = masked "x" }
    } else {
      if (c == "'" || c == "\"" || c == "`") { instr = 1; qchar = c; masked = masked c }
      else if (c == "{") { depth++; masked = masked c }
      else if (c == "}") {
        depth--; masked = masked c
        if (depth == 0) {
          done_flag = 1
          print "FOUND"
          print "===RAW==="
          print raw
          print "===MASKED==="
          print masked
          exit 0
        }
      } else { masked = masked c }
    }
  }
  if (state == "capture") { raw = raw "\n"; masked = masked "\n" }
}
END {
  # `exit` above still runs END — done_flag is how the success path avoids
  # printing a second, contradictory verdict here.
  if (done_flag) { }
  else if (found) print "UNCLOSED"
  else print "NOTFOUND"
}
AWK_EOF

extract_meta_block() {  # extract_meta_block <file> -> see AWK_EOF header above
  awk -f "${AWK_SCRIPT}" "$1"
}

# scan_masked <masked-block-text>
#
# Squashes the block to one line (a colon and its value can legally span a
# line break — `whenToUse:\n  'text'` is how the real file is formatted) and
# emits one "      <NodeType>: ..." line per disallowed construct found.
# Silent (no output) means the block is a pure literal.
scan_masked() {
  local masked="$1" flat
  flat="$(printf '%s\n' "${masked}" | tr '\n' ' ' | tr -s ' ')"

  [[ "${flat}" == *'`'* ]] &&
    printf '      TemplateLiteral: a backtick-delimited string is present in meta\n'
  [[ "${flat}" == *'+'* ]] &&
    printf '      BinaryExpression: a `+` operator is present outside any string literal\n'
  [[ "${flat}" == *'...'* ]] &&
    printf '      SpreadElement: `...` is present outside any string literal\n'
  { [[ "${flat}" == *'('* ]] || [[ "${flat}" == *')'* ]]; } &&
    printf '      CallExpression: a parenthesis is present outside any string literal\n'

  # G5: `grep` exit 1 means "looked, matched nothing", which is the healthy
  # case here. Anything above 1 means it could not look at all, and a `|| true`
  # that folds the two together turns a broken scan into a clean bill of
  # health. Fail the file instead — emitting a violation line is how this
  # function says no.
  local ids ids_rc
  ids="$(printf '%s' "${flat}" |
    grep -Eo ':[[:space:]]*[A-Za-z_$][A-Za-z0-9_$]*[[:space:]]*[,}]')"
  ids_rc=$?
  if [[ "${ids_rc}" -gt 1 ]]; then
    printf '      internal error: the bare-identifier scan could not run (grep exit %d)\n' "${ids_rc}"
    return 0
  fi

  local match word
  while IFS= read -r match; do
    [[ -n "${match}" ]] || continue
    word="$(printf '%s' "${match}" | sed -E 's/^:[[:space:]]*//; s/[[:space:]]*[,}]$//')"
    case "${word}" in
      true | false | null) ;;
      *)
        printf '      Identifier: bare identifier `%s` in value position\n' "${word}"
        ;;
    esac
  done <<< "${ids}"
}

# check_file <path>
#
# Prints a one-line verdict plus any violation reasons; returns 0 on a pure
# literal, 1 otherwise.
check_file() {
  local file="$1" label out status masked violations
  label="${file#"${ROOT}"/}"
  out="$(extract_meta_block "${file}")"
  status="$(printf '%s\n' "${out}" | head -n1)"

  case "${status}" in
    NOTFOUND)
      printf '  %-46s FAILED\n' "${label}"
      printf '      no `export const meta = { ... }` block found\n'
      return 1
      ;;
    UNCLOSED)
      printf '  %-46s FAILED\n' "${label}"
      printf '      meta block opened but never closed (brace/quote mismatch)\n'
      return 1
      ;;
    FOUND)
      masked="$(printf '%s\n' "${out}" | awk '/^===MASKED===$/{f=1;next} f{print}')"
      violations="$(scan_masked "${masked}")"
      if [[ -n "${violations}" ]]; then
        printf '  %-46s FAILED\n' "${label}"
        printf '%s\n' "${violations}"
        return 1
      fi
      printf '  %-46s ok\n' "${label}"
      return 0
      ;;
    *)
      printf '  %-46s FAILED\n' "${label}"
      printf '      internal error: unrecognized extractor status %s\n' "${status}"
      return 1
      ;;
  esac
}

# scan_workflows [dir]
#
# Checks every `<dir>/*.js`; defaults to `workflows/` at the repo root.
# Exits non-zero when zero files are scanned (DF-59): a checker that exits 0
# on an empty input set is a gate that cannot fail.
scan_workflows() {
  local dir="${1:-${ROOT}/workflows}" files=() f failures=0

  shopt -s nullglob
  files=("${dir}"/*.js)
  shopt -u nullglob

  if [[ "${#files[@]}" -eq 0 ]]; then
    printf '::error::no *.js files found under %s — a checker that scans nothing cannot fail (DF-59).\n' "${dir}" >&2
    return 1
  fi

  printf 'checking %d workflow file(s) for a pure-literal `meta` block:\n\n' "${#files[@]}"
  for f in "${files[@]}"; do
    check_file "${f}" || failures=$((failures + 1))
  done

  printf '\n'
  if [[ "${failures}" -gt 0 ]]; then
    printf '::error::%d of %d workflow file(s) failed the pure-literal meta check.\n' "${failures}" "${#files[@]}"
    return 1
  fi
  printf 'ok: all %d workflow file(s) carry a pure-literal `meta` block.\n' "${#files[@]}"
  return 0
}

# self_test
#
# The point of this script. Three mandatory controls plus one DF-59 pin:
#   NEGATIVE          — the checked-in concatenated form must be REJECTED, and
#                        the stated reason must name the concatenation itself
#                        (`BinaryExpression`), not some unrelated parse
#                        failure. The corpus is a tracked fixture, not a
#                        commit pulled back out of git history — the fixture's
#                        own header records why archaeology cannot be a
#                        control.
#   POSITIVE          — the current shipped workflows/wave.js must PASS.
#   FALSE-POSITIVE     — a description legitimately containing `+ ( ) '`
#                        must PASS (the regression pin for the bug this run
#                        already hit once).
#   ZERO-FILES (DF-59) — scanning an empty directory must exit non-zero.
# A control that cannot fail is not proof of anything; each is graded on
# whether the gate behaved as the control demands, not on vibes. The number of
# controls actually run is reported and refused when zero (G4): a self-test
# that silently runs nothing is the same defect one level up.
self_test() {
  printf 'self-test: prove the gate can both FAIL and PASS\n\n'
  local fails=0 controls=0 tmp

  tmp="$(mktemp -d -t check-workflow-meta-selftest.XXXXXX)"
  TMP_DIRS+=("${tmp}")

  # --- NEGATIVE control -----------------------------------------------------
  #
  # The corpus is a tracked file that deliberately carries the `+`-concatenated
  # `whenToUse` this gate exists to catch. Reading it costs nothing and works in
  # a shallow CI checkout; recovering the same bytes from an old commit works in
  # neither — `actions/checkout` defaults to `fetch-depth: 1`, and the object is
  # already absent from this clone.
  #
  # Rejection alone is not enough. A fixture rejected because it failed to parse,
  # or for some construct other than the concatenation, is a vacuous control: it
  # would keep printing PASS long after the `+` check itself broke. So the REASON
  # is asserted too, and it must be `BinaryExpression`.
  controls=$((controls + 1))
  local negative="${ROOT}/hooks/tests/fixtures/df69-concatenated-meta.js"
  local neg_out neg_rc neg_reason neg_grep_rc
  if [[ ! -f "${negative}" ]]; then
    printf '  FAIL  NEGATIVE control: the corpus fixture is missing: %s\n' "${negative}"
    fails=$((fails + 1))
  else
    neg_out="$(check_file "${negative}" 2>&1)"
    neg_rc=$?
    # G5 again: 0 found, 1 looked-and-absent, >1 could-not-look. The last of
    # those must not be reported as either of the first two.
    neg_reason="$(printf '%s\n' "${neg_out}" | grep -F -- 'BinaryExpression')"
    neg_grep_rc=$?
    if [[ "${neg_rc}" -eq 0 ]]; then
      printf '  FAIL  NEGATIVE control: the concatenated `whenToUse` fixture was ACCEPTED — the gate cannot fire\n'
      fails=$((fails + 1))
    elif [[ "${neg_grep_rc}" -gt 1 ]]; then
      printf '  FAIL  NEGATIVE control: could not inspect the rejection reason (grep exit %d)\n' "${neg_grep_rc}"
      fails=$((fails + 1))
    elif [[ "${neg_grep_rc}" -ne 0 ]]; then
      printf '  FAIL  NEGATIVE control: the fixture was rejected, but NOT for its concatenation:\n'
      printf '%s\n' "${neg_out}" | sed 's/^/        /'
      fails=$((fails + 1))
    else
      printf '  PASS  NEGATIVE control: the concatenated `whenToUse` fixture is REJECTED, for the concatenation:\n'
      printf '%s\n' "${neg_reason}" | sed 's/^[[:space:]]*/        /'
    fi
  fi

  # --- POSITIVE control ------------------------------------------------------
  controls=$((controls + 1))
  local shipped="${ROOT}/workflows/wave.js"
  if [[ ! -f "${shipped}" ]]; then
    printf '  FAIL  POSITIVE control: %s does not exist\n' "${shipped}"
    fails=$((fails + 1))
  elif check_file "${shipped}" >/dev/null 2>&1; then
    printf '  PASS  POSITIVE control: the current workflows/wave.js meta block is a pure literal\n'
  else
    printf '  FAIL  POSITIVE control: the current workflows/wave.js meta block was REJECTED:\n'
    check_file "${shipped}" | sed 's/^/        /'
    fails=$((fails + 1))
  fi

  # --- FALSE-POSITIVE GUARD ---------------------------------------------------
  controls=$((controls + 1))
  local falsepos="${tmp}/falsepos.js"
  cat >"${falsepos}" <<'FIXTURE_EOF'
export const meta = {
  name: 'demo',
  description: "Use A + B (or C) — don't skip it",
  whenToUse: 'demo only, never dispatched',
  phases: [],
}
FIXTURE_EOF
  if check_file "${falsepos}" >/dev/null 2>&1; then
    printf "  PASS  FALSE-POSITIVE GUARD: a description containing + ( ) and an apostrophe passes\n"
  else
    printf '  FAIL  FALSE-POSITIVE GUARD: a legitimate description string was rejected:\n'
    check_file "${falsepos}" | sed 's/^/        /'
    fails=$((fails + 1))
  fi

  # --- ZERO-FILES guard (DF-59 / G4) ------------------------------------------
  controls=$((controls + 1))
  local empty_dir="${tmp}/empty-workflows"
  mkdir -p "${empty_dir}"
  if scan_workflows "${empty_dir}" >/dev/null 2>&1; then
    printf '  FAIL  ZERO-FILES guard (DF-59): an empty scan set exited 0\n'
    fails=$((fails + 1))
  else
    printf '  PASS  ZERO-FILES guard (DF-59): an empty scan set exits non-zero\n'
  fi

  printf '\n'
  # G4: say how many things were checked, and refuse when that number is zero.
  # A self-test that runs no controls is the same shape of lie as a checker that
  # scans no files.
  if [[ "${controls}" -eq 0 ]]; then
    printf '::error::the self-test ran 0 controls — a self-test that checks nothing cannot fail.\n'
    return 1
  fi
  if [[ "${fails}" -gt 0 ]]; then
    printf '::error::%d of %d self-test control(s) failed — the gate is not trustworthy.\n' "${fails}" "${controls}"
    return 1
  fi
  printf 'ok: all %d self-test control(s) behaved as designed.\n' "${controls}"
  return 0
}

main() {
  if [[ "${1:-}" == "--self-test" ]]; then
    self_test
    return $?
  fi
  scan_workflows
  return $?
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
  exit $?
fi
