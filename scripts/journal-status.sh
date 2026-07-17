#!/usr/bin/env bash
# scripts/journal-status.sh — deterministic Dynamic-Workflow wave-return signal (GH #213).
#
# WHY: during a live wave (v0.3.8-dev.5) a Workflow run was demonstrably mid-flight
# — 13 agents spawned, journal.jsonl actively appending — yet the harness TASK
# REGISTRY was blind to it (TaskGet "not found", TaskList "no tasks"). After a
# /compact the dispatcher lost the handle entirely; recovery meant hand-parsing
# journal.jsonl. So wave-return detection must be deterministic FILE-POLLING of the
# journal, never registry trust. This is that poll: point it at a run's journal and
# it reports how many steps spawned, how many returned, and their PASS/REDO verdicts.
# The wave routine (skills/shepherd/references/wave-routine.md §Root gate step 1)
# and the spawn/start watchdog until-loop call it.
#
# JOURNAL SCHEMA (observed, stable): append-only JSONL; each record
#   {"type":"started","key":"<content-hash>","agentId":"<id>"}          # a step began
#   {"type":"result","key":"<content-hash>","agentId":"<id>","result":<payload>}  # returned
# A step is identified by its content-hash `key` (stable across resume); started and
# result share the key. Verdict is scanned from the result payload text (a coder+
# auditor step returns PASS/REDO). Unknown record types are ignored, so a schema
# addition never breaks the count.
#
# USAGE: journal-status.sh <journal.jsonl>
# OUTPUT (stdout):
#   journal: <path>
#   steps=<started> returned=<returned> pass=<P> redo=<R> pending=<started-returned>
#   <key8> <agentId> <returned|pending> [PASS|REDO]   (one per step, first-seen order)
# EXIT: 3 journal absent (not yet emitted) · 4 some step still pending · 0 all returned.

set -uo pipefail

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: journal-status.sh <journal.jsonl>"
  [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && exit 0 || exit 2
fi
JOURNAL="$1"
if [[ ! -f "$JOURNAL" ]]; then
  echo "journal: $JOURNAL (absent — wave not yet emitting)" >&2
  exit 3
fi

python3 - "$JOURNAL" <<'PY'
import json, re, sys

path = sys.argv[1]
started = []          # step keys, first-seen order
started_agent = {}    # key -> agentId
results = {}          # key -> payload text
verdict_re = re.compile(r"\b(REDO|PASS)\b")

with open(path, errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):  # a bare array/number/string/null is valid
            continue                   # JSON but not a record — tolerate, don't crash
        t = rec.get("type")
        key = rec.get("key") or rec.get("agentId")
        if key is None:
            continue
        if t == "started":
            if key not in started_agent:
                started.append(key)
            started_agent.setdefault(key, rec.get("agentId", "?"))
        elif t == "result":
            payload = rec.get("result", "")
            results[key] = payload if isinstance(payload, str) else json.dumps(payload)
            if key not in started_agent:      # result seen before started (rare ordering)
                started.append(key)
                started_agent[key] = rec.get("agentId", "?")

def verdict(text):
    m = verdict_re.search(text or "")
    return m.group(1) if m else ""

pass_n = sum(1 for k, txt in results.items() if verdict(txt) == "PASS")
redo_n = sum(1 for k, txt in results.items() if verdict(txt) == "REDO")
returned = len(results)
steps = len(started)
pending = steps - returned

print(f"journal: {path}")
print(f"steps={steps} returned={returned} pass={pass_n} redo={redo_n} pending={pending}")
for key in started:
    short = key.split(":", 1)[-1][:8]
    agent = started_agent.get(key, "?")
    if key in results:
        v = verdict(results[key])
        print(f"  {short} {agent} returned{(' ' + v) if v else ''}")
    else:
        print(f"  {short} {agent} pending")

sys.exit(0 if steps > 0 and pending == 0 else 4)
PY
