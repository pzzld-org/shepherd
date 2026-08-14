#!/usr/bin/env bash
# hooks/tests/test_sql_escaping.sh — regression test for #285, extended this
# wave (R1-sql-injection, v6.4.5 W14 close remediation) for the proven-live
# sites #295 (cmd_teammate.sh retire/status — mass UPDATE / WHERE-bypass
# read), #291 (cmd_init.sh unescaped dirname — arbitrary SQL execution), #297
# (cmd_report.sh — 5 unescaped CLI flags, UNION-based exfiltration), and #296
# (the broken `${v//\'/\'\'}` idiom recurring in cmd_eval.sh/cmd_prune.sh, plus
# two FURTHER, previously-undocumented broken idioms found while sweeping every
# `skills/context/scripts/*.sh` SQL call site by hand rather than trusting the
# issue list: cmd_query.sh's bind-value escape silently DELETED apostrophes
# instead of doubling them — an unquoted `''` in `${v//\'/''}` is parsed by
# bash as an empty-string literal, not two literal quotes — and
# refresh-artifacts.sh's title-line sed script collapsed the same way via a
# bash single-quote/escape puzzle). Every one of the ~20 files that build SQL
# by raw interpolation now routes through the single `esc()` in `_lib.sh`
# (GH #296's explicit follow-up ask) — see the recurrence guard at the bottom
# of this file for the mechanical enforcement.
#
# `skills/context/scripts/cmd_adapt.sh` and `skills/context/scripts/cmd_loop.sh`
# escaped SQL text literals with the bash parameter-expansion form
# `${v//\'/\'\'}` (each file's `_txt()` helper, both at line 101 pre-fix). That
# form does NOT double a single quote on bash 3.2 — the REPLACEMENT side keeps
# its backslash literally instead of using it purely as an escape marker, so
# one apostrophe becomes four raw characters (`\'\'`) instead of the two SQLite
# wants (`''`). That truncates the SQL string literal early and leaves a bare
# backslash as the next token, which SQLite's parser rejects. Both call sites
# interpolate FREE-TEXT fields (a grade note, a loop task, a reflection) —
# exactly where an apostrophe lives in ordinary use — and NEITHER call site
# denies on a bad write (no exit-code check wraps the INSERT), so an
# exit-code-only assertion would have passed whether or not the row landed.
# This suite proves the fix by writing an apostrophe-bearing value THROUGH
# each call site into a real sqlite3 DB, then SELECTing it back and asserting
# the retrieved string equals the input EXACTLY — plus an adversarial
# DROP-TABLE-shaped payload per site, asserting both the exact round-trip and
# that the targeted table still exists afterward.
#
# Fix: both files now define the proven-correct esc() idiom already present in
# cmd_teammate.sh (`sed "s/'/''/g"`) and route every SQL text literal through
# it, replacing the broken hand-rolled parameter expansion everywhere it
# appeared in both files (not only at the two named line-101 sites).
#
# Call sites exercised (both route text VERBATIM through `_txt()`/esc(), so
# "equals the input exactly" is the correct assertion — no template wrapping):
#   - cmd_adapt.sh: `adapt roll --grade=<text>` → sprint_metrics.grade
#   - cmd_loop.sh:  `loop init --task=<text>`   → loops.task
#
# House style: exit 0 = pass, non-zero + message = fail (mirrors
# test_teammate_git_guard.sh).

set -eu -o pipefail
cd "$(dirname "$0")"
SCRIPTS_DIR="$(cd ../../skills/context/scripts && pwd)"

fails=0
total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip() { printf '  SKIP  %s — %s\n' "$1" "$2"; }

if ! command -v sqlite3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  skip "all cases" "sqlite3 and/or jq binary missing"
  echo "—— 0/0 passed ——"
  exit 0
fi

