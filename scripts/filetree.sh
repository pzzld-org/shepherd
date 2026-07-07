#!/usr/bin/env bash
# scripts/filetree.sh — dev-only inventory of shepherd's own prompt surface.
#
# NOT part of the shipped plugin. Not wired into `shctx`, not cited by any
# agent/doctrine/skill file, not something the flock ever runs. This is a
# tool for whoever (human or Claude session) is maintaining THIS repo to
# check, at the start or end of a work session, whether the plugin's own
# prompt/instruction surface (the thing that costs Opus/Sonnet tokens on
# every dispatch) is growing. Run it by hand: `bash scripts/filetree.sh`.
#
# Writes scripts/.filetree.json (gitignored) with an entry per file that
# actually gets read into an agent's context at some point: agent profiles,
# slash commands, skill entry points, doctrines, references, per-language
# style guides, the two core dispatch references, and the repo's own
# dogfood CLAUDE.md. Excluded outright: the plugin manifest (.claude-plugin/
# *.json, never read by an agent), hooks.json, schema/*.sql, every *.sh/*.py
# script (executed, not prompted), human-only docs (README/CHANGELOG/
# CONTRIBUTING/CODE_OF_CONDUCT/LICENSE), docs/specs/** (dated planning
# artifacts), doctrines/_candidates/** (unadopted proposals), and examples/**
# (sample consumer projects, not this plugin's own surface).
#
# Usage: scripts/filetree.sh [--stdout] [--md]
#   (no flags)   write scripts/.filetree.json, print a one-line total
#   --stdout     print the JSON to stdout instead of writing a file
#   --md         also print a per-kind markdown summary table

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

STDOUT=0
MD=0
for a in "$@"; do
  case "$a" in
    --stdout) STDOUT=1 ;;
    --md)     MD=1 ;;
    *)        echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

OUT="scripts/.filetree.json"

kind_surface_of() {
  local p="$1"
  case "$p" in
    agents/*.md)                                    echo "agent flock" ;;
    commands/*.md)                                  echo "command commands" ;;
    skills/shepherd/SKILL.md)                        echo "skill-entry shepherd-skill" ;;
    skills/context/SKILL.md)                         echo "skill-entry context-skill" ;;
    skills/adaptation/SKILL.md)                      echo "skill-entry adaptation-skill" ;;
    skills/motivation/SKILL.md)                      echo "skill-entry motivation-skill" ;;
    skills/harness/SKILL.md)                         echo "skill-entry harness-skill" ;;
    skills/thinking/SKILL.md)                        echo "skill-entry thinking-skill" ;;
    skills/harness/references/*.md)                  echo "reference harness-skill" ;;
    skills/shepherd/pipeline.md|skills/shepherd/flock.md)
                                                     echo "core shepherd-skill" ;;
    skills/shepherd/doctrines/_candidates/*.md)      echo "doctrine-candidate shepherd-skill" ;;
    skills/shepherd/doctrines/README.md)             echo "doctrine-meta shepherd-skill" ;;
    skills/shepherd/doctrines/*.md)                  echo "doctrine shepherd-skill" ;;
    skills/shepherd/agents/*.reference.md)           echo "agent-reference shepherd-skill" ;;
    skills/shepherd/references/*.md)                 echo "reference shepherd-skill" ;;
    skills/context/references/*.md)                  echo "reference context-skill" ;;
    skills/context/examples/*.md)                    echo "example context-skill" ;;
    skills/context/styles/*.md)                      echo "style context-skill" ;;
    docs/specs/*.md)                                  echo "docs-spec docs" ;;
    docs/*.md)                                        echo "docs docs" ;;
    CLAUDE.md)                                        echo "claude-md root" ;;
    *)                                                 echo "other other" ;;
  esac
}

is_load_bearing() {
  case "$1" in
    doctrine-candidate|docs-spec|other) return 1 ;;
    *) return 0 ;;
  esac
}

FILES="$(git ls-files \
    'agents/*.md' \
    'commands/*.md' \
    'skills/**/*.md' \
    'docs/*.md' \
    'docs/specs/*.md' \
    'CLAUDE.md' \
  2>/dev/null | LC_ALL=C sort -u)"

TMP_JSON="$(mktemp)"
trap 'rm -f "$TMP_JSON"' EXIT

{
  printf '{\n  "generated_at": "%s",\n  "files": [\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  first=1
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    read -r kind surface <<<"$(kind_surface_of "$f")"
    lb="false"
    is_load_bearing "$kind" && lb="true"
    lines=$(wc -l < "$f" 2>/dev/null | tr -d ' ')
    bytes=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
    words=$(wc -w < "$f" 2>/dev/null | tr -d ' ')
    [[ $first -eq 1 ]] && first=0 || printf ',\n'
    printf '    {"path":"%s","kind":"%s","surface":"%s","load_bearing":%s,"lines":%s,"words":%s,"bytes":%s}' \
      "$f" "$kind" "$surface" "$lb" "${lines:-0}" "${words:-0}" "${bytes:-0}"
  done <<<"$FILES"
  printf '\n  ]\n}\n'
} > "$TMP_JSON"

if [[ "$STDOUT" -eq 1 ]]; then
  cat "$TMP_JSON"
else
  cp "$TMP_JSON" "$OUT"
  echo "wrote $OUT" >&2
fi

summarize() {
  if command -v jq >/dev/null 2>&1; then
    jq -r '
      [.files[] | select(.load_bearing)] as $lb
      | ($lb | length) as $n
      | ($lb | map(.lines) | add // 0) as $lines
      | ($lb | map(.words) | add // 0) as $words
      | ($lb | map(.bytes) | add // 0) as $bytes
      | "\($n) load-bearing files | \($lines) lines | \($words) words | \($bytes) bytes (~\(($words*13/10)) est. tokens)"
    ' "$TMP_JSON"
    if [[ "$MD" -eq 1 ]]; then
      echo ""
      echo "| kind | files | lines | words | ~tokens |"
      echo "|---|---|---|---|---|"
      jq -r '
        [.files[] | select(.load_bearing)]
        | group_by(.kind)
        | map({kind: .[0].kind, n: length, lines: (map(.lines)|add), words: (map(.words)|add)})
        | sort_by(-.words)
        | .[]
        | "| \(.kind) | \(.n) | \(.lines) | \(.words) | \((.words*13/10)|floor) |"
      ' "$TMP_JSON"
    fi
  else
    python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
lb = [f for f in d["files"] if f["load_bearing"]]
n = len(lb)
lines = sum(f["lines"] for f in lb)
words = sum(f["words"] for f in lb)
bytes_ = sum(f["bytes"] for f in lb)
print(f"{n} load-bearing files | {lines} lines | {words} words | {bytes_} bytes (~{words*13//10} est. tokens)")
if len(sys.argv) > 2 and sys.argv[2] == "md":
    print()
    print("| kind | files | lines | words | ~tokens |")
    print("|---|---|---|---|---|")
    by_kind = {}
    for f in lb:
        k = f["kind"]
        by_kind.setdefault(k, {"n": 0, "lines": 0, "words": 0})
        by_kind[k]["n"] += 1
        by_kind[k]["lines"] += f["lines"]
        by_kind[k]["words"] += f["words"]
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]["words"]):
        print(f"| {k} | {v[\"n\"]} | {v[\"lines\"]} | {v[\"words\"]} | {v[\"words\"]*13//10} |")
' "$TMP_JSON" "$([[ $MD -eq 1 ]] && echo md || echo "")"
  fi
}

summarize >&2
