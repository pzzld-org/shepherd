#!/usr/bin/env bash
# test_worktree_root_resolution.sh — #221: shctx_repo_root + shctx_in_subworktree
# resolve the SHARED main worktree from inside a LINKED worktree, so the registry
# DB and config are never scoped per-worktree. Regression guard for the field bug
# where 6 concurrent /shepherd:spawn conductor worktrees each bound a stray empty
# per-worktree shepherd.db ("no such table: focus / no such table: teammates").
source "$(dirname "$0")/_assert.sh"
set -eu -o pipefail

command -v git >/dev/null 2>&1 || { echo "SKIP: worktree-root-resolution (git absent)"; exit 0; }

SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SHCTX_QUIET=1 source "$SHCTX_SKILL_ROOT/scripts/_lib.sh"

TMP="$(mktemp -d -t shctx-wtroot.XXXXXX)"
trap 'git -C "$TMP/main" worktree remove --force "$TMP/lane" 2>/dev/null || true; rm -rf "$TMP"' EXIT

# --- main worktree with a real (tracked) registry dir + config ---
mkdir -p "$TMP/main"
git -C "$TMP/main" init -q
git -C "$TMP/main" config user.email t@t
git -C "$TMP/main" config user.name t
git -C "$TMP/main" config commit.gpgsign false
mkdir -p "$TMP/main/.claude" "$TMP/main/.shepherd"
printf 'sprint = "s1"\n' > "$TMP/main/.claude/shepherd.toml"
: > "$TMP/main/.shepherd/shepherd.db"
git -C "$TMP/main" add -A
git -C "$TMP/main" commit -qm init

MAIN_REAL="$(cd "$TMP/main" && pwd -P)"

# A linked worktree (a lane) — git checks out the TRACKED .shepherd/ subtree into
# it (the exact condition that made resolve_workdir pick the worktree-local path).
git -C "$TMP/main" worktree add -q "$TMP/lane" -b lane-x

# ---- from the MAIN worktree ----
out="$(cd "$TMP/main" && shctx_repo_root)"
assert_eq "main-root-is-main" "$(cd "$out" && pwd -P)" "$MAIN_REAL"
( cd "$TMP/main" && shctx_in_subworktree ) && { echo "FAIL: main-flagged-as-linked" >&2; exit 1; } || true

# ---- from the LINKED worktree (the #221 core) ----
out="$(cd "$TMP/lane" && shctx_repo_root)"
assert_eq "lane-root-resolves-to-main" "$(cd "$out" && pwd -P)" "$MAIN_REAL"

# DB path from the lane targets the SHARED main registry, never a per-worktree DB.
dbp="$(cd "$TMP/lane" && shctx_db_path)"
assert_eq "lane-db-is-main-registry" \
  "$(cd "$(dirname "$dbp")" && pwd -P)/$(basename "$dbp")" \
  "$MAIN_REAL/.shepherd/shepherd.db"

# `shctx config path` surface (shctx_repo_root/.claude/shepherd.toml) → main.
cfgroot="$(cd "$TMP/lane" && shctx_repo_root)"
assert_eq "lane-config-is-main" "$cfgroot/.claude/shepherd.toml" "$MAIN_REAL/.claude/shepherd.toml"

# shctx_in_subworktree is true inside the lane.
( cd "$TMP/lane" && shctx_in_subworktree ) || { echo "FAIL: lane-not-flagged-as-linked" >&2; exit 1; }

echo "PASS: worktree-root-resolution"