# ---------------------------------------------------------------------------
# Ephemeral project: a fresh git repo + a real, fully-migrated shctx namespace
# (via the actual `shctx init`), so both call sites run against the same
# schema production does rather than a hand-rolled subset of it.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-sqlesc-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init

init_out=$(bash "$SCRIPTS_DIR/shctx" init --shepherd 2>&1) || {
  echo "FATAL: shctx init failed: $init_out" >&2
  exit 1
}

# shellcheck source=/dev/null
source "$SCRIPTS_DIR/_lib.sh"
DB="$(shctx_db_path)"
if [[ ! -f "$DB" ]]; then
  echo "FATAL: expected DB at $DB after 'shctx init' — got: $init_out" >&2
  exit 1
fi
# The one host project this ephemeral repo registers — used below wherever a
# test needs to insert a fixture row directly (bypassing the CLI) to set up
# the precondition a call site's WHERE clause then has to survive.
pid_for_tests="$(shctx_project_id)"

table_exists() {
  local n
  n=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='$1';")
  [[ "${n:-0}" == "1" ]]
}

# ===========================================================================
# cmd_adapt.sh — `adapt roll --grade=<free text>` stores $grade VERBATIM into
# sprint_metrics.grade via _txt() (the fixed cmd_adapt.sh:101 site).
# ===========================================================================

# --- A1: apostrophe value round-trips exactly -------------------------------
total=$((total+1))
A1_GRADE="it's a fine grade"
out=$(bash "$SCRIPTS_DIR/cmd_adapt.sh" roll --sprint=sqlesc-a1 --grade="$A1_GRADE" 2>&1) || true
got=$(sqlite3 "$DB" "SELECT grade FROM sprint_metrics WHERE sprint_branch='sqlesc-a1';")
if [[ "$got" == "$A1_GRADE" ]]; then
  pass "A1 cmd_adapt.sh 'roll --grade' apostrophe value round-trips exactly"
else
  fail "A1 cmd_adapt.sh 'roll --grade' apostrophe value round-trips exactly" \
    "want=[$A1_GRADE] got=[$got] cmd_out=${out:0:200}"
fi

# --- A2: adversarial DROP-TABLE-shaped value round-trips, table survives ---
total=$((total+1))
A2_GRADE="pwned'); DROP TABLE sprint_metrics;--"
out=$(bash "$SCRIPTS_DIR/cmd_adapt.sh" roll --sprint=sqlesc-a2 --grade="$A2_GRADE" 2>&1) || true
if table_exists sprint_metrics; then
  got=$(sqlite3 "$DB" "SELECT grade FROM sprint_metrics WHERE sprint_branch='sqlesc-a2';")
  if [[ "$got" == "$A2_GRADE" ]]; then
    pass "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives"
  else
    fail "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives" \
      "want=[$A2_GRADE] got=[$got] cmd_out=${out:0:200}"
  fi
else
  fail "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives" \
    "sprint_metrics TABLE WAS DROPPED — cmd_out=${out:0:300}"
fi

# ===========================================================================
# cmd_loop.sh — `loop init --task=<free text>` stores $task VERBATIM into
# loops.task via _txt() (the fixed cmd_loop.sh:101 site).
# ===========================================================================

# --- L1: apostrophe value round-trips exactly -------------------------------
total=$((total+1))
L1_TASK="reviewer's note: don't merge yet"
loop_id1=$(bash "$SCRIPTS_DIR/cmd_loop.sh" init --max=3 --task="$L1_TASK" 2>&1) || true
got=$(sqlite3 "$DB" "SELECT task FROM loops WHERE id='$loop_id1';")
if [[ "$got" == "$L1_TASK" ]]; then
  pass "L1 cmd_loop.sh 'loop init --task' apostrophe value round-trips exactly"
else
  fail "L1 cmd_loop.sh 'loop init --task' apostrophe value round-trips exactly" \
    "want=[$L1_TASK] got=[$got] loop_id_out=${loop_id1:0:200}"
