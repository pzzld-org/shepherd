#!/usr/bin/env bash
# test_cmd_issues.sh — regression suite for `shctx issues classify` (W8R-R4).
#
# W8R-R4 fixed two related defects in cmd_issues.sh with NO regression test in
# the tree (verified only by an ad hoc harness never committed). This suite
# closes that gap and covers BOTH halves of the fix:
#
#   1. DEFAULT bucket — with no [ledger].non_issue_labels configured, the
#      hardcoded fallback (_DEFAULT_NON_ISSUE_LABELS) must match the
#      documented default in docs/configuration.md §[ledger] EXACTLY:
#      ["wontfix","tracking-future","design-question","rfc"]. The pre-fix
#      default (deferred/wontfix/won't fix/invalid/duplicate/question)
#      disagreed with the doc it claimed to implement — "deferred" is the
#      control label here: present in the OLD buggy default, absent from the
#      documented one, so it must NOT land in labeled-non-issue.
#
#   2. SINGLE-LINE override — `non_issue_labels = ["a","b"]` on one line must
#      take effect and REPLACE (not merge with) the default.
#
#   3. MULTI-LINE override — the idiomatic
#        non_issue_labels = [
#          "a",
#          "b",
#        ]
#      form must ALSO take effect. Pre-fix, cfg_section_get (a single-line
#      awk reader) read only the "[" opening line of a multi-line array and
#      returned that alone; _non_issue_labels_from_toml() then treated the
#      truncated "[" as an empty/unset override and silently fell back to the
#      default — the exact "documented override no-ops silently" bug this
#      suite exists to pin. The override labels below ("quarantine-em",
#      "shelved") appear in NEITHER the old nor the new hardcoded default, so
#      a regression to the silent-fallback behavior cannot hide behind
#      accidental overlap with either default list.
#
# cmd_issues.sh hard-requires bash >= 4 (own top-of-file gate) even though its
# classify logic is itself bash-3.2-safe — macOS ships bash 3.2 by default, so
# this suite discovers a qualifying bash4+ interpreter (Homebrew, a Cellar
# install, or a Nix store one) and puts it first on PATH for the duration of
# the run, exactly the way the tool's own error message ("brew install bash,
# then re-run via the brewed bash") tells an operator to. No qualifying
# interpreter found anywhere on the box → SKIP (exit 0, matching the
# established python3-missing skip convention in test_cmd_signal.sh), not
# FAIL: a missing bash4+ is an environment gap in a prerequisite of the
# command under test, not a defect in this suite.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"

command -v sqlite3 >/dev/null || { echo "skip: sqlite3 not installed"; exit 0; }
command -v jq      >/dev/null || { echo "skip: jq not installed"; exit 0; }
command -v python3 >/dev/null || { echo "skip: python3 not installed (classify --json needs it)"; exit 0; }

