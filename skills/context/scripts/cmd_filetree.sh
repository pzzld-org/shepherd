#!/usr/bin/env bash
# shctx filetree — emit a JSON inventory of shepherd's own prompt/instruction
# surface (v6.2.7, #180 follow-up).
#
# Adapted from an axiom-project sibling script of the same shape (crate/LOC/
# bytes inventory for a Rust workspace) — this variant is scoped to what
# actually costs Claude tokens in THIS plugin: every markdown file that gets
# read into an agent's context at some point (agent profiles, slash commands,
# skill entry points, doctrines, references, per-language style guides, the
# two core dispatch references, and the repo's own dogfood CLAUDE.md).
# Explicitly EXCLUDED as non-load-bearing: .claude-plugin/*.json (plugin
# manifest, never read by an agent), hooks.json, schema/*.sql, every *.sh/*.py
# script (executed, not prompted), human-only docs (README.md, CHANGELOG.md,
# CONTRIBUTING.md, CODE_OF_CONDUCT.md, LICENSE), docs/specs/** (dated
# planning artifacts, not live operating doctrine), doctrines/_candidates/**
# (proposals not yet adopted into the live citation graph), and examples/**
# (sample consumer projects, not shepherd's own surface).
#
# Each entry: {"path","kind","surface","lines","bytes","words"}.
#   kind    — functional role: agent | command | skill-entry | doctrine |
#             doctrine-meta | reference | agent-reference | style | example |
#             core | docs | claude-md
#   surface — which subsystem it belongs to: flock | commands | shepherd-skill
#             | context-skill | docs | root
#
# Usage: shctx filetree [--stdout] [--out=<path>] [--md]
#   (no flags)   write <namespace>/filetree.json, print a one-line summary
#   --stdout     print the JSON to stdout instead of writing a file
#   --out=<path> write to an explicit path instead of the namespace default
#   --md         also print a markdown summary table (totals per kind) to
#                stdout — the deterministic "are we bloating again" report
#
# Run this at the start (or close) of every sprint per CLAUDE.md's own
# "measurable outcome" rule: a rising total is a signal, not a vibe.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

STDOUT=0
MD=0
OUT=""
for a in "$@"; do
  case "$a" in
    --stdout)   STDOUT=1 ;;
    --out=*)    OUT="${a#--out=}" ;;
    --md)       MD=1 ;;
    *)          echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

if [[ -z "$OUT" ]]; then
  ns="$(resolve_namespace 2>/dev/null || echo .shepherd)"
  OUT="$ns/filetree.json"
fi

kind_surface_of() {
  local p="$1"
  case "$p" in
    agents/*.md)                                    echo "agent flock" ;;
    commands/*.md)                                  echo "command commands" ;;
    skills/shepherd/SKILL.md|skills/context/SKILL.md)
      case "$p" in
        skills/shepherd/*) echo "skill-entry shepherd-skill" ;;
        *)                 echo "skill-entry context-skill" ;;
      esac ;;
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

# Load-bearing predicate: everything the classifier resolved to a real kind
# EXCEPT doctrine-candidate (proposal, not live) and docs-spec (archival) and
# other (unclassified — shouldn't happen given the glob below, but fail
# closed rather than silently counting an unknown file as load-bearing).
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
  mkdir -p "$(dirname "$OUT")"
  cp "$TMP_JSON" "$OUT"
fi

# Deterministic summary — never eyeballed, per CLAUDE.md's own rule that
# arithmetic belongs in a script, not in a model's head.
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

if [[ "$STDOUT" -eq 0 ]]; then
  echo "wrote $OUT" >&2
fi
summarize >&2