fi

# --- L2: adversarial DROP-TABLE-shaped value round-trips, table survives ---
total=$((total+1))
L2_TASK="pwned'); DROP TABLE loops;--"
loop_id2=$(bash "$SCRIPTS_DIR/cmd_loop.sh" init --max=3 --task="$L2_TASK" 2>&1) || true
if table_exists loops; then
  got=$(sqlite3 "$DB" "SELECT task FROM loops WHERE id='$loop_id2';")
  if [[ "$got" == "$L2_TASK" ]]; then
    pass "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives"
  else
    fail "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives" \
      "want=[$L2_TASK] got=[$got] loop_id_out=${loop_id2:0:200}"
  fi
else
  fail "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives" \
    "loops TABLE WAS DROPPED — loop_id_out=${loop_id2:0:300}"
fi

# ===========================================================================
# GH #295 — cmd_teammate.sh `retire`/`status`: proven mass-UPDATE and
# WHERE-bypass-read via an unescaped $name positional. Exercises the EXACT
# payloads from the issue's reproduction section.
# ===========================================================================
TM1="tm1-sqlesc-$$"; TM2="tm2-sqlesc-$$"
bash "$SCRIPTS_DIR/cmd_teammate.sh" register "$TM1" --team=sqlesc-team --type=conductor --session="$(shctx_uuid7)" >/dev/null
bash "$SCRIPTS_DIR/cmd_teammate.sh" register "$TM2" --team=sqlesc-team --type=conductor --session="$(shctx_uuid7)" >/dev/null

# --- B1: retire with a WHERE-bypass payload must NOT retire every teammate --
total=$((total+1))
bash "$SCRIPTS_DIR/cmd_teammate.sh" retire "nonexistent' OR '1'='1" >/dev/null 2>&1 || true
still_active=$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE teammate_name IN ('$TM1','$TM2') AND status!='retired';")
if [[ "$still_active" == "2" ]]; then
  pass "B1 cmd_teammate.sh 'retire' WHERE-bypass payload does not mass-retire other teammates"
else
  fail "B1 cmd_teammate.sh 'retire' WHERE-bypass payload does not mass-retire other teammates" \
    "want=2 unaffected got=$still_active still active"
fi

# --- B2: status with a WHERE-bypass payload must return NOTHING, not an
#         arbitrary row (the issue's proven `' OR '1'='1` read-bypass) -------
total=$((total+1))
status_out=$(bash "$SCRIPTS_DIR/cmd_teammate.sh" status "does-not-exist' OR '1'='1" 2>&1) || true
if [[ -z "$status_out" || "$status_out" == "[]" ]]; then
  pass "B2 cmd_teammate.sh 'status' WHERE-bypass payload returns no row"
else
  fail "B2 cmd_teammate.sh 'status' WHERE-bypass payload returns no row" "got=${status_out:0:200}"
fi

# --- B3: an apostrophe-bearing name round-trips into a real retire ----------
total=$((total+1))
TM3="it's-a-teammate-$$"
bash "$SCRIPTS_DIR/cmd_teammate.sh" register "$TM3" --team=sqlesc-team --type=conductor --session="$(shctx_uuid7)" >/dev/null
bash "$SCRIPTS_DIR/cmd_teammate.sh" retire "$TM3" >/dev/null 2>&1 || true
got=$(sqlite3 "$DB" "SELECT status FROM teammates WHERE id=(SELECT id FROM teammates WHERE teammate_name='$(esc "$TM3")' ORDER BY spawned_at DESC LIMIT 1);")
if [[ "$got" == "retired" ]]; then
  pass "B3 cmd_teammate.sh 'retire' apostrophe-bearing name round-trips (targets the right row)"
else
  fail "B3 cmd_teammate.sh 'retire' apostrophe-bearing name round-trips (targets the right row)" "want=retired got=$got"
fi

