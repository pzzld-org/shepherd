#!/usr/bin/env bash
# skills/context/tests/test_cmd_filetree.sh
#
# shctx filetree (v6.2.7, #180 follow-up): emits a JSON inventory of
# shepherd's own prompt/instruction surface. Pins: valid JSON on --stdout,
# the exclusion rules (plugin manifest / scripts / human-only docs / doctrine
# candidates / dated spec docs are NOT load_bearing), and that the dispatcher
# routes `filetree` correctly.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

fails=0
note() { printf '  %s\n' "$1"; }

# 1. --stdout emits valid, parseable JSON (no summary text mixed in).
out="$(bash skills/context/scripts/shctx filetree --stdout 2>/dev/null)"
if ! printf '%s' "$out" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
  note "FAIL: --stdout did not emit valid JSON"
  fails=$((fails+1))
else
  note "PASS: --stdout emits valid JSON"
fi

# 2. Every entry has the expected shape.
shape_ok="$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
required = {"path", "kind", "surface", "load_bearing", "lines", "words", "bytes"}
bad = [f for f in d["files"] if not required.issubset(f.keys())]
print("ok" if not bad else "bad")
')"
if [[ "$shape_ok" == "ok" ]]; then
  note "PASS: every entry has path/kind/surface/load_bearing/lines/words/bytes"
else
  note "FAIL: some entry is missing a required field"
  fails=$((fails+1))
fi

# 3. Exclusion rules: known non-load-bearing files are present but flagged false.
excl_ok="$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
by_path = {f["path"]: f for f in d["files"]}
checks = []
# docs/specs/* -> docs-spec, not load-bearing
specs = [f for p, f in by_path.items() if p.startswith("docs/specs/")]
checks.append(all(not f["load_bearing"] and f["kind"] == "docs-spec" for f in specs) if specs else True)
# doctrines/_candidates/* -> doctrine-candidate, not load-bearing, if any exist
cands = [f for p, f in by_path.items() if "doctrines/_candidates/" in p]
checks.append(all(not f["load_bearing"] and f["kind"] == "doctrine-candidate" for f in cands) if cands else True)
print("ok" if all(checks) else "bad")
')"
if [[ "$excl_ok" == "ok" ]]; then
  note "PASS: docs-spec / doctrine-candidate entries correctly flagged non-load-bearing"
else
  note "FAIL: exclusion classification is wrong"
  fails=$((fails+1))
fi

# 4. Known load-bearing agent file is present and flagged true.
agent_ok="$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
row = next((f for f in d["files"] if f["path"] == "agents/conductor.md"), None)
print("ok" if row and row["load_bearing"] and row["kind"] == "agent" and row["surface"] == "flock" else "bad")
')"
if [[ "$agent_ok" == "ok" ]]; then
  note "PASS: agents/conductor.md present, load_bearing=true, kind=agent, surface=flock"
else
  note "FAIL: agents/conductor.md misclassified or missing"
  fails=$((fails+1))
fi

# 5. Plugin manifest / scripts / human-only docs are NEVER in the file list at all
#    (excluded outright, not just flagged false).
excluded_absent="$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
paths = {f["path"] for f in d["files"]}
forbidden = [".claude-plugin/plugin.json", "README.md", "CHANGELOG.md",
             "hooks/hooks.json", "skills/context/scripts/shctx"]
present = [p for p in forbidden if p in paths]
print("ok" if not present else ",".join(present))
')"
if [[ "$excluded_absent" == "ok" ]]; then
  note "PASS: plugin manifest / scripts / human-only docs excluded outright"
else
  note "FAIL: unexpectedly present in inventory: $excluded_absent"
  fails=$((fails+1))
fi

# 6. --out=<path> writes to the given path.
tmp_out="$(mktemp -d)/ft.json"
bash skills/context/scripts/shctx filetree --out="$tmp_out" >/dev/null 2>&1
if [[ -f "$tmp_out" ]] && python3 -c "import json; json.load(open('$tmp_out'))" 2>/dev/null; then
  note "PASS: --out=<path> writes valid JSON to the given path"
else
  note "FAIL: --out=<path> did not write valid JSON"
  fails=$((fails+1))
fi
rm -rf "$(dirname "$tmp_out")"

if [[ "$fails" -gt 0 ]]; then
  echo "FAIL: test_cmd_filetree ($fails failure(s))"
  exit 1
fi
echo "PASS: test_cmd_filetree"
