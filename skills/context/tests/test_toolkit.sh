#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
# toolkit does NOT require 'shctx init' (no DB dependency — JSON-only).
# Use a fresh SHEPHERD_WORKDIR that is clean and local to this test.
export SHEPHERD_WORKDIR="$SHCTX_TEST_TMP"
# Isolate the global tier under the temp root so --global never touches the
# operator's real ~/.config/shepherd/toolkit.json.
export XDG_CONFIG_HOME="$SHCTX_TEST_TMP/xdg"

# ---- init -------------------------------------------------------------------
"$SHCTX" toolkit init --scope=local
assert_file "$SHCTX_TEST_TMP/toolkit.json"
# Schema should be copied to types/.
assert_file "$SHCTX_TEST_TMP/types/toolkit.schema.json"
# Idempotent: second init must not overwrite.
echo '{"version":1,"scope":"local","updated_at":1,"tools":[]}' > "$SHCTX_TEST_TMP/toolkit.json"
"$SHCTX" toolkit init --scope=local
val=$(jq '.updated_at' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "init-idempotent" "$val" "1"

# ---- add --------------------------------------------------------------------
"$SHCTX" toolkit add \
  --name=context7 --type=mcp \
  --description="Up-to-date library docs" \
  --capabilities=library-docs,api-reference \
  --invocation=mcp__Context7__query-docs \
  --tags=docs --pin

n=$(jq '.tools | length' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "add.count" "$n" "1"
name=$(jq -r '.tools[0].name' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "add.name" "$name" "context7"
pinned=$(jq -r '.tools[0].pinned' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "add.pinned" "$pinned" "true"

# Duplicate name should fail.
"$SHCTX" toolkit add --name=context7 --type=mcp --description="dup" --capabilities=x && {
  echo "FAIL: duplicate add should have failed" >&2; exit 1
} || true

# Add a second tool (non-canonical type triggers warn, not error).
"$SHCTX" toolkit add \
  --name=homelab --type=service \
  --description="SSH target: home server" \
  --capabilities=remote-shell,ssh

n=$(jq '.tools | length' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "add.count2" "$n" "2"

# ---- list -------------------------------------------------------------------
out=$("$SHCTX" toolkit list --scope=local --md)
assert_contains "list.md" "$out" "context7"
assert_contains "list.md.2" "$out" "homelab"

# JSON output.
out=$("$SHCTX" toolkit list --scope=local --json)
assert_contains "list.json" "$out" "context7"

# Type filter.
out=$("$SHCTX" toolkit list --scope=local --type=mcp --md)
assert_contains "list.type-filter" "$out" "context7"
# homelab (service) should not appear under --type=mcp.
! grep -q "homelab" <<< "$out" || { echo "FAIL: type filter did not exclude homelab" >&2; exit 1; }

# ---- show -------------------------------------------------------------------
out=$("$SHCTX" toolkit show context7 --md)
assert_contains "show.md" "$out" "context7"
assert_contains "show.invocation" "$out" "mcp__Context7__query-docs"

out=$("$SHCTX" toolkit show context7 --json)
assert_contains "show.json" "$out" '"name"'

# show unknown tool errors.
"$SHCTX" toolkit show no_such_tool && { echo "FAIL: show unknown should error" >&2; exit 1; } || true

# ---- md — brief injection ---------------------------------------------------
out=$("$SHCTX" toolkit md --scope=local)
assert_contains "md" "$out" "context7"
assert_contains "md.header" "$out" "Available tools"
# Graceful-empty: no tools matching filter → empty output, exit 0.
out=$("$SHCTX" toolkit md --scope=local --type=skill)
[[ -z "$out" ]] || { echo "FAIL: md should be empty when no matching tools" >&2; exit 1; }

# ---- pin / unpin ------------------------------------------------------------
"$SHCTX" toolkit unpin context7
pinned=$(jq -r '.tools[] | select(.name=="context7") | .pinned' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "unpin" "$pinned" "false"

"$SHCTX" toolkit pin context7
pinned=$(jq -r '.tools[] | select(.name=="context7") | .pinned' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "pin" "$pinned" "true"

# pin unknown errors.
"$SHCTX" toolkit pin no_such && { echo "FAIL: pin unknown should error" >&2; exit 1; } || true

# ---- validate ---------------------------------------------------------------
out=$("$SHCTX" toolkit validate --scope=local 2>&1)
assert_contains "validate.ok" "$out" "2 tool(s)"
# validate exits 0 when there are only warnings.
"$SHCTX" toolkit validate --scope=local 2>/dev/null

# Corrupt a tool to trigger a hard error, confirm non-zero exit.
jq '.tools[0].description = ""' "$SHCTX_TEST_TMP/toolkit.json" > "$SHCTX_TEST_TMP/toolkit.json.tmp" \
  && mv "$SHCTX_TEST_TMP/toolkit.json.tmp" "$SHCTX_TEST_TMP/toolkit.json"
"$SHCTX" toolkit validate --scope=local 2>/dev/null && {
  echo "FAIL: validate should exit non-zero on missing description" >&2; exit 1
} || true
# Restore.
jq '.tools[0].description = "Up-to-date library docs"' "$SHCTX_TEST_TMP/toolkit.json" \
  > "$SHCTX_TEST_TMP/toolkit.json.tmp" && mv "$SHCTX_TEST_TMP/toolkit.json.tmp" "$SHCTX_TEST_TMP/toolkit.json"

# ---- rm ---------------------------------------------------------------------
"$SHCTX" toolkit rm homelab
n=$(jq '.tools | length' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "rm.count" "$n" "1"

# rm unknown errors.
"$SHCTX" toolkit rm no_such && { echo "FAIL: rm unknown should error" >&2; exit 1; } || true

# ---- flag aliases: --desc / --local / --global (v6.1.3) ---------------------
# --desc is an alias for --description; --local for --scope=local. At this point
# only context7 remains in the local toolkit (count 1).
"$SHCTX" toolkit add --name=aliased --type=cli --desc="via --desc alias" --capabilities=x --local
desc=$(jq -r '.tools[] | select(.name=="aliased") | .description' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "alias.desc" "$desc" "via --desc alias"
scope=$(jq -r '.tools[] | select(.name=="aliased") | .scope' "$SHCTX_TEST_TMP/toolkit.json")
assert_eq "alias.local-scope" "$scope" "local"
"$SHCTX" toolkit rm aliased --local   # restore local count to 1

# --global routes to the global tier (isolated XDG under the temp root).
"$SHCTX" toolkit add --name=globaltool --type=cli --desc="user-wide" --capabilities=x --global
assert_file "$SHCTX_TEST_TMP/xdg/shepherd/toolkit.json"
gname=$(jq -r '.tools[0].name' "$SHCTX_TEST_TMP/xdg/shepherd/toolkit.json")
assert_eq "alias.global-add" "$gname" "globaltool"
# md --scope=all merges both tiers and surfaces the global tool.
out=$("$SHCTX" toolkit md --scope=all)
assert_contains "alias.global-merge" "$out" "globaltool"
# rm --global removes from the global tier.
"$SHCTX" toolkit rm globaltool --global
gn=$(jq '.tools | length' "$SHCTX_TEST_TMP/xdg/shepherd/toolkit.json")
assert_eq "alias.global-rm" "$gn" "0"

# ---- graceful-empty: no toolkit.json at all ---------------------------------
rm -f "$SHCTX_TEST_TMP/toolkit.json"
out=$("$SHCTX" toolkit list --scope=local)
[[ -z "$out" ]] || { echo "FAIL: list with no toolkit.json should be empty" >&2; exit 1; }
out=$("$SHCTX" toolkit md --scope=local)
[[ -z "$out" ]] || { echo "FAIL: md with no toolkit.json should be empty" >&2; exit 1; }

# validate with missing file → skips gracefully.
"$SHCTX" toolkit validate --scope=local 2>/dev/null
