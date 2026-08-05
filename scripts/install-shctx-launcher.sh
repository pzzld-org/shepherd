#!/usr/bin/env bash
# scripts/install-shctx-launcher.sh -- installs a publisher-agnostic PATH
# launcher for the shepherd context CLI at ~/.local/bin/shctx.
#
# THE BUG (GH #235): a hand-rolled launcher globbed `cache/fl03/shepherd/*`
# only -- ONE publisher, hardcoded -- and resolved to a dead 6.3.3 binary
# while the actively-loaded 6.3.9 install sat under `cache/pzzld/shepherd/*`.
# Every `shctx` call fleet-wide (root, six lane conductors, hooks) routed to
# the stale binary for days: bogus per-worktree shepherd.db files and
# "unknown subcommand" errors misdiagnosed across two separate sprints.
#
# THE FIX this installer ships: the launcher it writes scans EVERY publisher
# directory (`cache/*/shepherd/*`) and picks the highest version BY THE
# VERSION PATH SEGMENT, using real semver ordering -- never a full-path
# lexicographic sort. See the launcher's own header (below, in the heredoc)
# for why a lexicographic sort is a live landmine, not a today-only bug:
# "pzzld" happens to sort above "fl03" and so happened to pick the newer
# binary in this exact incident, which would give the WRONG answer the day
# the publisher names (or a third one) sort the other way.
#
# This installer is idempotent: re-running it is a no-op when the payload is
# unchanged, and backs up any existing file at the destination before
# overwriting it otherwise. Prints exactly what it did either way.
#
# Usage: scripts/install-shctx-launcher.sh
#   SHCTX_LAUNCHER_DEST  override the install destination (default
#                        ~/.local/bin/shctx). Set by tests to install into a
#                        throwaway directory instead of the real PATH bin.
set -eu -o pipefail

# Destination is overridable for testing; production default is the
# conventional user-local PATH bin dir (mirrors bin/shepherd-venv-ensure's
# own env-override-with-sane-default pattern).
DEST="${SHCTX_LAUNCHER_DEST:-$HOME/.local/bin/shctx}"
DEST_DIR="$(dirname "$DEST")"
mkdir -p "$DEST_DIR"

# Render the launcher payload to a scratch file first so idempotency can be
# checked by content (cmp -s), not by "does a file already exist" -- the
# latter would back up and rewrite on every run even when nothing changed.
STAGED="$(mktemp "${TMPDIR:-/tmp}/shctx-launcher.XXXXXX")"
trap 'rm -f "$STAGED"' EXIT

cat >"$STAGED" <<'SHCTX_LAUNCHER_EOF'
#!/usr/bin/env bash
# ~/.local/bin/shctx -- PATH launcher for the shepherd context CLI.
#
# Written by scripts/install-shctx-launcher.sh (GH #235). DO NOT hand-edit --
# re-run the installer instead; it is idempotent and will overwrite this file
# with the current payload (after backing up whatever was here) if the
# installer's payload has changed since the last run.
#
# THE BUG THIS FIXES (#235): an earlier hand-rolled launcher globbed
# `cache/fl03/shepherd/*` only -- ONE publisher, hardcoded -- and so resolved
# to a dead 6.3.3 binary while the actively-loaded 6.3.9 install sat under
# `cache/pzzld/shepherd/*`. Every `shctx` call fleet-wide (root, six lane
# conductors, hooks) routed to the stale binary for days: bogus per-worktree
# shepherd.db files, "unknown subcommand" errors misdiagnosed across two
# separate sprints.
#
# Resolution order (mirrors bin/shepherd's own CLAUDE_PLUGIN_ROOT-then-derive
# pattern -- see that file's header):
#   1. $CLAUDE_PLUGIN_ROOT, when set. This is the harness's own word on which
#      plugin install is actually loaded for THIS session -- trusted as-is,
#      never second-guessed against the cache scan below. If it points at a
#      broken install, fail loudly rather than silently substituting a
#      different one; silent substitution is exactly the failure mode #235
#      was.
#   2. Otherwise (a bare shell with no harness context propagated -- the
#      common case for a manually-invoked or cross-session `shctx`): scan
#      EVERY publisher directory under the plugin cache, `cache/*/shepherd/*`,
#      and pick the highest version BY THE VERSION PATH SEGMENT (the final
#      path component), using real semver ordering (`sort -V`, verified
#      working before use; degrades to a pure-bash numeric compare if not).
#      NEVER sort candidates by their full path -- "pzzld" sorts
#      lexicographically above "fl03" and would happen to pick the newer
#      binary today, but that is an accident of two publisher slugs, not a
#      version comparison, and would pick the WRONG binary the day the names
#      (or a third publisher) sort the other way.
set -eu -o pipefail