# ===========================================================================
# GH #291 — cmd_init.sh: $name (repo dirname) and $scope_json interpolated
# with ZERO escaping. Reproduces BOTH the malformed-statement case and the
# proven DROP-TABLE case, each in its own fresh git repo (name is derived
# from cwd's basename, so each case needs its own directory).
# ===========================================================================

# --- C1: an apostrophe in the checkout dirname must not break `shctx init` --
total=$((total+1))
c1_dir="$tmp/repo test's dir"
mkdir -p "$c1_dir"
(
  cd "$c1_dir" && git init -q . && git config user.email t@t && git config user.name t \
    && git -c commit.gpgsign=false commit -q --allow-empty -m init \
    && bash "$SCRIPTS_DIR/shctx" init --shepherd
) >"$tmp/c1_out" 2>&1
c1_rc=$?
c1_db="$c1_dir/.shepherd/shepherd.db"
if [[ "$c1_rc" -eq 0 && -f "$c1_db" ]]; then
  c1_name=$(sqlite3 "$c1_db" "SELECT name FROM projects LIMIT 1;")
  if [[ "$c1_name" == "repo test's dir" ]]; then
    pass "C1 cmd_init.sh apostrophe-bearing dirname round-trips exactly, init succeeds"
  else
    fail "C1 cmd_init.sh apostrophe-bearing dirname round-trips exactly, init succeeds" \
      "want=[repo test's dir] got=[$c1_name]"
  fi
else
  fail "C1 cmd_init.sh apostrophe-bearing dirname round-trips exactly, init succeeds" \
    "rc=$c1_rc out=$(cat "$tmp/c1_out" | tr '\n' ' ' | head -c 300)"
fi

# --- C2: a DROP-TABLE-shaped dirname must not execute arbitrary SQL --------
total=$((total+1))
c2_dir="$tmp/pwned'); DROP TABLE mem_entries;--"
mkdir -p "$c2_dir"
(
  cd "$c2_dir" && git init -q . && git config user.email t@t && git config user.name t \
    && git -c commit.gpgsign=false commit -q --allow-empty -m init \
    && bash "$SCRIPTS_DIR/shctx" init --shepherd
) >"$tmp/c2_out" 2>&1
c2_rc=$?
c2_db="$c2_dir/.shepherd/shepherd.db"
if [[ "$c2_rc" -eq 0 && -f "$c2_db" ]]; then
  c2_mem_exists=$(sqlite3 "$c2_db" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='mem_entries';")
  c2_name=$(sqlite3 "$c2_db" "SELECT name FROM projects LIMIT 1;")
  if [[ "$c2_mem_exists" == "1" && "$c2_name" == "pwned'); DROP TABLE mem_entries;--" ]]; then
    pass "C2 cmd_init.sh DROP-TABLE-shaped dirname round-trips exactly, mem_entries survives"
  else
    fail "C2 cmd_init.sh DROP-TABLE-shaped dirname round-trips exactly, mem_entries survives" \
      "mem_entries_exists=$c2_mem_exists name=[$c2_name]"
  fi
else
  fail "C2 cmd_init.sh DROP-TABLE-shaped dirname round-trips exactly, mem_entries survives" \
    "rc=$c2_rc out=$(cat "$tmp/c2_out" | tr '\n' ' ' | head -c 300)"
fi

# ===========================================================================
# GH #297 — cmd_report.sh: 5 unescaped CLI flags, UNION-based exfiltration
# proven live against `discovery --run=`. Reproduces the issue's exact canary
# + payload shape.
# ===========================================================================
total=$((total+1))
CANARY_ID="$(shctx_uuid7)"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at) VALUES ('$CANARY_ID','$(esc "$pid_for_tests")','note','SECRET-CANARY','this-should-never-leak-via-a-report-flag','[]',0,0,0);" 2>/dev/null || true
D_OUT=$(bash "$SCRIPTS_DIR/cmd_report.sh" discovery --run="zzz' UNION SELECT 'LEAK','LEAK', body, NULL FROM mem_entries WHERE title='SECRET-CANARY' --" 2>&1) || true
if [[ "$D_OUT" != *"this-should-never-leak-via-a-report-flag"* ]]; then
  pass "D1 cmd_report.sh 'discovery --run' UNION payload does not leak the canary row"
