#!/usr/bin/env bash
# test_workdir.sh — resolve_workdir / resolve_namespace precedence (v6.0.2).
#
# Self-contained: no sqlite3, no git. Sources the skills lib, then pins
# shctx_repo_root to a throwaway temp dir so we control exactly which of
# .shepherd/ and .artifacts/ exist for each assertion.
source "$(dirname "$0")/_assert.sh"
set -eu -o pipefail

SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# SHCTX_QUIET keeps the split-brain warning off stderr by default; (d) re-enables
# it explicitly to assert the warning fires.
SHCTX_QUIET=1 source "$SHCTX_SKILL_ROOT/scripts/_lib.sh"

TMP="$(mktemp -d -t shctx-workdir.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Pin the repo root so resolution is hermetic.
shctx_repo_root() { echo "$TMP"; }

reset_dirs() { rm -rf "$TMP/.shepherd" "$TMP/.artifacts"; }

# (a) SHEPHERD_WORKDIR=foo (relative) → <root>/foo
reset_dirs
out="$(SHEPHERD_WORKDIR=foo resolve_workdir)"
assert_eq "workdir-relative" "$out" "$TMP/foo"

# (a') SHEPHERD_WORKDIR absolute → used as-is
out="$(SHEPHERD_WORKDIR=/abs/work resolve_workdir)"
assert_eq "workdir-absolute" "$out" "/abs/work"

# (b) only .artifacts present → .artifacts
reset_dirs
mkdir -p "$TMP/.artifacts"
out="$(resolve_workdir)"
assert_eq "fallback-artifacts" "$out" "$TMP/.artifacts"

# (c) neither present → .shepherd (default)
reset_dirs
out="$(resolve_workdir)"
assert_eq "default-shepherd" "$out" "$TMP/.shepherd"

# (d) both present → .shepherd (by precedence) + split-brain warning on stderr
reset_dirs
mkdir -p "$TMP/.shepherd" "$TMP/.artifacts"
err="$(SHCTX_QUIET= resolve_workdir 2>&1 >/dev/null)"
out="$(SHCTX_QUIET= resolve_workdir 2>/dev/null)"
assert_eq "split-brain-picks-shepherd" "$out" "$TMP/.shepherd"
assert_contains "split-brain-warns" "$err" "both .shepherd/ and .artifacts/ exist"

# shctx_artifacts_root must delegate (legacy name == resolve_workdir).
reset_dirs
out="$(SHEPHERD_WORKDIR=bar shctx_artifacts_root)"
assert_eq "legacy-name-delegates" "$out" "$TMP/bar"

# Derived path helpers inherit the override. DB filename (v6.1.2): the new
# default is shepherd.db; a pre-existing root.db is honored (legacy back-compat);
# shepherd.db wins when both are present.
mkdir -p "$TMP/bar"
out="$(SHEPHERD_WORKDIR=bar shctx_db_path)"
assert_eq "db-path-default-shepherd" "$out" "$TMP/bar/shepherd.db"

: > "$TMP/bar/root.db"
out="$(SHEPHERD_WORKDIR=bar shctx_db_path)"
assert_eq "db-path-legacy-rootdb" "$out" "$TMP/bar/root.db"

: > "$TMP/bar/shepherd.db"
out="$(SHEPHERD_WORKDIR=bar shctx_db_path)"
assert_eq "db-path-prefers-shepherd" "$out" "$TMP/bar/shepherd.db"
rm -f "$TMP/bar/root.db" "$TMP/bar/shepherd.db"

echo "PASS: workdir"
