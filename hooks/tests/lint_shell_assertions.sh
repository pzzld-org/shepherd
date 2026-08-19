#!/usr/bin/env bash
# hooks/tests/lint_shell_assertions.sh — bans bare shell assertions in
# hooks/** and scripts/** (v651 L7-S1, issues #318 + #340).
#
# WHY this exists (two independent, already-shipped defects):
#
#   #318 -- a bare `rg -Fq PATTERN FILE` prints nothing on no-match. Under
#   `set -e` the script simply dies: no diagnostic, no requirement named,
#   just a dead script and an operator with no idea why it stopped.
#
#   #340 -- bash 3.2 (macOS's shipped, un-upgradeable `/bin/bash`) does NOT
#   honour `set -e` for a failing `[[ ]]`/`(( ))` compound command; bash 5.2
#   does:
#
#     $ /bin/bash -c 'set -e; [[ 2 -eq 3 ]]; echo SURVIVED'  -> SURVIVED, rc=0
#     $ /bin/bash -c 'set -e; false;        echo SURVIVED'   -> rc=1
#
#   That gap hid a false assertion for two releases:
#   scripts/tests/test-release-workflow.sh:270 asserted `-eq 3` against a
#   real count of 2 since v6.4.6, and no macOS dev shell ever saw it fail.
#
# CLASSIFIER: this script ports the ground-truth classifier at
# .shepherd/runs/v651/lanes/l7-assertions/evidence/classify.py (see that
# file's header for the full rule-by-rule rationale). Summary:
#   R1 line-initial only -- `foo && [[ x ]]` is already guarded by its own
#      operator; only a statement that OPENS the line is a candidate.
#   R2 match the CLOSING token, then test the TAIL after it. Scanning the
#      whole line for `&&`/`||` misses every `[[ -n "$a" && -f "$b" ]]` --
#      this repo's house idiom puts the operator INSIDE the brackets. A
#      whole-line scan undercounted in root's first survey and again in an
#      l11 implementer's self-lint; matching the closing token first is
#      what fixes it.
#   R3 a non-empty tail (`&& ...`, `|| ...`, `; ...`) or a trailing `\`
#      means the statement is guarded or continued. Not bare.
#   R4 EXCLUSION -- function-return position. A test whose next non-blank,
#      non-comment line is `}` is the function's RETURN VALUE, not an
#      assertion. hooks/scripts/_lib.sh:120 (is_shepherd_project), :369
#      (quiet_warnings), and :450 (in_subworktree) are exactly this shape;
#      "fixing" them would turn a boolean predicate's false branch into a
#      hard exit and break every caller -- quiet_warnings defaults to false
#      and a hard exit there would kill every hook whenever the operator
#      has not set it.
#
# Quoted spans are masked before any of the above runs, or a `]]`/`)` inside
# a string reads as a close (scripts/tests/test-release-installer-
# powershell-contract.sh:21's search pattern contains a literal `if ` --
# whole-line scanning is the class of bug that trips on; masking prevents it
# here the same way it does in the reference classifier).
#
# hooks/tests/fixtures/assertion-hygiene/ is excluded from the production
# scan by path prefix: bare_reference.sh in that directory deliberately
# contains one of each banned shape as a committed reference, and a lint
# that flags its own fixtures is unshippable.
#
# python3 is shelled out to for the same reason 7 sibling tests in this
# directory already do (test_loc_count.sh, test_description_budget.sh,
# test_registered_hooks_no_python.sh, ...): bracket-depth matching with
# quote-masking is not something bash 3.2 does cleanly, and python3 is an
# established dependency here.
#
# Bash 3.2 safe: no ${var,,}, no mapfile, no declare -A.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
FIXTURE_DIR="$HERE/fixtures/assertion-hygiene"
FIXTURE_PREFIX="hooks/tests/fixtures/assertion-hygiene"

checks=0
fails=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s -- %s\n' "$1" "$2" >&2; fails=$((fails + 1)); }