else
  fail "D1 cmd_report.sh 'discovery --run' UNION payload does not leak the canary row" "leaked in output: ${D_OUT:0:300}"
fi

# ===========================================================================
# GH #296 (cmd_eval.sh) — the broken `${v//\'/\'\'}` idiom, 9 sites. Exercised
# end-to-end (real DB + real CLI, no network) via SHEPHERD_LLM_MOCK_TEXT,
# which short-circuits services/llm/llm.sh before any claude call — the
# documented "deterministic, free gate tests" seam. Covers the reflect-lookup
# WHERE clause AND the --record INSERT (6 of the 9 sites) in one real run.
# ===========================================================================
total=$((total+1))
E1_SPRINT="sqlesc-e1-doesn't-fully-address-it's"
E1_MID="$(shctx_uuid7)"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at) VALUES ('$E1_MID','$(esc "$pid_for_tests")','prior','prior: reflection ($(esc "$E1_SPRINT"))','the reflection note itself','[\"reflection\"]',0,0,0);"
E1_OUT=$(SHEPHERD_LLM_MOCK_TEXT='{"scores":{"specificity":4,"actionability":4,"grounding":3},"rationale":"The response doesn'"'"'t fully address the user'"'"'s question."}' \
  bash "$SCRIPTS_DIR/cmd_eval.sh" run --kind=reflection --sprint="$E1_SPRINT" --record --json 2>&1) || true
if [[ -n "$(sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_runs';" 2>/dev/null)" ]]; then
  E1_GOT=$(sqlite3 "$DB" "SELECT rationale FROM eval_runs WHERE subject_ref='$(esc "$E1_SPRINT")' ORDER BY created_at DESC LIMIT 1;")
  if [[ "$E1_GOT" == "The response doesn't fully address the user's question." ]]; then
    pass "E1 cmd_eval.sh 'run --record' apostrophe-bearing reflection round-trips exactly (ordinary judge prose, not adversarial)"
  else
    fail "E1 cmd_eval.sh 'run --record' apostrophe-bearing reflection round-trips exactly" \
      "want=[The response doesn't fully address the user's question.] got=[$E1_GOT] out=${E1_OUT:0:200}"
  fi
else
  fail "E1 cmd_eval.sh 'run --record' apostrophe-bearing reflection round-trips exactly" \
    "eval_runs table missing after run — out=${E1_OUT:0:300}"
fi

# --- E2: eval list/report WHERE-clause survives an apostrophe-bearing kind -
total=$((total+1))
E2_KIND="kind's-with-a-quote"
sqlite3 "$DB" "INSERT INTO eval_runs (id,project_id,kind,subject_ref,score,threshold,passed,model,scores_json,rationale,created_at) VALUES ('$(shctx_uuid7)','$(esc "$pid_for_tests")','$(esc "$E2_KIND")','sqlesc-e2',80,60,1,'mockmodel','{}','ok',0);"
E2_OUT=$(bash "$SCRIPTS_DIR/cmd_eval.sh" list --kind="$E2_KIND" --json 2>&1) || true
if [[ "$E2_OUT" == *"sqlesc-e2"* ]]; then
  pass "E2 cmd_eval.sh 'list --kind' apostrophe-bearing filter matches the row (WHERE clause not broken)"
else
  fail "E2 cmd_eval.sh 'list --kind' apostrophe-bearing filter matches the row" "out=${E2_OUT:0:300}"
fi

# ===========================================================================
# GH #296 (cmd_prune.sh) — the same broken idiom on $branch (`cur_esc`). A
# real git branch name may legally contain an apostrophe.
# ===========================================================================
total=$((total+1))
F_BRANCH="o'brien-sprint"
orig_branch="$(git -C "$tmp" rev-parse --abbrev-ref HEAD)"
git -C "$tmp" checkout -q -b "$F_BRANCH"
f_out=$(cd "$tmp" && bash "$SCRIPTS_DIR/cmd_prune.sh" --json 2>&1) || true
git -C "$tmp" checkout -q "$orig_branch"
if [[ "$f_out" == *'"branch"'* ]]; then
  pass "F1 cmd_prune.sh apostrophe-bearing branch name does not break the preview query"
else
  fail "F1 cmd_prune.sh apostrophe-bearing branch name does not break the preview query" "${f_out:0:300}"
fi

# ===========================================================================
# NEW this wave (not in any filed issue — found by sweeping every call site
# rather than trusting the issue list, per the brief): cmd_query.sh's
# bind-value escape silently DELETED apostrophes (an unquoted `''` on the
# replacement side of `${v//\'/''}` is an empty-string LITERAL to bash, not
# two literal quotes) instead of doubling them for SQL — a round-trip
# violation, exercised through the REAL `mem-search` query template.
# ===========================================================================
total=$((total+1))
G_TITLE="it's a mem search target"
G_ID="$(shctx_uuid7)"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at) VALUES ('$G_ID','$(esc "$pid_for_tests")','note','$(esc "$G_TITLE")','body','[]',0,0,0);"
G_OUT=$(bash "$SCRIPTS_DIR/cmd_query.sh" mem-search --q="it's a mem search target" --json 2>&1) || true
if [[ "$G_OUT" == *"it's a mem search target"* ]]; then
  pass "G1 cmd_query.sh bind-value round-trips an apostrophe exactly (was silently stripping it)"
