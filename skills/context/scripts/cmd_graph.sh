#!/usr/bin/env bash
# shctx graph <status|next|mark|trace|reset> [args]
#
# Rule-engine walker for the Stage Graph (the conductor's deterministic
# dispatch driver). Operates on the state.json that `shctx plan extract`
# materializes from the engineer's plan.
#
#   status [--json|--md]
#       Summary: nodes by state, ready batches, completion %, ETA hint.
#
#   next [--json]
#       Print the next-eligible dispatch batch. Honors parallel_with cliques.
#       Conductor reads this output, dispatches the batch in ONE message,
#       then `mark`s the completion. The walker does no LLM judgment —
#       edge labels are evaluated mechanically on the marked exit.
#
#   mark <node-id> --state=in_flight|done|skipped [--exit=<edge-label>]
#                                                  [--agent=<id>]
#       Advance node state. On --state=done, the optional --exit names the
#       outgoing edge that fired; downstream in_predicates are updated and
#       blocked nodes may become ready.
#
#   trace [--tail=N] [--json]
#       Inspect the append-only event log.
#
#   reset [--force]
#       Wipe state and trace (re-extract the plan to rebuild).
#
# Schema: doctrines/dispatch-cascade.md.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

_state_path() { echo "$(shctx_artifacts_root)/graph/state.json"; }
_trace_path() { echo "$(shctx_artifacts_root)/graph/trace.jsonl"; }

usage() {
  cat <<'EOF'
shctx graph <status|next|mark|trace|reset> [args]

  status [--json|--md]
      Nodes by state, ready batches, completion %.

  next [--json]
      Next-eligible dispatch batch (parallel_with cliques honored).
      Conductor: read this, dispatch one Agent batch, then `mark`.

  mark <node-id> --state=<in_flight|done|skipped> [--exit=<edge>] [--agent=<id>]
      Advance state. --state=done + --exit=<edge-label> fires the named
      outgoing edge and updates downstream nodes.

  trace [--tail=N] [--json]
      Read the append-only event log.

  reset [--force]
      Drop state and trace; re-extract to rebuild.

See doctrines/dispatch-cascade.md.
EOF
}

_require_state() {
  local s; s="$(_state_path)"
  [[ -f "$s" ]] || { echo "ERROR: no graph state at $s. Run 'shctx plan extract <plan.md>' first." >&2; exit 1; }
}

_trace_append() {
  python3 - "$(_trace_path)" "$@" <<'PY'
import json, sys, time
trace_path = sys.argv[1]
ev = {"at": int(time.time())}
for arg in sys.argv[2:]:
    k, _, v = arg.partition("=")
    ev[k] = v
with open(trace_path, "a") as f:
    f.write(json.dumps(ev) + "\n")
PY
}

# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
_cmd_status() {
  _require_state
  local fmt="text"
  for arg in "$@"; do
    case "$arg" in --json) fmt="json" ;; --md) fmt="md" ;; esac
  done

  python3 - "$(_state_path)" "$fmt" <<'PY'
import json, sys, collections
state = json.load(open(sys.argv[1])); fmt = sys.argv[2]
nodes = state["nodes"]
by_state = collections.Counter(n["state"] for n in nodes.values())
total = len(nodes)
done = by_state.get("done", 0)
pct = (done * 100) // total if total else 0

ready = [nid for nid, n in nodes.items() if n["state"] == "ready"]
in_flight = [nid for nid, n in nodes.items() if n["state"] == "in_flight"]

if fmt == "json":
    print(json.dumps({
        "sprint": state["sprint"],
        "total": total, "by_state": dict(by_state),
        "completion_pct": pct,
        "ready": ready, "in_flight": in_flight,
    }, indent=2))
elif fmt == "md":
    print(f"## Graph status — {state['sprint']}")
    print(f"_completion: {done}/{total} ({pct}%)_")
    print()
    for s in ("ready","in_flight","pending","done","skipped"):
        c = by_state.get(s, 0)
        if c: print(f"- **{s}**: {c}")
    if ready:
        print(f"\n**Ready now:** {', '.join('`'+n+'`' for n in ready)}")
    if in_flight:
        print(f"\n**In flight:** {', '.join('`'+n+'`' for n in in_flight)}")
