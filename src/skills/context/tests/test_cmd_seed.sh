#!/usr/bin/env bash
# skills/context/tests/test_cmd_seed.sh — deterministic seed pre-flight gate (v6.2.1).
#
# `shctx seed verify` is a pure text gate (no DB, no network). Asserts a canonical
# seed passes; each HARD-failure class blocks with exit 1 (hallucinated file_scope
# path, TODO marker, prescriptive Lane-N numbering, a priority-bearing deliverable
# with no GH anchor, an oversized footprint); the (NEW) marker exempts a not-yet-
# existing path; an old-format / freeform seed degrades gracefully (no false block).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SEED="$ROOT/skills/context/scripts/cmd_seed.sh"

tmp="$(mktemp -d -t shctx-seed-test.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
mkdir -p src
echo x > src/real.rs    # an existing path the good seed references

cat > good.seed.md <<'EOF'
---
title: vX Seed — theme
branch: vX
base: vW
kind: sprint-seed
milestone: 12
file_scope:
  exclusive:
    - src/real.rs
  additive:
    - src/brand_new.rs (NEW)
---

## Phase 0 mesh

| # | Source | Query | Pass |
|---|--------|-------|------|
| 1 | issues | gh | ok |
| 2 | prs | gh | ok |
| 3 | milestones | gh | ok |
| 4 | git | log | ok |
| 5 | sentry | search | ok |
| 6 | datastore | schema | ok |
| 7 | close | report | ok |
| 8 | claude.md | read | ok |

## Deliverables

### Gate  [CRITICAL]

- **GH:** #101
- **Priority:** CRITICAL
- **Acceptance:** grep -q something
EOF

fails=0
ck() { # name file want_rc [want_substr]
  local name="$1" f="$2" want="$3" sub="${4:-}" out rc=0
  out="$(bash "$SEED" verify "$f")" || rc=$?
  if [[ "$rc" != "$want" ]]; then
    echo "  FAIL  $name: rc=$rc want=$want"; printf '%s\n' "$out" | sed 's/^/        /'; fails=$((fails+1)); return
  fi
  if [[ -n "$sub" ]] && ! grep -qF -- "$sub" <<<"$out"; then
    echo "  FAIL  $name: want substr '$sub' in: $out"; fails=$((fails+1)); return
  fi
  echo "  PASS  $name"
}

ck "good-canonical-passes" good.seed.md 0 "OK:"

sed 's#src/real.rs#nope/ghost.rs#' good.seed.md > bad_path.seed.md
ck "hallucinated-path-blocks" bad_path.seed.md 1 "does not resolve"

# (NEW) marker exempts a not-yet-existing path
sed 's#- src/real.rs#- src/future_thing.rs (NEW)#' good.seed.md > newmark.seed.md
ck "new-marker-exempts" newmark.seed.md 0 "OK:"

{ cat good.seed.md; echo "TODO: finish later"; } > bad_todo.seed.md
ck "todo-blocks" bad_todo.seed.md 1 "TODO"

{ cat good.seed.md; echo "Wave grouping: Lane 2 handles the hook."; } > bad_lane.seed.md
ck "lane-n-blocks" bad_lane.seed.md 1 "Lane N"

sed '/- \*\*GH:\*\* #101/d' good.seed.md > bad_nogh.seed.md
ck "missing-gh-blocks" bad_nogh.seed.md 1 "GH:"

{ cat good.seed.md; i=1; while [[ $i -le 410 ]]; do echo "filler $i"; i=$((i+1)); done; } > bad_big.seed.md
ck "oversized-blocks" bad_big.seed.md 1 "footprint"

# --- path-resolver tolerance (review FIX-FIRST: must not false-positive idiomatic seeds) ---
# glob that matches >=1 file passes (single-level — bash 3.2 has no globstar)
sed 's#- src/real.rs#- src/*.rs#' good.seed.md > glob_ok.seed.md
ck "glob-match-passes" glob_ok.seed.md 0 "OK:"
# glob that matches nothing blocks
sed 's#- src/real.rs#- ghostdir/*.rs#' good.seed.md > glob_miss.seed.md
ck "glob-nomatch-blocks" glob_miss.seed.md 1 "does not resolve"
# annotated (em-dash) path on an existing file passes
sed 's#- src/real.rs#- src/real.rs — the core parser#' good.seed.md > annot.seed.md
ck "annotated-path-passes" annot.seed.md 0 "OK:"
# parenthetical annotation on an existing file passes
sed 's#- src/real.rs#- src/real.rs (the helper)#' good.seed.md > paren.seed.md
ck "paren-annotated-passes" paren.seed.md 0 "OK:"
# embellished (NEW - reason) marker passes
sed 's#- src/real.rs#- src/whatever.rs (NEW - the new parser)#' good.seed.md > newreason.seed.md
ck "new-embellished-passes" newreason.seed.md 0 "OK:"
# flow-style file_scope with a real path passes
sed 's#  exclusive:#  exclusive: [src/real.rs]#; /^    - src\/real.rs$/d' good.seed.md > flow_ok.seed.md
ck "flow-style-real-passes" flow_ok.seed.md 0 "OK:"
# flow-style file_scope with a ghost path BLOCKS (the false-negative the review caught)
sed 's#  exclusive:#  exclusive: [nope/ghost.rs]#; /^    - src\/real.rs$/d' good.seed.md > flow_ghost.seed.md
ck "flow-style-ghost-blocks" flow_ghost.seed.md 1 "does not resolve"

# old-format freeform seed (no canonical structure) must NOT hard-fail
cat > old.seed.md <<'EOF'
---
title: old
branch: v5
---
## North star
Some prose, no canonical structure.
## Scope items
### Item 1 — do a thing
- a bullet
EOF
ck "old-format-degrades" old.seed.md 0

# usage error when no path
rc=0; bash "$SEED" verify >/dev/null 2>&1 || rc=$?
if [[ "$rc" == "2" ]]; then echo "  PASS  no-path-usage-error"; else echo "  FAIL  no-path-usage-error rc=$rc"; fails=$((fails+1)); fi

if [[ "$fails" -eq 0 ]]; then echo "PASS: test_cmd_seed"; exit 0; else echo "FAIL: test_cmd_seed ($fails)"; exit 1; fi