else
  fail "G1 cmd_query.sh bind-value round-trips an apostrophe exactly (was silently stripping it)" "out=${G_OUT:0:300}"
fi

# ===========================================================================
# NEW this wave: refresh-artifacts.sh's title-line sed script
# (`sed -E 's/^#+ //;s/'\''/''/g'`) collapses, once bash finishes quote
# removal, to `s/'//g` — DELETING every apostrophe from the title instead of
# doubling it for SQL. Same round-trip-violation class as G1, different file.
# ===========================================================================
total=$((total+1))
h_artifacts_root="$(shctx_artifacts_root)"
mkdir -p "$h_artifacts_root/docs/plans"
printf "# Joe's Plan Title\n\nbody text\n" > "$h_artifacts_root/docs/plans/joes-plan.plan.md"
# Runs against the SAME already-initialized project/DB as every other test
# in this file (cwd is still $tmp — the git repo `shctx init` ran in above).
bash "$SCRIPTS_DIR/refresh-artifacts.sh" >/dev/null 2>&1 || true
H_GOT=$(sqlite3 "$DB" "SELECT title FROM artifacts WHERE path LIKE '%joes-plan.plan.md';" 2>/dev/null || true)
if [[ "$H_GOT" == "Joe's Plan Title" ]]; then
  pass "H1 refresh-artifacts.sh title round-trips an apostrophe exactly (was silently stripping it)"
else
  fail "H1 refresh-artifacts.sh title round-trips an apostrophe exactly (was silently stripping it)" "want=[Joe's Plan Title] got=[$H_GOT]"
fi

