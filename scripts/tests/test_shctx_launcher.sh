#!/usr/bin/env bash
# scripts/tests/test_shctx_launcher.sh -- regression tests for the #235
# shctx PATH launcher (scripts/install-shctx-launcher.sh).
#
# THE BUG (#235): a hand-rolled launcher globbed `cache/fl03/shepherd/*`
# only -- ONE publisher, hardcoded -- and resolved to a dead 6.3.3 binary
# while the actively-loaded 6.3.9 install sat under `cache/pzzld/shepherd/*`.
# Every `shctx` call fleet-wide (root, six lane conductors, hooks) routed to
# the stale binary for days. This suite builds a FAKE cache tree under a
# temp dir (never touches the real ~/.claude/plugins/cache or the real
# ~/.local/bin/shctx -- both are overridden via SHCTX_CACHE_ROOT /
# SHCTX_LAUNCHER_DEST) and asserts the installed launcher always picks the
# highest version BY THE VERSION PATH SEGMENT, regardless of which publisher
# directory it lives under and regardless of lexicographic path ordering.
#
# Runnable standalone: ./scripts/tests/test_shctx_launcher.sh
set -eu -o pipefail
cd "$(dirname "$0")"
SCRIPTS_DIR="$(cd .. && pwd)"
INSTALLER="$SCRIPTS_DIR/install-shctx-launcher.sh"

fails=0
total=0