# Numeric, segment-by-segment comparison of two dot-separated version
# strings. Returns success (0) when $1 > $2. Used only when `sort -V` is
# absent or does not actually behave correctly (see sort_v_works) --
# degrading to a PLAIN sort here would silently reintroduce #235's bug
# (lexicographic "6.4.9" > "6.4.10" is false; numeric it is true).
version_gt() {
  local a="$1" b="$2"
  local -a a_parts b_parts
  IFS='.' read -r -a a_parts <<<"$a"
  IFS='.' read -r -a b_parts <<<"$b"
  local i max ai bi da db
  max=${#a_parts[@]}
  [ "${#b_parts[@]}" -gt "$max" ] && max=${#b_parts[@]}
  for (( i = 0; i < max; i++ )); do
    ai="${a_parts[i]:-0}"; bi="${b_parts[i]:-0}"
    da="${ai//[!0-9]/}"; db="${bi//[!0-9]/}"
    [ -z "$da" ] && da=0
    [ -z "$db" ] && db=0
    if (( 10#$da > 10#$db )); then return 0; fi
    if (( 10#$da < 10#$db )); then return 1; fi
  done
  return 1
}

# Confirms `sort -V` is not just present but actually orders version
# segments numerically -- some minimal `sort` builds (e.g. non-GNU) accept
# an unknown flag without erroring and silently fall back to a plain
# lexicographic sort, which would reintroduce #235's exact bug class.
sort_v_works() {
  command -v sort >/dev/null 2>&1 || return 1
  [ "$(printf '6.4.9\n6.4.10\n' | sort -V 2>/dev/null | tail -n1)" = "6.4.10" ]
}

fail() {
  echo "shctx: $*" >&2
  exit 1
}

# Execs the resolved binary with the launcher's original args, preserving
# the caller's cwd (exec never changes directory). Falls back to `bash
# <path>` when the file exists but lacks the executable bit -- a cache
# extraction that didn't preserve permissions is a fixable condition, not a
# reason to fail.
run_binary() {
  local binary="$1"; shift
  if [ -x "$binary" ]; then
    exec "$binary" "$@"
  elif [ -f "$binary" ]; then
    exec bash "$binary" "$@"
  fi
  fail "resolved binary '$binary' does not exist"
}

# 1. Harness-declared plugin root -- trusted unconditionally when set.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  BINARY="$CLAUDE_PLUGIN_ROOT/bin/shepherd"
  [ -e "$BINARY" ] || fail "\$CLAUDE_PLUGIN_ROOT is set to '$CLAUDE_PLUGIN_ROOT' but $BINARY does not exist -- refusing to silently fall back to a scanned install (that silent substitution is the #235 bug class). Fix \$CLAUDE_PLUGIN_ROOT, or unset it to use the cache scan."
  run_binary "$BINARY" "$@"
fi

# 2. Bare-shell fallback: scan every publisher's shepherd install under the
#    plugin cache. SHCTX_CACHE_ROOT overrides the cache root for testing.
CACHE_ROOT="${SHCTX_CACHE_ROOT:-$HOME/.claude/plugins/cache}"

shopt -s nullglob
CANDIDATES=("$CACHE_ROOT"/*/shepherd/*)
shopt -u nullglob

VERSION_DIRS=()
for c in "${CANDIDATES[@]}"; do
  [ -d "$c" ] && [ -e "$c/bin/shepherd" ] && VERSION_DIRS+=("$c")
done

if [ "${#VERSION_DIRS[@]}" -eq 0 ]; then
  fail "no shepherd plugin install found. \$CLAUDE_PLUGIN_ROOT is unset and nothing under '$CACHE_ROOT'/*/shepherd/*/bin/shepherd resolved. Install the plugin (see README.md), or set \$CLAUDE_PLUGIN_ROOT / \$SHCTX_CACHE_ROOT."
fi

BEST=""
if sort_v_works; then
  BEST_LINE="$(for c in "${VERSION_DIRS[@]}"; do printf '%s\t%s\n' "${c##*/}" "$c"; done \
    | sort -t "$(printf '\t')" -k1,1V | tail -n1)"
  BEST="${BEST_LINE#*"$(printf '\t')"}"
else
  BEST_VERSION=""
  for c in "${VERSION_DIRS[@]}"; do
    v="${c##*/}"
    if [ -z "$BEST_VERSION" ] || version_gt "$v" "$BEST_VERSION"; then
      BEST_VERSION="$v"
      BEST="$c"
    fi
  done
fi

run_binary "$BEST/bin/shepherd" "$@"
SHCTX_LAUNCHER_EOF

chmod 0755 "$STAGED"

if [ -f "$DEST" ] && cmp -s "$STAGED" "$DEST"; then
  echo "install-shctx-launcher: $DEST already up to date (no changes)"
  exit 0
fi

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  BACKUP="${DEST}.bak.$(date +%Y%m%d%H%M%S)"
  cp -p "$DEST" "$BACKUP"
  echo "install-shctx-launcher: backed up existing $DEST -> $BACKUP"
fi

cp "$STAGED" "$DEST"
chmod 0755 "$DEST"
echo "install-shctx-launcher: wrote $DEST (mode 0755)"
echo "install-shctx-launcher: resolution order: \$CLAUDE_PLUGIN_ROOT (harness-set) -> highest-version cache/*/shepherd/* by semver (bare-shell fallback)"

if ! command -v sort >/dev/null 2>&1 || [ "$(printf '6.4.9\n6.4.10\n' | sort -V 2>/dev/null | tail -n1)" != "6.4.10" ]; then
  echo "install-shctx-launcher: WARNING -- 'sort -V' is unavailable or non-numeric on this system; the installed launcher will use its pure-bash version-compare fallback." >&2
fi