# ===========================================================================
# cmd_mem.sh — same WHERE-bypass/mass-write class as #295, a DIFFERENT file:
# `pin`/`unpin`/`rm` take a bare CLI positional `<id>` and were unescaped.
# ===========================================================================
total=$((total+1))
M_ID1="$(shctx_uuid7)"; M_ID2="$(shctx_uuid7)"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at) VALUES ('$M_ID1','$(esc "$pid_for_tests")','note','keep-me','b','[]',0,0,0);"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at) VALUES ('$M_ID2','$(esc "$pid_for_tests")','note','keep-me-too','b','[]',0,0,0);"
bash "$SCRIPTS_DIR/cmd_mem.sh" rm "nonexistent' OR '1'='1" >/dev/null 2>&1 || true
M_SURVIVORS=$(sqlite3 "$DB" "SELECT count(*) FROM mem_entries WHERE id IN ('$M_ID1','$M_ID2');")
if [[ "$M_SURVIVORS" == "2" ]]; then
  pass "M1 cmd_mem.sh 'rm' WHERE-bypass payload does not mass-delete other rows"
else
  fail "M1 cmd_mem.sh 'rm' WHERE-bypass payload does not mass-delete other rows" "want=2 survivors got=$M_SURVIVORS"
fi

# ===========================================================================
# cmd_signal.sh — `send` interpolated $to/$kind/$sender raw (inconsistent
# with `poll`, which already escaped the same $kind correctly).
# ===========================================================================
total=$((total+1))
S_PAYLOAD='{"note":"hi"}'
S_TO="recipient's-name"
S_OUT=$(printf '%s' "$S_PAYLOAD" | bash "$SCRIPTS_DIR/cmd_signal.sh" send --to="$S_TO" --kind="it's-a-kind" 2>&1) || true
S_GOT=$(sqlite3 "$DB" "SELECT recipient||'|'||kind FROM session_signals WHERE id='$S_OUT';" 2>/dev/null || true)
if [[ "$S_GOT" == "recipient's-name|it's-a-kind" ]]; then
  pass "S1 cmd_signal.sh 'send' apostrophe-bearing --to/--kind round-trip exactly"
else
  fail "S1 cmd_signal.sh 'send' apostrophe-bearing --to/--kind round-trip exactly" "want=[recipient's-name|it's-a-kind] got=[$S_GOT] id_out=${S_OUT:0:80}"
fi

# ===========================================================================
# Recurrence guard (#296's explicit ask): grep for the broken
# `${var//'/''}` byte shape across every shell script this wave's file scope
# owns, and FAIL on any hit. Self-tested against a deliberately-broken
# fixture as its positive control — a checker never shown to fail is not
# known to check anything.
# ===========================================================================
recurrence_scan() {
  # Matches `${<anything>//\'/\'\'}` — the broken form: a backslash survives
  # on the REPLACEMENT side. Deliberately does NOT match the correct
  # `${v//\'/''}` (no backslash before the replacement's quotes), which is
  # why cmd_signal.sh/cmd_query.sh's ORIGINAL (bind-key) idiom never tripped
  # this — that one had a different bug (see G1 above), not this byte shape.
  #
  # Comment lines are stripped BEFORE matching: this fix's own explanatory
  # comments (this file included — see the header above) cite the broken
  # byte pattern verbatim to document what NOT to do, which would otherwise
  # be an unbroken stream of false positives against a guard that scans
  # itself. A line whose first non-blank character is `#` never reaches
  # sqlite3, so it carries no live risk; only CODE is enforced.
  local f
  for f in "$@"; do
    [[ -f "$f" ]] || continue
    if grep -vE '^[[:space:]]*#' "$f" 2>/dev/null | grep -qE "//\\\\'/\\\\'\\\\'"; then
      printf '%s\n' "$f"
    fi
  done
}

# --- self-test: a deliberately-broken fixture MUST be caught -----------------
# Written via a quoted heredoc (no expansion at all) so the fixture's own
# broken idiom lands byte-for-byte with zero risk of THIS file's quoting
# accidentally "fixing" it on the way in.
total=$((total+1))
fixture="$tmp/broken_idiom_fixture.sh"
cat > "$fixture" <<'FIXTURE_EOF'
#!/usr/bin/env bash
v_esc="${v//\'/\'\'}"
FIXTURE_EOF
hit=$(recurrence_scan "$fixture")
if [[ "$hit" == "$fixture" ]]; then
  pass "N1 recurrence guard: positive control — a deliberately-broken fixture is caught"
