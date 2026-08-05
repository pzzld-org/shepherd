#!/usr/bin/env bash
# hooks/tests/test_description_budget.sh — frontmatter description budget (v6.4.3).
#
# `skills/harness/SKILL.md §Lazy-load economics` states the rule: skill, agent,
# and command BODIES load only on invoke or dispatch, so at session start the
# ONLY text resident is each one's frontmatter `description`. That string is
# what every session pays for whether or not the thing is ever used, which is
# why the doctrine caps it at 200 characters and requires it to be
# load-bearing.
#
# The rule was doctrine-only until now, and doctrine with no teeth drifts: two
# descriptions had already gone over (commands/start.md at 206,
# skills/bridge/SKILL.md at 309) with nothing to notice. A cap that is only
# written down is a cap that is only sometimes true.
#
# Counts the description VALUE, joined and whitespace-collapsed, stopping at
# the next top-level frontmatter key. Note the key regex must allow `-`:
# `argument-hint:` is a real key on most commands, and a naive `^\w+:` runs
# straight past it and measures three fields as one -- which is exactly the
# false reading this file was written to avoid repeating.
#
# Exit 0 on pass; exit 1 listing every over-budget file.

set -uo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
LIMIT=200

command -v python3 >/dev/null 2>&1 || { echo "  SKIP  python3 absent"; exit 0; }

python3 - "$REPO_ROOT" "$LIMIT" <<'PY'
import glob, os, pathlib, re, sys

root, limit = sys.argv[1], int(sys.argv[2])
targets = sorted(
    glob.glob(os.path.join(root, "agents", "*.md"))
    + glob.glob(os.path.join(root, "commands", "*.md"))
    + glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))
)

fails = []
checked = 0
for path in targets:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        continue
    parts = text.split("---", 2)
    if len(parts) < 3:
        continue
    frontmatter = parts[1]
    # A top-level key may contain '-' or '_' (argument-hint, allowed-tools).
    match = re.search(
        r"^description:\s*(.*?)(?=^[A-Za-z][\w-]*:\s|\Z)", frontmatter, re.M | re.S
    )
    if not match:
        continue
    checked += 1
    desc = " ".join(match.group(1).split()).strip("\"'|>").strip()
    if len(desc) > limit:
        fails.append((os.path.relpath(path, root), len(desc)))

for rel, n in fails:
    print(f"  FAIL  {rel}: description is {n} chars (limit {limit}) — "
          f"every session pays for this string whether or not the file is used")

if fails:
    print(f"test_description_budget: {len(fails)} over the {limit}-char lazy-load budget "
          f"(skills/harness/SKILL.md §Lazy-load economics)")
    sys.exit(1)

print(f"test_description_budget: OK — {checked} frontmatter descriptions all within "
      f"the {limit}-char lazy-load budget")
PY