else:
    print(f"Graph status — sprint: {state['sprint']}")
    print(f"  completion: {done}/{total} ({pct}%)")
    for s in ("ready","in_flight","pending","done","skipped"):
        c = by_state.get(s, 0)
        if c: print(f"  {s:<10}: {c}")
    if ready:      print(f"\n  Ready now:  {', '.join(ready)}")
    if in_flight:  print(f"  In flight:  {', '.join(in_flight)}")
PY
}

# ---------------------------------------------------------------------------
# next — return next-eligible batch (parallel_with cliques honored)
# ---------------------------------------------------------------------------
_cmd_next() {
  _require_state
  local fmt="text"
  for arg in "$@"; do
    case "$arg" in --json) fmt="json" ;; esac
  done

  python3 - "$(_state_path)" "$fmt" <<'PY'
import json, sys
state = json.load(open(sys.argv[1])); fmt = sys.argv[2]
nodes = state["nodes"]
# Ready = state == "ready" (no unmet in_predicates) and not yet in flight
ready = [n for n in nodes.values() if n["state"] == "ready"]

if not ready:
    if fmt == "json":
        print(json.dumps({"batch": [], "reason": "no ready nodes"}))
    else:
        in_flight = [n["id"] for n in nodes.values() if n["state"] == "in_flight"]
        if in_flight:
            print(f"No ready nodes. In flight: {', '.join(in_flight)} — `mark` them to advance.")
        else:
            pending = [n["id"] for n in nodes.values() if n["state"] == "pending"]
            if pending:
                print(f"No ready nodes; {len(pending)} pending with unmet in_predicates.")
            else:
                print("Graph complete — no nodes remain.")
    sys.exit(0)

# Coalesce by parallel_with cliques.
# A clique is the closure of a node's parallel_with set.
def clique_of(start_id):
    seen = {start_id}; stack = [start_id]
    while stack:
        cur = stack.pop()
        for peer in (nodes[cur].get("parallel_with") or []):
            if peer in seen or peer not in nodes: continue
            if nodes[peer]["state"] != "ready": continue
            seen.add(peer); stack.append(peer)
    return sorted(seen)

# Pick the first ready node; its clique is the batch.
# (Multiple disjoint cliques exist — the conductor fires one batch per `next`.)
seed = ready[0]
batch_ids = clique_of(seed["id"])
batch = [nodes[i] for i in batch_ids]

# Distill dispatch instructions per node
out = []
for n in batch:
    out.append({
        "id": n["id"],
        "type": n["type"],
        "agents": n.get("agents") or [],          # may be empty (conductor-inline)
        "parallel_with": [i for i in batch_ids if i != n["id"]],
    })

if fmt == "json":
    print(json.dumps({"batch": out, "count": len(out)}, indent=2))
else:
    print(f"Next batch ({len(out)} node(s) — fire in ONE Agent message):")
    for n in out:
        agents = n["agents"]
        if agents:
            for a in agents:
                print(f"  • {n['id']:<24} ({n['type']}) — @{a.get('role')} ×{a.get('count',1)}")
        else:
            print(f"  • {n['id']:<24} ({n['type']}) — conductor-inline")
    print()
    print("After dispatch+return:  shctx graph mark <id> --state=done --exit=<edge-label>")
PY
}

# ---------------------------------------------------------------------------
# mark <node-id> --state=... [--exit=...] [--agent=...]
# ---------------------------------------------------------------------------
_cmd_mark() {
  local nid="${1:-}"; shift || true
  [[ -n "$nid" ]] || { echo "ERROR: usage: shctx graph mark <node-id> --state=..." >&2; exit 1; }

  local target_state="" exit_edge="" agent=""
  for arg in "$@"; do
    case "$arg" in
      --state=*) target_state="${arg#--state=}" ;;
      --exit=*)  exit_edge="${arg#--exit=}" ;;
      --agent=*) agent="${arg#--agent=}" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ "$target_state" =~ ^(in_flight|done|skipped)$ ]] \
    || { echo "ERROR: --state must be in_flight|done|skipped" >&2; exit 1; }

  _require_state

  python3 - "$(_state_path)" "$(_trace_path)" "$nid" "$target_state" "$exit_edge" "$agent" <<'PY'