finish() {
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  if [[ "$fails" -eq 0 ]]; then
    printf 'PASS: lint_shell_assertions\n'
    exit 0
  fi
  printf 'FAIL: lint_shell_assertions (%d)\n' "$fails" >&2
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  printf 'SKIP: python3 is required by lint_shell_assertions\n'
  exit 0
fi

if [[ ! -f "$FIXTURE_DIR/clean.sh" || ! -f "$FIXTURE_DIR/bare_reference.sh" ]]; then
  printf 'FAIL: lint_shell_assertions -- fixtures missing under %s\n' "$FIXTURE_DIR" >&2
  exit 1
fi

WORKDIR="$(mktemp -d -t shep-assertion-lint.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

# =============================================================================
# The classifier, ported from classify.py's classify()/strip_quotes()/
# find_close()/next_code_line() verbatim, plus a --exclude path-prefix
# filter this lint needs that the reference tool does not. Written once to
# $WORKDIR and invoked many times below (fixtures, real tree, empty dir);
# never runs against the tracked tree in place -- every scan target passed
# to it is either a read-only tracked path or a $TMPDIR copy.
# =============================================================================

CLASSIFIER="$WORKDIR/classify_port.py"
cat > "$CLASSIFIER" <<'PYEOF'
import re, sys, pathlib

OPEN = {'[[': ']]', '((': '))'}
RG = re.compile(r'^rg\s+(-[A-Za-z]+\s+)*-[A-Za-z]*q')


def strip_quotes(s):
    """Blank out quoted spans so a `]]` inside a string is not read as a close."""
    out, i, q = [], 0, None
    while i < len(s):
        c = s[i]
        if q:
            if c == '\\' and q == '"':
                out.append('  '); i += 2; continue
            out.append(' ' if c != q else c)
            if c == q:
                q = None
            i += 1
        else:
            if c in '"\'':
                q = c; out.append(c)
            elif c == '\\':
                out.append('  '); i += 2; continue
            else:
                out.append(c)
            i += 1
    return ''.join(out)


def find_close(masked, start, close):
    depth, i = 0, start
    tok = masked[start:start + 2]
    while i < len(masked) - 1:
        two = masked[i:i + 2]
        if two == tok:
            depth += 1; i += 2; continue
        if two == close:
            depth -= 1
            if depth == 0:
                return i + 2
            i += 2; continue
        i += 1
    return -1


def next_code_line(lines, idx):
    for j in range(idx + 1, len(lines)):
        t = lines[j].strip()
        if t and not t.startswith('#'):
            return t
    return ''


def classify(path):
    lines = pathlib.Path(path).read_text(errors='replace').split('\n')
    hits = []
    for n, raw in enumerate(lines):
        body = raw.strip()
        if not body or body.startswith('#'):
            continue
        masked = strip_quotes(body)
        kind = tail = None
        for op, cl in OPEN.items():
            if body.startswith(op):
                end = find_close(masked, 0, cl)
                if end < 0:
                    break
                kind, tail = op, body[end:].strip()
                break
        else:
            if RG.match(body):
                kind, tail = 'rg', ''
                m = re.search(r'(\|\||&&|\||;)', masked)
                if m:
                    tail = body[m.start():].strip()
        if kind is None:
            continue
        if tail:                                   # R3 guarded / chained
            continue
        if body.endswith('\\'):                    # R3 continued
            continue
        if next_code_line(lines, n) == '}':        # R4 function return value
            hits.append((n + 1, kind, body, 'RETURN'))
            continue
        hits.append((n + 1, kind, body, 'BARE'))
    return hits


def main():
    args = sys.argv[1:]
    roots, excludes = [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--exclude':
            i += 1
            excludes.append(args[i])
        else:
            roots.append(a)
        i += 1
    if not roots:
        roots = ['hooks', 'scripts']

    files = sorted(p for r in roots for p in pathlib.Path(r).rglob('*.sh'))
    files = [f for f in files if not any(str(f).startswith(ex) for ex in excludes)]

    res = {}
    for f in files:
        h = classify(f)
        if h:
            res[str(f)] = h
    bare = [(f, l, k, b) for f, hs in res.items() for l, k, b, v in hs if v == 'BARE']
    ret = [(f, l, k, b) for f, hs in res.items() for l, k, b, v in hs if v == 'RETURN']

    print('FILES_SCANNED=%d' % len(files))
    print('BARE_TOTAL=%d' % len(bare))
    print('BARE_BRACKET=%d' % len([x for x in bare if x[2] in ('[[', '((')]))
    print('BARE_RG=%d' % len([x for x in bare if x[2] == 'rg']))
    print('EXCLUDED_RETURN=%d' % len(ret))
    print('---BARE---')
    for f, l, k, b in bare:
        print('%s:%d\t%s\t%s' % (f, l, k, b))
    print('---EXCLUDED---')
    for f, l, k, b in ret:
        print('%s:%d\t%s\t%s' % (f, l, k, b))


if __name__ == '__main__':
    main()
PYEOF

# run_classifier OUT_FILE EXCLUDE_PREFIX_OR_EMPTY ROOT...
# Always runs with cwd=REPO_ROOT so relative roots resolve exactly like
# classify.py's own `roots = sys.argv[1:] or ['hooks', 'scripts']` usage.
run_classifier() {
  local out="$1" exclude="$2"
  shift 2
  if [[ -n "$exclude" ]]; then
    (cd "$REPO_ROOT" && python3 "$CLASSIFIER" --exclude "$exclude" "$@") > "$out" 2>"$out.err"
  else
    (cd "$REPO_ROOT" && python3 "$CLASSIFIER" "$@") > "$out" 2>"$out.err"
  fi
}

# metric OUT_FILE KEY — read one FILES_SCANNED=/BARE_TOTAL=/... line.
metric() {
  awk -F= -v k="$2" '$1==k{print $2; exit}' "$1"
}

# section OUT_FILE MARKER — print the lines between a `---MARKER---` header
# and the next `---` header (or EOF).
section() {
  awk -v m="---$2---" 'BEGIN{f=0} $0==m{f=1;next} /^---/{f=0} f' "$1"
}

# require_nonempty_scan FILES_SCANNED LABEL — the actual gate predicate
# (constraint G3/G4: a gate that scans nothing and reports success is the
# exact failure this repo has hit repeatedly). Returns failure (1) when
# FILES_SCANNED is 0. Part B calls this against a target guaranteed to be
# empty to prove the predicate trips; Part E calls the SAME function
# against the real tree, so both paths share one implementation rather than
# two copies that could drift apart.
require_nonempty_scan() {
  local n="$1" label="$2"
  if [[ "$n" -eq 0 ]]; then
    printf '    %s: FILES_SCANNED=0 -- empty scan set\n' "$label" >&2
    return 1
  fi
  return 0
}

# =============================================================================
# Part A — fixture-based two-sided falsification (independent of the tree's
# current state; passes standalone regardless of whether scripts/tests/*.sh
# conversions have landed yet).
# =============================================================================

printf '  -- Part A: two-sided falsification against the CLEAN fixture --\n'

CLEAN_SRC="$FIXTURE_DIR/clean.sh"

# --- baseline side: the unmutated fixture must be CLEAN for the rule -------
# Scanned alone (its own directory, not the whole fixtures dir) because
# bare_reference.sh — this fixture's sibling — deliberately contains real
# bare sites; Part D exercises that file on its own terms.
clean_out="$WORKDIR/clean_only.txt"
mkdir -p "$WORKDIR/clean_only_dir"
cp "$CLEAN_SRC" "$WORKDIR/clean_only_dir/clean.sh"
run_classifier "$clean_out" "" "$WORKDIR/clean_only_dir"
clean_files="$(metric "$clean_out" FILES_SCANNED)"
clean_bare="$(metric "$clean_out" BARE_TOTAL)"
clean_ret="$(metric "$clean_out" EXCLUDED_RETURN)"
printf '    baseline (clean.sh alone): files_scanned=%s bare_total=%s excluded_return=%s (expect 1, 0, 2)\n' \
  "$clean_files" "$clean_bare" "$clean_ret"
if [[ "$clean_files" -eq 1 && "$clean_bare" -eq 0 && "$clean_ret" -eq 2 ]]; then
  pass "baseline side: the unmutated clean fixture is CLEAN for the rule (BARE_TOTAL=0, 2 function-return exclusions)"
else
  fail "baseline side: the unmutated clean fixture is CLEAN for the rule" \
    "files=$clean_files bare_total=$clean_bare excluded_return=$clean_ret"
fi

# --- explicit guarded-inline-operator case: NOT flagged --------------------
if section "$clean_out" BARE | grep -qF 'check_inputs'; then
  fail "guarded [[ -n \"\$a\" && -f \"\$b\" ]] || { ...; } is NOT flagged" "found in BARE section"
else
  pass "guarded [[ -n \"\$a\" && -f \"\$b\" ]] || { ...; } is NOT flagged (inside-operator case, R2/R3)"
fi

# --- explicit function-return case: NOT flagged, IS excluded ---------------
if section "$clean_out" BARE | grep -qF 'is_shepherd_project'; then
  fail "function-return [[ ]] before } is NOT flagged as BARE" "found in BARE section"
else
  pass "function-return [[ ]] before } is NOT flagged as BARE (the _lib.sh case)"
fi
if section "$clean_out" EXCLUDED | grep -qF -- '-n "$ns" && -f "$ns/shepherd.toml"'; then
  pass "function-return [[ -n \"\$ns\" && -f ... ]] before } is excluded as RETURN"
else
  fail "function-return case appears in the EXCLUDED (RETURN) section" "not found"
fi

# --- injected mutations: one bare statement appended per case --------------
inject_case_dir() {
  # inject_case_dir NAME LINE — copy clean.sh into its own $WORKDIR
  # subdirectory and append LINE at end of file (so its next-code-line is
  # empty, never `}` — guaranteeing BARE, not RETURN, classification).
  local name="$1" line="$2" dir="$WORKDIR/inject_${name}"
  mkdir -p "$dir"
  cp "$CLEAN_SRC" "$dir/clean.sh"
  printf '\n%s\n' "$line" >> "$dir/clean.sh"
  printf '%s' "$dir"
}

check_injected() {
  # check_injected LABEL NAME LINE EXPECT_KIND
  local label="$1" name="$2" line="$3" expect_kind="$4"
  local dir out bare kind_count
  dir="$(inject_case_dir "$name" "$line")"
  out="$WORKDIR/inject_${name}.txt"
  run_classifier "$out" "" "$dir"
  bare="$(metric "$out" BARE_TOTAL)"
  printf '    %s: bare_total=%s (expect 1)\n' "$label" "$bare"
  if [[ "$bare" -eq 1 ]] && section "$out" BARE | grep -qF "$line"; then
    pass "$label -> flagged"
  else
    fail "$label -> flagged" "bare_total=$bare; section: $(section "$out" BARE)"
  fi
}

check_injected 'injected bare [[ ]]' bracket '[[ -f "$config" ]]' '[['
check_injected 'injected bare (( ))' paren '(( count > 0 ))' '(('
check_injected 'injected bare rg -Fq' rgfq "rg -Fq 'TOKEN' \"\$file\"" rg
check_injected 'injected bare rg -q' rgq "rg -q 'TOKEN' \"\$file\"" rg

# =============================================================================
# Part B — empty scan set must be a hard failure (constraint G3/G4: a gate
# that scans nothing and reports success is the exact failure this repo has
# hit repeatedly). Independent of Part A's fixtures.
# =============================================================================

printf '  -- Part B: empty scan set is a hard failure --\n'

empty_dir="$WORKDIR/empty_scan_target"
mkdir -p "$empty_dir"
empty_out="$WORKDIR/empty.txt"
run_classifier "$empty_out" "" "$empty_dir"
empty_files="$(metric "$empty_out" FILES_SCANNED)"
printf '    empty dir: files_scanned=%s\n' "$empty_files"
if [[ "$empty_files" -eq 0 ]]; then
  pass "classifier reports FILES_SCANNED=0 for an empty scan target"
else
  fail "classifier reports FILES_SCANNED=0 for an empty scan target" "files_scanned=$empty_files"
fi

# The actual gate predicate (require_nonempty_scan, also used by Part E's
# real enforcement below) must itself return failure for this target -- not
# just report a metric that a caller could still ignore.
if require_nonempty_scan "$empty_files" "empty-dir probe" 2>"$WORKDIR/empty_guard.err"; then
  fail "require_nonempty_scan() returns failure for an empty scan target" \
    "returned success (0) for files_scanned=$empty_files"
else
  pass "require_nonempty_scan() returns failure (hard failure) for an empty scan target"
fi

# =============================================================================
# Part C — hooks/scripts/_lib.sh:120,369,450 must report clean (RETURN, not
# BARE). This runs against the REAL tracked file, not a fixture -- it is
# stable regardless of the concurrent scripts/tests/*.sh conversions since
# hooks/scripts/_lib.sh is outside that scope.
# =============================================================================

printf '  -- Part C: hooks/scripts/_lib.sh function-return sites report clean --\n'

lib_out="$WORKDIR/lib.txt"
run_classifier "$lib_out" "" "hooks/scripts"
for line in 120 369 450; do
  if section "$lib_out" BARE | grep -q "^hooks/scripts/_lib\.sh:${line}"; then
    fail "hooks/scripts/_lib.sh:$line reports clean" "found in BARE section"
  elif section "$lib_out" EXCLUDED | grep -q "^hooks/scripts/_lib\.sh:${line}"; then
    pass "hooks/scripts/_lib.sh:$line reports clean (RETURN, excluded from conversion)"
  else
    fail "hooks/scripts/_lib.sh:$line reports clean" "not found in either section -- classifier disagreement"
  fi
done

# =============================================================================
# Part D — the fixtures-directory exclusion actually does work: scanning
# bare_reference.sh directly must flag all 4 shapes, and scanning the real
# tree WITH the exclusion applied must contribute zero hits from this
# directory.
# =============================================================================

printf '  -- Part D: fixtures-directory exclusion is not vacuous --\n'

ref_dir="$WORKDIR/bare_reference_only"
mkdir -p "$ref_dir"
cp "$FIXTURE_DIR/bare_reference.sh" "$ref_dir/bare_reference.sh"
ref_out="$WORKDIR/bare_reference.txt"
run_classifier "$ref_out" "" "$ref_dir"
ref_bare="$(metric "$ref_out" BARE_TOTAL)"
ref_bracket="$(metric "$ref_out" BARE_BRACKET)"
ref_rg="$(metric "$ref_out" BARE_RG)"
printf '    bare_reference.sh alone: bare_total=%s bare_bracket=%s bare_rg=%s (expect 4, 2, 2)\n' \
  "$ref_bare" "$ref_bracket" "$ref_rg"
if [[ "$ref_bare" -eq 4 && "$ref_bracket" -eq 2 && "$ref_rg" -eq 2 ]]; then
  pass "the classifier flags all 4 committed bare shapes when pointed at bare_reference.sh directly"
else
  fail "the classifier flags all 4 committed bare shapes" "bare_total=$ref_bare bracket=$ref_bracket rg=$ref_rg"
fi

# =============================================================================
# Part E — the real enforcement: hooks/** and scripts/**, excluding this
# lint's own fixtures directory, must contain zero bare assertions. This IS
# the lint's actual verdict, not a test of the tool.
#
# SEQUENCING (v651 L7-S1): three coders convert scripts/tests/*.sh
# concurrently in sibling worktrees. Until every one of those conversions
# lands, this part MAY fail and list the sites still outstanding -- that is
# expected sequencing, not a bug in this file. That is the whole point of
# building the lint before the conversion finishes: once every site lands,
# this part goes green with zero code changes here.
# =============================================================================

printf '  -- Part E: real-tree enforcement (hooks/**, scripts/**) --\n'

real_out="$WORKDIR/real_tree.txt"
run_classifier "$real_out" "$FIXTURE_PREFIX" hooks scripts
real_files="$(metric "$real_out" FILES_SCANNED)"
real_bare="$(metric "$real_out" BARE_TOTAL)"
real_ret="$(metric "$real_out" EXCLUDED_RETURN)"
printf '    files_scanned=%s bare_total=%s excluded_return=%s\n' "$real_files" "$real_bare" "$real_ret"

# Hand-written literal, deliberately NOT derived from $FIXTURE_PREFIX: if
# FIXTURE_PREFIX itself were ever wrong (typo'd, emptied, pointed at the
# wrong path), reusing it here to check its own effect would trust the
# thing it is supposed to be probing independently and pass for unrelated
# reasons -- root shipped exactly that class of bug in
# hooks/tests/test_plugin_contract.sh (see this file's header falsification
# note). This grep target is independently spelled out so a broken
# FIXTURE_PREFIX still gets caught here.
if section "$real_out" BARE | grep -qF 'tests/fixtures/assertion-hygiene' \
  || section "$real_out" EXCLUDED | grep -qF 'tests/fixtures/assertion-hygiene'; then
  fail "the fixtures-directory exclusion removes it from the real-tree scan" \
    "found a hooks/tests/fixtures/assertion-hygiene path in scan output"
else
  pass "the fixtures-directory exclusion removes it from the real-tree scan (0 contribution from hooks/tests/fixtures/assertion-hygiene)"
fi

if require_nonempty_scan "$real_files" "hooks/**, scripts/**" 2>"$WORKDIR/real_guard.err"; then
  pass "hooks/** and scripts/** scan is non-empty ($real_files files)"
else
  fail "hooks/** and scripts/** scan at least one file" "files_scanned=0 -- pathspec drift? run from the wrong cwd?"
fi

if [[ "$real_bare" -eq 0 ]]; then
  pass "hooks/** and scripts/** contain zero bare assertions"
else
  fail "hooks/** and scripts/** contain zero bare assertions" \
    "$real_bare site(s) still outstanding (see list below) -- expected non-zero until scripts/tests/*.sh conversions land"
  printf '    outstanding bare sites (%s):\n' "$real_bare"
  section "$real_out" BARE | sed 's/^/      /'
fi

finish