# ---------------------------------------------------------------------------
# bash4+ discovery (see header). Tries PATH first (already qualifying on any
# non-macOS runner), then well-known Homebrew locations, then a Cellar/Nix
# store scan as a last resort for a sandboxed dev box with neither on PATH.
# ---------------------------------------------------------------------------
_find_bash4() {
  local c
  for c in "$(command -v bash 2>/dev/null || true)" \
           /opt/homebrew/bin/bash /usr/local/bin/bash /usr/bin/bash /bin/bash; do
    [[ -n "$c" && -x "$c" ]] || continue
    if "$c" -c '[[ ${BASH_VERSINFO[0]} -ge 4 ]]' 2>/dev/null; then
      printf '%s' "$c"; return 0
    fi
  done
  local d
  for d in /opt/homebrew/Cellar/bash/*/bin/bash /usr/local/Cellar/bash/*/bin/bash \
           /nix/store/*/bin/bash; do
    [[ -x "$d" ]] || continue
    if "$d" -c '[[ ${BASH_VERSINFO[0]} -ge 4 ]]' 2>/dev/null; then
      printf '%s' "$d"; return 0
    fi
  done
  return 1
}

BASH4=""
BASH4="$(_find_bash4 2>/dev/null)" || true
if [[ -z "$BASH4" ]]; then
  echo "skip: no bash 4+ interpreter found (cmd_issues.sh requires one — install via 'brew install bash')"
  echo "PASS: test_cmd_issues (skipped — environment missing bash4+)"
  exit 0
fi

shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# Prepend a `bash` shim resolving to the discovered bash4+ so both the shctx
# dispatcher's shebang (`#!/usr/bin/env bash`) and its internal
# `bash "$impl" "$@"` re-dispatch land on it.
BASH4BIN="$SHCTX_TEST_TMP/.bash4bin"
mkdir -p "$BASH4BIN"
ln -sf "$BASH4" "$BASH4BIN/bash"
export PATH="$BASH4BIN:$PATH"

# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------
_insert_issue() {
  # Args: db project_id row_id number title labels_json
  local db="$1" pid="$2" iid="$3" num="$4" title="$5" labels="$6"
  sqlite3 "$db" "INSERT INTO index_issues VALUES
    ('$iid','$pid','github',$num,'$title','open','$labels',NULL,'[]','b','u',1,1,1);"
}

_bucket_of() {
  # Args: classify --json output, issue number → prints that issue's bucket.
  printf '%s' "$1" | jq -r --argjson n "$2" '.[] | select(.number==$n) | .bucket'
}

_new_repo() {
  # Stand up an isolated repo + `shctx init` under a fresh mktemp dir, echoing
  # its path. Separate from $SHCTX_TEST_TMP so each override scenario gets its
  # own untouched (or independently configured) shepherd.toml.
  local dir; dir="$(mktemp -d)"
  ( cd "$dir" && git init -q . && git config user.email t@t && git config user.name t \
      && echo test > README.md && git add README.md && git commit -qm init \
      && "$SHCTX" init >/dev/null 2>&1 ) || { echo "FAIL: repo setup failed in $dir" >&2; exit 1; }
  printf '%s' "$dir"
}

# ---------------------------------------------------------------------------
# 1. DEFAULT — no [ledger].non_issue_labels configured anywhere
# ---------------------------------------------------------------------------
"$SHCTX" init >/dev/null 2>&1
db1="$SHCTX_TEST_TMP/.shepherd/shepherd.db"
pid1="$(jq -r .id "$SHCTX_TEST_TMP/.shepherd/project.json")"

_insert_issue "$db1" "$pid1" "i-wontfix" 2001 "wontfix-issue"         '["wontfix"]'
_insert_issue "$db1" "$pid1" "i-trackf"  2002 "tracking-future-issue" '["tracking-future"]'
_insert_issue "$db1" "$pid1" "i-designq" 2003 "design-question-issue" '["design-question"]'
_insert_issue "$db1" "$pid1" "i-rfc"     2004 "rfc-issue"             '["rfc"]'
_insert_issue "$db1" "$pid1" "i-deferred" 2005 "deferred-issue"       '["deferred"]'

out1="$("$SHCTX" issues classify --json)"
assert_eq "default.wontfix"         "$(_bucket_of "$out1" 2001)" "labeled-non-issue"
assert_eq "default.tracking-future" "$(_bucket_of "$out1" 2002)" "labeled-non-issue"
assert_eq "default.design-question" "$(_bucket_of "$out1" 2003)" "labeled-non-issue"
assert_eq "default.rfc"             "$(_bucket_of "$out1" 2004)" "labeled-non-issue"
assert_eq "default.deferred-not-swept" "$(_bucket_of "$out1" 2005)" "unclassified"

# ---------------------------------------------------------------------------
# 2. SINGLE-LINE override
# ---------------------------------------------------------------------------
TMP2="$(_new_repo)"
db2="$TMP2/.shepherd/shepherd.db"
pid2="$(jq -r .id "$TMP2/.shepherd/project.json")"
printf '[ledger]\nnon_issue_labels = ["a","b"]\n' > "$TMP2/.shepherd/shepherd.toml"

_insert_issue "$db2" "$pid2" "i-a"       3001 "a-issue"       '["a"]'
_insert_issue "$db2" "$pid2" "i-wontfix" 3002 "wontfix-issue" '["wontfix"]'

out2="$(cd "$TMP2" && "$SHCTX" issues classify --json)"
assert_eq "single-line.override-applies"   "$(_bucket_of "$out2" 3001)" "labeled-non-issue"
assert_eq "single-line.default-overridden" "$(_bucket_of "$out2" 3002)" "unclassified"
rm -rf "$TMP2"

# ---------------------------------------------------------------------------
# 3. MULTI-LINE override (the idiomatic form — the historical regression)
# ---------------------------------------------------------------------------
TMP3="$(_new_repo)"
db3="$TMP3/.shepherd/shepherd.db"
pid3="$(jq -r .id "$TMP3/.shepherd/project.json")"
cat > "$TMP3/.shepherd/shepherd.toml" <<'TOML'
[ledger]
non_issue_labels = [
  "quarantine-em",
  "shelved",
]
TOML

_insert_issue "$db3" "$pid3" "i-q"       4001 "quarantine-issue" '["quarantine-em"]'
_insert_issue "$db3" "$pid3" "i-wontfix" 4002 "wontfix-issue"    '["wontfix"]'

out3="$(cd "$TMP3" && "$SHCTX" issues classify --json)"
assert_eq "multi-line.override-applies"   "$(_bucket_of "$out3" 4001)" "labeled-non-issue"
assert_eq "multi-line.default-overridden" "$(_bucket_of "$out3" 4002)" "unclassified"
rm -rf "$TMP3"

echo "test_cmd_issues: all assertions passed"