else
  fail "N1 recurrence guard: positive control — a deliberately-broken fixture is caught" "expected to catch $fixture, got=[$hit]"
fi

# --- self-test: a CORRECTLY-escaped fixture must NOT be flagged (no false
#     positive on the working idiom) ------------------------------------------
total=$((total+1))
clean_fixture="$tmp/clean_idiom_fixture.sh"
cat > "$clean_fixture" <<'FIXTURE_EOF'
#!/usr/bin/env bash
esc() { printf '%s' "$1" | sed "s/'/''/g"; }
v_esc="$(esc "$v")"
FIXTURE_EOF
hit=$(recurrence_scan "$clean_fixture")
if [[ -z "$hit" ]]; then
  pass "N2 recurrence guard: negative control — the correct esc() idiom is not flagged"
else
  fail "N2 recurrence guard: negative control — the correct esc() idiom is not flagged" "false positive on $clean_fixture"
fi

# --- enforcement: every *.sh this file scope owns must be clean -------------
total=$((total+1))
live_hits=$(recurrence_scan "$SCRIPTS_DIR"/*.sh)
if [[ -z "$live_hits" ]]; then
  pass "N3 recurrence guard: skills/context/scripts/*.sh carries zero broken-idiom sites"
else
  fail "N3 recurrence guard: skills/context/scripts/*.sh carries zero broken-idiom sites" "hits in: $live_hits"
fi

# --- enforcement (repo-wide intent, #296): also scan hooks/scripts/*.sh and
# hooks/tests/*.sh. This is NOT this step's file scope to FIX — flagged here
# so a hit is loud and attributable, never silently swallowed. A hit here
# reflects a SIBLING lane's file scope this wave, not this diff. Excludes
# THIS file: its own N1 positive-control fixture is authored via a heredoc
# that deliberately contains the broken byte pattern as literal source text
# (not live SQL-building code), which would otherwise self-flag every run —
# a checker tripping on its own known-bad test data is a false positive, not
# evidence of a live defect.
#
# DELIBERATELY NON-GATING (does not touch total/fails, unlike N1-N3): this
# step's file scope is `skills/context/scripts/*.sh` +
# `hooks/tests/test_sql_escaping.sh` ONLY — hooks/scripts/*.sh is a SIBLING
# lane's file scope this same wave (file_scope.exclusive: "siblings hold
# everything else"). Making N4 a hard gate would couple THIS step's exit
# code to another coder's independent, concurrently-in-flight fix — a false
# "my diff is broken" signal for a defect this diff cannot touch. It still
# runs and prints loudly on every invocation (visibility, not silence) so
# the gap is never swallowed; it just isn't allowed to fail a lane it
# doesn't own.
repo_root="$(cd "$SCRIPTS_DIR/../../.." && pwd)"
self="$repo_root/hooks/tests/test_sql_escaping.sh"
wide_hits=""
for wf in "$repo_root"/hooks/scripts/*.sh "$repo_root"/hooks/tests/*.sh; do
  [[ "$wf" == "$self" ]] && continue
  h="$(recurrence_scan "$wf")"
  [[ -n "$h" ]] && wide_hits="$wide_hits$h"$'\n'
done
if [[ -z "$wide_hits" ]]; then
  pass "N4 (informational) recurrence guard: hooks/scripts + hooks/tests also carry zero broken-idiom sites"
else
  skip "N4 (informational) recurrence guard — hooks/scripts + hooks/tests" \
    "OUT OF THIS STEP'S FILE SCOPE (sibling lane owns hooks/scripts/*.sh this wave) — live hits: $(printf '%s' "$wide_hits" | tr '\n' ' ')"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
