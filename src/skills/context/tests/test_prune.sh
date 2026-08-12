#!/usr/bin/env bash
# skills/context/tests/test_prune.sh — workdir prune (v6.2.5, #171).
#
# Deterministic: --dry-run (default) removes nothing; --confirm MOVES eligible
# on-disk targets to /tmp (reversible); the CURRENT-branch dispatch dir is NEVER
# swept (the active fence); a missing registry DB is tolerated. Runs cmd_prune.sh
# inside an ephemeral git repo with a .shepherd/ workdir.

set -uo pipefail
SCRIPTS="$(cd "$(dirname "$0")/../scripts" && pwd)"
CMD="$SCRIPTS/cmd_prune.sh"

fails=0
ok()  { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fails=$((fails+1)); }

tmp=$(mktemp -d -t shep-prune-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude; printf '[project]\nname="t"\n' > .claude/shepherd.toml
branch="$(git rev-parse --abbrev-ref HEAD)"

wd="$tmp/.shepherd"
mkdir -p "$wd/dispatch/oldsprint" "$wd/dispatch/$branch" "$wd/logs/hooks" "$wd/cache/snapshots"
touch "$wd/dispatch/oldsprint/a.json" "$wd/dispatch/$branch/b.json"
touch "$wd/logs/events-old.jsonl" "$wd/logs/hooks/2020-01-01.jsonl"
touch "$wd/cache/snapshots/precompact-s1-1.json" "$wd/cache/snapshots/precompact-s2-2.json"
# Backdate the transient state so the age floors match (find -mtime +N).
touch -t 202001010000 "$wd/dispatch/oldsprint" "$wd/dispatch/oldsprint/a.json" \
      "$wd/dispatch/$branch" "$wd/dispatch/$branch/b.json" \
      "$wd/logs/events-old.jsonl" "$wd/logs/hooks/2020-01-01.jsonl" 2>/dev/null

# 1. Dry-run (default) removes nothing.
out="$(bash "$CMD" --dispatch-days=0 --logs-days=0 --snapshots-keep=0 2>&1)"; rc=$?
[[ $rc -eq 0 ]] && ok "dry-run exits 0" || bad "dry-run exits 0 (rc=$rc)"
[[ -d "$wd/dispatch/oldsprint" ]] && ok "dry-run kept oldsprint dir" || bad "dry-run kept oldsprint dir"
[[ "$out" == *"DRY-RUN"* ]] && ok "dry-run labelled" || bad "dry-run labelled"
[[ "$out" == *"plan CSV:"* ]] && ok "dry-run wrote plan CSV" || bad "dry-run wrote plan CSV"

# 2. --confirm moves eligible on-disk targets; NEVER the current-branch dispatch dir.
conf_out="$(bash "$CMD" --confirm --dispatch-days=0 --logs-days=0 --snapshots-keep=0 2>&1)"
run_dir="$(printf '%s\n' "$conf_out" | sed -n 's/^plan CSV: //p' | sed 's#/plan.csv$##')"
[[ ! -d "$wd/dispatch/oldsprint" ]] && ok "confirm moved non-current dispatch dir" || bad "confirm moved non-current dispatch dir"
[[ -d "$wd/dispatch/$branch" ]] && ok "confirm KEPT current-branch dispatch dir (fence)" || bad "confirm KEPT current-branch dispatch dir (fence)"
[[ ! -f "$wd/logs/events-old.jsonl" ]] && ok "confirm moved aged event log" || bad "confirm moved aged event log"
[[ ! -f "$wd/cache/snapshots/precompact-s1-1.json" || ! -f "$wd/cache/snapshots/precompact-s2-2.json" ]] \
  && ok "confirm moved over-retention snapshot(s)" || bad "confirm moved over-retention snapshot(s)"
# Reversibility: the snapshot MIRRORS the workdir tree — logs/hooks/ keeps its subpath
# (regression guard for the flatten-into-$cat/ data-loss bug).
if [[ -n "$run_dir" && -f "$run_dir/logs/hooks/2020-01-01.jsonl" ]]; then
  ok "confirm preserved logs/hooks/ subpath in snapshot (reversible)"
else
  bad "confirm preserved logs/hooks/ subpath in snapshot (run_dir=$run_dir)"
fi

# 3. Missing registry DB tolerated (db_present=0, no error).
out="$(bash "$CMD" 2>&1)"; rc=$?
[[ $rc -eq 0 ]] && ok "no-DB run exits 0" || bad "no-DB run exits 0 (rc=$rc)"
[[ "$out" == *"registry DB: none"* ]] && ok "no-DB reported cleanly" || bad "no-DB reported cleanly"

if [[ "$fails" -gt 0 ]]; then
  printf 'test_prune: %d failure(s)\n' "$fails"; exit 1
fi
printf 'test_prune: OK — dry-run default, confirm moves, current-branch fence, missing-DB tolerated\n'