import json, sys, time
state_path, trace_path, nid, target, exit_edge, agent = sys.argv[1:]
state = json.load(open(state_path))
nodes = state["nodes"]
if nid not in nodes:
    sys.exit(f"ERROR: node {nid} not in graph")
n = nodes[nid]
now = int(time.time())

prev = n["state"]
n["state"] = target
if target == "in_flight":
    n["started_at"] = now
    if agent: n["agent_ids"] = list(set((n.get("agent_ids") or []) + [agent]))
elif target in ("done", "skipped"):
    n["exited_at"] = now
    if exit_edge: n["exit_edge"] = exit_edge
    # Satisfy any downstream in_predicates that match this exit_edge
    if target == "done" and exit_edge:
        for downstream in nodes.values():
            for p in downstream["in_predicates"]:
                if p["predecessor"] == nid and p["edge"] == exit_edge:
                    p["satisfied"] = True
        # Re-check readiness for all pending nodes
        for d in nodes.values():
            if d["state"] != "pending": continue
            if all(p["satisfied"] for p in d["in_predicates"]):
                d["state"] = "ready"

with open(state_path, "w") as f:
    json.dump(state, f, indent=2)

# Append trace event
ev = {"at": now, "event": "node_mark", "node": nid,
      "from": prev, "to": target}
if exit_edge: ev["exit_edge"] = exit_edge
if agent:     ev["agent_id"]  = agent
with open(trace_path, "a") as t:
    t.write(json.dumps(ev) + "\n")

# Report
newly_ready = [d["id"] for d in nodes.values() if d["state"] == "ready"]
print(f"marked: {nid}  {prev} → {target}" + (f"  exit={exit_edge}" if exit_edge else ""))
if newly_ready:
    print(f"newly ready: {', '.join(newly_ready)}")
PY
}

# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------
_cmd_trace() {
  local tail="" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --tail=*) tail="${arg#--tail=}" ;;
      --json)   fmt="json" ;;
    esac
  done
  local tp; tp="$(_trace_path)"
  [[ -f "$tp" ]] || { echo "(no trace yet at $tp)"; exit 0; }

  if [[ "$fmt" == "json" ]]; then
    if [[ -n "$tail" ]]; then tail -n "$tail" "$tp"; else cat "$tp"; fi
    return
  fi

  python3 - "$tp" "${tail:-0}" <<'PY'
import json, sys, datetime
tp, tail = sys.argv[1], int(sys.argv[2])
lines = open(tp).read().splitlines()
if tail > 0: lines = lines[-tail:]
for line in lines:
    try: ev = json.loads(line)
    except Exception: print("(unparseable)", line); continue
    ts = datetime.datetime.fromtimestamp(ev.get("at",0)).isoformat(timespec="seconds")
    evt = ev.pop("event", "?"); ev.pop("at", None)
    rest = " ".join(f"{k}={v}" for k,v in ev.items())
    print(f"{ts}  {evt:<16} {rest}")
PY
}

# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------
_cmd_reset() {
  local force=0
  for arg in "$@"; do case "$arg" in --force) force=1 ;; esac; done
  local sp tp; sp="$(_state_path)"; tp="$(_trace_path)"
  if (( force == 0 )); then
    echo "Will remove:"
    [[ -f "$sp" ]] && echo "  $sp"
    [[ -f "$tp" ]] && echo "  $tp"
    echo "Re-run with --force to confirm."
    exit 0
  fi
  rm -f "$sp" "$tp"
  echo "reset: graph state and trace removed."
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  status)       _cmd_status "$@" ;;
  next)         _cmd_next "$@" ;;
  mark)         _cmd_mark "$@" ;;
  trace)        _cmd_trace "$@" ;;
  reset)        _cmd_reset "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