# Fresh temp dir per whole-suite run: install destination + fake cache tree
# both live here, torn down on exit so repeated runs never accumulate state
# and never touch the real filesystem locations the production launcher
# targets.
tmp=$(mktemp -d -t shep-shctx-launcher-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT

LAUNCHER_DEST="$tmp/local-bin/shctx"

# --- helpers ----------------------------------------------------------------

# Writes a fake `bin/shepherd` stub at
# $CACHE_ROOT/<publisher>/shepherd/<version>/bin/shepherd that echoes a
# distinctive tag when invoked, so a test can assert exactly which install
# the launcher resolved to.
make_fake_install() {
  local cache_root="$1" publisher="$2" version="$3" tag="$4"
  local dir="$cache_root/$publisher/shepherd/$version/bin"
  mkdir -p "$dir"
  cat > "$dir/shepherd" <<EOF
#!/usr/bin/env bash
echo "$tag"
EOF
  chmod +x "$dir/shepherd"
}

# Runs the installed launcher with CLAUDE_PLUGIN_ROOT unset and
# SHCTX_CACHE_ROOT pointed at the given fake cache root, capturing stdout.
run_launcher_against_cache() {
  local cache_root="$1"; shift
  env -u CLAUDE_PLUGIN_ROOT SHCTX_CACHE_ROOT="$cache_root" "$LAUNCHER_DEST" "$@"
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  total=$((total+1))
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS  %s\n' "$name"
  else
    printf '  FAIL  %-60s expected=%q actual=%q\n' "$name" "$expected" "$actual"
    fails=$((fails+1))
  fi
}

assert_contains() {
  local name="$1" needle="$2" haystack="$3"
  total=$((total+1))
  if [[ "$haystack" == *"$needle"* ]]; then
    printf '  PASS  %s\n' "$name"
  else
    printf '  FAIL  %-60s expected to contain %q, got=%q\n' "$name" "$needle" "$haystack"
    fails=$((fails+1))
  fi
}

# --- install the launcher into a throwaway destination -----------------------

echo "== install-shctx-launcher.sh =="
install_out="$(SHCTX_LAUNCHER_DEST="$LAUNCHER_DEST" bash "$INSTALLER" 2>&1)"
total=$((total+1))
if [[ -x "$LAUNCHER_DEST" ]]; then
  printf '  PASS  %s\n' "installer-creates-executable-launcher"
else
  printf '  FAIL  %-60s installer output: %s\n' "installer-creates-executable-launcher" "$install_out"
  fails=$((fails+1))
fi
assert_contains "installer-reports-what-it-did" "wrote $LAUNCHER_DEST" "$install_out"

# Idempotency: re-running with no payload change must be a clean no-op, not
# a repeated backup-and-rewrite.
rerun_out="$(SHCTX_LAUNCHER_DEST="$LAUNCHER_DEST" bash "$INSTALLER" 2>&1)"
assert_contains "installer-idempotent-second-run" "already up to date" "$rerun_out"
total=$((total+1))
backup_count=$(find "$(dirname "$LAUNCHER_DEST")" -maxdepth 1 -name '*.bak.*' | wc -l)
if [[ "$backup_count" -eq 0 ]]; then
  printf '  PASS  %s\n' "installer-no-spurious-backup-on-noop-rerun"
else
  printf '  FAIL  %-60s found %d backup file(s)\n' "installer-no-spurious-backup-on-noop-rerun" "$backup_count"
  fails=$((fails+1))
fi

# Overwrite-with-backup: a DIFFERENT existing file at the destination must be
# backed up, not silently clobbered, and the installer must report it.
printf '#!/bin/sh\necho old-launcher\n' > "$LAUNCHER_DEST"
chmod +x "$LAUNCHER_DEST"
overwrite_out="$(SHCTX_LAUNCHER_DEST="$LAUNCHER_DEST" bash "$INSTALLER" 2>&1)"
assert_contains "installer-backs-up-before-overwrite" "backed up existing" "$overwrite_out"
total=$((total+1))
backup_count=$(find "$(dirname "$LAUNCHER_DEST")" -maxdepth 1 -name '*.bak.*' | wc -l)
if [[ "$backup_count" -ge 1 ]]; then
  printf '  PASS  %s\n' "installer-backup-file-exists"
else
  printf '  FAIL  %s\n' "installer-backup-file-exists"
  fails=$((fails+1))
fi
rm -f "$(dirname "$LAUNCHER_DEST")"/*.bak.*

echo "== launcher — the #235 regression, verbatim =="
# fl03/6.3.3 (the stale, actually-executing binary in the incident) alongside
# pzzld/6.3.9 (the actively-loaded version nothing could see). A
# full-path-lexicographic sort would happen to get this right ("pzzld" >
# "fl03") -- which is exactly why this case alone does not prove the fix;
# the semver case below proves it is comparing versions, not paths.
regression_cache="$tmp/cache-regression"
make_fake_install "$regression_cache" fl03 6.3.3 "STALE-6.3.3-fl03"
make_fake_install "$regression_cache" pzzld 6.3.9 "ACTIVE-6.3.9-pzzld"
out="$(run_launcher_against_cache "$regression_cache")"
assert_eq "picks-6.3.9-over-stale-6.3.3-regardless-of-publisher" "ACTIVE-6.3.9-pzzld" "$out"

echo "== launcher — semver ordering (6.4.9 vs 6.4.10) =="
# Publisher names deliberately chosen so LEXICOGRAPHIC full-path sort would
# pick the WRONG one ("aaa" < "zzz" lexicographically, so a naive sort
# would rank aaa/6.4.10 below zzz/6.4.9 by path -- but 6.4.10 is the
# correct answer numerically. This is the case that fails under a plain
# `sort` and only passes under a genuine `sort -V` / numeric compare).
semver_cache="$tmp/cache-semver"
make_fake_install "$semver_cache" aaa-publisher 6.4.10 "V6.4.10-aaa"
make_fake_install "$semver_cache" zzz-publisher 6.4.9 "V6.4.9-zzz"
out="$(run_launcher_against_cache "$semver_cache")"
assert_eq "picks-6.4.10-over-6.4.9-numerically-not-lexicographically" "V6.4.10-aaa" "$out"

# Sanity check that a PLAIN lexicographic string sort of the version segment
# alone really would get 6.4.9 vs 6.4.10 backwards -- pins the premise of
# the test above so it can never silently start testing nothing.
total=$((total+1))
lexicographic_pick="$(printf '6.4.10\n6.4.9\n' | sort | tail -n1)"
if [[ "$lexicographic_pick" == "6.4.9" ]]; then
  printf '  PASS  %s\n' "premise-plain-sort-gets-6.4.9-vs-6.4.10-backwards"
else
  printf '  FAIL  %-60s plain sort picked %q (premise invalidated)\n' "premise-plain-sort-gets-6.4.9-vs-6.4.10-backwards" "$lexicographic_pick"
  fails=$((fails+1))
fi

echo "== launcher — three-plus publishers, arbitrary directory-glob order =="
multi_cache="$tmp/cache-multi"
make_fake_install "$multi_cache" mmm 1.0.0 "V1.0.0"
make_fake_install "$multi_cache" bbb 2.5.3 "V2.5.3"
make_fake_install "$multi_cache" xxx 2.5.10 "V2.5.10-winner"
make_fake_install "$multi_cache" aaa 2.4.99 "V2.4.99"
out="$(run_launcher_against_cache "$multi_cache")"
assert_eq "picks-highest-across-many-publishers" "V2.5.10-winner" "$out"

echo "== launcher — \$CLAUDE_PLUGIN_ROOT takes priority over the cache scan =="
# Even when the cache scan WOULD resolve to a newer version, an explicitly
# set CLAUDE_PLUGIN_ROOT (the harness's own word on the loaded plugin) wins
# -- the glob is the bare-shell fallback, not a second opinion.
plugin_root="$tmp/plugin-root"
mkdir -p "$plugin_root/bin"
printf '#!/usr/bin/env bash\necho "FROM-PLUGIN-ROOT"\n' > "$plugin_root/bin/shepherd"
chmod +x "$plugin_root/bin/shepherd"
out="$(CLAUDE_PLUGIN_ROOT="$plugin_root" SHCTX_CACHE_ROOT="$semver_cache" "$LAUNCHER_DEST")"
assert_eq "claude-plugin-root-preferred-over-cache-scan" "FROM-PLUGIN-ROOT" "$out"

echo "== launcher — args and cwd are preserved through exec =="
argv_root="$tmp/argv-root"
mkdir -p "$argv_root/bin"
cat > "$argv_root/bin/shepherd" <<'EOF'
#!/usr/bin/env bash
echo "cwd=$(pwd)"
echo "argv=$*"
EOF
chmod +x "$argv_root/bin/shepherd"
workdir="$tmp/caller-cwd"
mkdir -p "$workdir"
out="$(cd "$workdir" && CLAUDE_PLUGIN_ROOT="$argv_root" "$LAUNCHER_DEST" status --json foo)"
assert_contains "caller-cwd-preserved" "cwd=$(cd "$workdir" && pwd)" "$out"
assert_contains "args-forwarded" "argv=status --json foo" "$out"

echo "== launcher — nothing resolves: clear diagnostic, non-zero exit, never silent =="
empty_cache="$tmp/cache-empty"
mkdir -p "$empty_cache"
set +e
out="$(run_launcher_against_cache "$empty_cache" 2>&1)"
rc=$?
set -e
total=$((total+1))
if [[ "$rc" -ne 0 ]]; then
  printf '  PASS  %s\n' "no-resolution-exits-non-zero"
else
  printf '  FAIL  %-60s exited 0\n' "no-resolution-exits-non-zero"
  fails=$((fails+1))
fi
assert_contains "no-resolution-prints-diagnostic" "no shepherd plugin install found" "$out"

echo "== launcher — CLAUDE_PLUGIN_ROOT set but binary missing: fails loud, no silent fallback =="
broken_root="$tmp/broken-plugin-root"
mkdir -p "$broken_root"  # no bin/shepherd under here
set +e
out="$(CLAUDE_PLUGIN_ROOT="$broken_root" SHCTX_CACHE_ROOT="$regression_cache" "$LAUNCHER_DEST" 2>&1)"
rc=$?
set -e
total=$((total+1))
if [[ "$rc" -ne 0 ]]; then
  printf '  PASS  %s\n' "broken-claude-plugin-root-exits-non-zero"
else
  printf '  FAIL  %-60s exited 0 (should have failed loud, not fallen back)\n' "broken-claude-plugin-root-exits-non-zero"
  fails=$((fails+1))
fi
assert_contains "broken-claude-plugin-root-diagnostic" "does not exist" "$out"
total=$((total+1))
if [[ "$out" != *"ACTIVE-6.3.9-pzzld"* ]]; then
  printf '  PASS  %s\n' "broken-claude-plugin-root-does-not-silently-fall-back-to-cache"
else
  printf '  FAIL  %s\n' "broken-claude-plugin-root-does-not-silently-fall-back-to-cache"
  fails=$((fails+1))
fi

echo "== launcher — missing executable bit degrades to bash invocation =="
noexec_root="$tmp/noexec-root"
mkdir -p "$noexec_root/bin"
printf '#!/usr/bin/env bash\necho "RAN-WITHOUT-X-BIT"\n' > "$noexec_root/bin/shepherd"
chmod -x "$noexec_root/bin/shepherd"
out="$(CLAUDE_PLUGIN_ROOT="$noexec_root" "$LAUNCHER_DEST" 2>&1)"
assert_eq "runs-via-bash-when-not-executable" "RAN-WITHOUT-X-BIT" "$out"

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
