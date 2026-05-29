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

  compile [--segment=<node-id>] [--out=<dir>] [--verify] [--list]
          [--max-concurrent=16] [--json]
      (v6.0.1, GH #77) Emit a gate-free agent-fanout segment of the Stage
      Graph as a Claude Code Dynamic Workflow script — the PRIMARY execution
      path for fanout segments. Default segment contains CLOSE-SWARM. --verify
      runs the §IV faithfulness diff (soundness / completeness / determinism);
      --list enumerates compilable segments. Seam nodes (operator gates,
      git/shell, conductor-inline) never enter the script — they run at the
      conductor (doctrine workflow-compile-down.md §III / §V / §VI).

See doctrines/dispatch-cascade.md and doctrines/workflow-compile-down.md.
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
# compile — emit a gate-free agent-fanout segment as a Dynamic Workflow script
# (v6.0.1, GH #77; doctrine workflow-compile-down.md §III/§IV/§V/§VI)
#
# Reuses the SAME state.json that `shctx plan extract` materializes — this is
# the second projection of the one source graph (doctrine §II, anti-pattern 6);
# it does NOT parse plan.md or build a second graph reader.
# ---------------------------------------------------------------------------
_cmd_compile() {
  _require_state
  local segment="" out_dir="" do_verify=0 max_conc=16 fmt="text" list=0
  for arg in "$@"; do
    case "$arg" in
      --segment=*)        segment="${arg#--segment=}" ;;
      --out=*)            out_dir="${arg#--out=}" ;;
      --verify)           do_verify=1 ;;
      --list)             list=1 ;;
      --max-concurrent=*) max_conc="${arg#--max-concurrent=}" ;;
      --json)             fmt="json" ;;
      -h|--help)          usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -z "$out_dir" ]] && out_dir="$(shctx_artifacts_root)/graph/compiled"
  mkdir -p "$out_dir"

  python3 - "$(_state_path)" "$out_dir" "$segment" "$do_verify" "$max_conc" "$fmt" "$list" "$(_trace_path)" <<'PY'
import json, sys, os, re, time, hashlib, collections

state_path, out_dir, seg_arg, do_verify_s, max_conc_s, fmt, list_s, trace_path = sys.argv[1:9]
do_verify     = do_verify_s == "1"
list_segments = list_s == "1"
MAX_CONCURRENT = int(max_conc_s)
HARD_TOTAL_CAP = 1000          # doctrine §III: ≤1000 total per run

state  = json.load(open(state_path))
nodes  = state["nodes"]
edges  = state["edges"]
sprint = state.get("sprint", "unknown")

# ---- node classification (doctrine §V φ map) -------------------------------
# Seam nodes are NOT compiled — operator gates + conductor-inline FS/git.
SEAM_EXACT = {
    "SEED-VERIFY", "CHAIN-REPAIR", "PLAN-GATE", "DEDUP-GATE", "LANE-CLOSE",
    "CANONICAL-TYPES-REFRESH", "CLOSE-FINALIZE", "RELEASE", "RESUME-LANE",
    "HARD-STOP", "MESH", "GATES-DISCOVERY",
}
def ntype(n): return (n.get("type") or "UNKNOWN").upper()

def is_compilable(n):
    """A node is an agent-fanout (compilable) node iff it spawns agents and is
    not a seam. Seam = gate / inline / operator-approval (doctrine §III/§V)."""
    t = ntype(n)
    if not n.get("agents"):      return False     # conductor-inline → seam
    if t in SEAM_EXACT:          return False
    if t.startswith("PAUSE"):    return False      # pause → segment boundary
    if t.endswith("-GATE"):      return False      # WAVE-1-GATE etc. → seam
    # φ-map compilable families:
    if t == "CLOSE-SWARM":       return True
    if t == "INTRO-COMBO-WAVE":  return True
    if t == "DISCOVERY":         return True
    if "IMPL"  in t:             return True        # WAVE-1-IMPL ...
    if "AUDIT" in t:             return True        # WAVE-1-AUDIT, CLOSE-AUDIT
    if t.startswith("HOTFIX"):   return True        # HOTFIX-DYNAMIC / HOTFIX-CLOSE
    if t.startswith("WORKER"):   return True        # WORKER-IO
    return False

# adjacency over sequential edges
succ = {nid: [] for nid in nodes}
pred = {nid: [] for nid in nodes}
for e in edges:
    if e["from"] in succ and e["to"] in nodes:
        succ[e["from"]].append((e["to"], e.get("label")))
        pred[e["to"]].append((e["from"], e.get("label")))

# ---- segment detection (doctrine §III: maximal compilable subgraph) --------
# Two compilable nodes share a segment when connected by parallel_with OR by a
# sequential edge (either direction) without crossing a seam.
def segment_of(seed_id):
    seg, stack = {seed_id}, [seed_id]
    while stack:
        cur = stack.pop()
        peers = list(nodes[cur].get("parallel_with") or [])
        peers += [t for (t, _l) in succ[cur]]
        peers += [f for (f, _l) in pred[cur]]
        for p in peers:
            if p in seg or p not in nodes:    continue
            if not is_compilable(nodes[p]):   continue   # stop at seam boundary
            seg.add(p); stack.append(p)
    return seg

compilable_ids = sorted(nid for nid, n in nodes.items() if is_compilable(n))
segments, assigned = [], set()
for nid in compilable_ids:
    if nid in assigned:  continue
    seg = segment_of(nid)
    assigned |= seg
    segments.append(sorted(seg))

def seg_label(seg):
    segset = set(seg)
    for nid in seg:                                   # CLOSE-SWARM is the canonical close label
        if ntype(nodes[nid]) == "CLOSE-SWARM": return nid
    # else label by the segment's entry node (no predecessor inside the segment),
    # preferring an IMPL-typed entry (the wave's head).
    entries = [nid for nid in seg
               if not any(p in segset for (p, _l) in pred[nid])]
    for nid in sorted(entries):
        if "IMPL" in ntype(nodes[nid]): return nid
    return sorted(entries)[0] if entries else seg[0]

if list_segments:
    if fmt == "json":
        print(json.dumps([{"label": seg_label(s), "nodes": s,
                           "types": sorted({ntype(nodes[i]) for i in s})} for s in segments], indent=2))
    else:
        if not segments:
            print("No gate-free agent-fanout segments in the graph (all nodes are seams).")
        for s in segments:
            print(f"segment {seg_label(s)}: {', '.join(s)}  [{', '.join(sorted({ntype(nodes[i]) for i in s}))}]")
    sys.exit(0)

if not segments:
    sys.exit("ERROR: no gate-free agent-fanout segment in the graph (nothing to compile).")

# ---- choose the target segment ---------------------------------------------
target = None
if seg_arg:
    for s in segments:
        if seg_arg in s:
            target = s; break
    if target is None:
        sys.exit(f"ERROR: no compilable segment contains node '{seg_arg}'. "
                 f"Run `shctx graph compile --list`.")
else:
    for s in segments:                                # default: CLOSE-SWARM first (§IX)
        if any(ntype(nodes[i]) == "CLOSE-SWARM" for i in s):
            target = s; break
    if target is None:
        target = segments[0]
label = seg_label(target)

# ---- order the segment into sequential batches of parallel cliques ---------
pool = set(target)
def clique_of(nid):
    seen, stack = {nid}, [nid]
    while stack:
        c = stack.pop()
        for peer in (nodes[c].get("parallel_with") or []):
            if peer in pool and peer not in seen:
                seen.add(peer); stack.append(peer)
    return sorted(seen)

cliques, seen_nodes = [], set()
for nid in sorted(target):
    if nid in seen_nodes: continue
    cl = clique_of(nid)
    seen_nodes |= set(cl)
    cliques.append(cl)

clique_idx = {nid: i for i, cl in enumerate(cliques) for nid in cl}
cl_succ = collections.defaultdict(set)
cl_indeg = [0] * len(cliques)
seen_pairs = set()
seg_orderings = []
for e in edges:
    a, b = e["from"], e["to"]
    if a in clique_idx and b in clique_idx:
        seg_orderings.append({"from": a, "to": b, "edge": e.get("label")})
        ia, ib = clique_idx[a], clique_idx[b]
        if ia != ib and (ia, ib) not in seen_pairs:
            cl_succ[ia].add(ib); cl_indeg[ib] += 1; seen_pairs.add((ia, ib))
# Kahn topological order of cliques (deterministic: sorted frontier)
indeg = cl_indeg[:]
frontier = sorted(i for i in range(len(cliques)) if indeg[i] == 0)
order = []
while frontier:
    i = frontier.pop(0); order.append(i)
    for j in sorted(cl_succ[i]):
        indeg[j] -= 1
        if indeg[j] == 0:
            frontier.append(j); frontier.sort()
if len(order) != len(cliques):                        # cycle (should not happen — DAG)
    order = list(range(len(cliques)))

# ---- expand agents → spawns (deterministic) --------------------------------
READONLY_ROLES = {"auditor", "discovery", "critic"}
def spawns_for_node(nid):
    out = []
    for a in (nodes[nid].get("agents") or []):
        role  = a.get("role", "coder")
        count = int(a.get("count", 1) or 1)
        concerns = a.get("concerns") or a.get("concern")
        briefs   = a.get("briefs")   or a.get("brief")
        for k in range(count):
            tag = None
            if   isinstance(concerns, list) and k < len(concerns): tag = concerns[k]
            elif isinstance(concerns, str):                        tag = concerns
            elif isinstance(briefs, list) and k < len(briefs):     tag = briefs[k]
            elif isinstance(briefs, str):                          tag = briefs
            out.append({"node": nid, "role": role, "index": k, "tag": tag,
                        "readonly": role in READONLY_ROLES})
    return out

total_agents = sum(len(spawns_for_node(nid)) for nid in target)
if total_agents > HARD_TOTAL_CAP:
    sys.exit(f"ERROR: segment '{label}' spawns {total_agents} agents (> {HARD_TOTAL_CAP} cap, "
             f"doctrine §III). This is a plan-scale error — split the plan.")

# ---- emit the workflow script ----------------------------------------------
def js(s): return json.dumps("" if s is None else s)
def _1l(s): return str(s).replace("\n", " ").replace("\r", " ").strip()  # comment-safe

L = []
def A(s): L.append(s)
A("// ───── shepherd compiled workflow ─────")
A(f"// segment      : {_1l(label)}")
A( "// generator    : `shctx graph compile` — compile(G_seg). DO NOT hand-edit.")
A(f"// source plan  : {_1l(state.get('plan_path','?'))}")
A(f"// sprint       : {_1l(sprint)}")
A(f"// nodes        : {', '.join(target)}")
A(f"// agents       : {total_agents}  (≤16 concurrent, ≤1000 total — doctrine §III)")
A(f"// faithfulness : `shctx graph compile --segment={label} --verify`  (§IV)")
A( "//")
A( "// SEAMS (doctrine §VI): git/shell, operator gates, and SQLite+git canonical")
A( "// writes run at the CONDUCTOR, never here. This workflow only coordinates")
A( "// agent fanout out-of-context; results return to the conductor in script")
A( "// variables. On runtime failure the conductor degrades to `shctx graph next`")
A( "// direct dispatch for this segment (doctrine §VI; no parallel engine).")
A( "//")
A( "// `agent` spawns a subagent; `briefs` is the conductor-resolved brief map")
A( "// keyed \"<node>:<tag>\" (brief CONTENT lives with the conductor, not in")
A( "// compile(G) — stage-graph.md: the graph references briefs by id).")
A("")
A("export default async function ({ agent, briefs }) {")
A(f"  const MAX_CONCURRENT = {MAX_CONCURRENT};  // doctrine §III concurrency cap")
A("")
A("  // Bounded fan-out: spawn in chunks of MAX_CONCURRENT (unbounded Promise.all")
A("  // is the §III anti-pattern). parallel_with peers share one batch.")
A("  async function fanout(spawns) {")
A("    const out = [];")
A("    for (let i = 0; i < spawns.length; i += MAX_CONCURRENT) {")
A("      const chunk = spawns.slice(i, i + MAX_CONCURRENT);")
A("      out.push(...(await Promise.all(chunk.map((s) => agent(s)))));")
A("    }")
A("    return out;")
A("  }")
A("")
A("  const results = {};")
for oi in order:
    cl = cliques[oi]
    spawns = []
    for nid in cl:
        spawns.extend(spawns_for_node(nid))
    bvar  = f"batch_{oi}"
    types = ", ".join(sorted({ntype(nodes[i]) for i in cl}))
    A(f"  // batch {oi}: {', '.join(cl)}  [{types}]")
    A(f"  const {bvar} = await fanout([")
    for s in spawns:
        key  = f"{s['node']}:{s['tag'] if s['tag'] is not None else s['index']}"
        desc = f"@{s['role']}" + (f": {s['tag']}" if s['tag'] else f" {s['node']}#{s['index']}")
        ro   = "  /* read-only: allowlist-enforced, no edit tools (§VII, #74) */" if s["readonly"] else ""
        A(f"    {{ subagent_type: \"shepherd:{s['role']}\", description: {js(desc)}, prompt: briefs[{js(key)}] }},{ro}")
    A("  ]);")
    for nid in cl:
        A(f"  results[{js(nid)}] = {bvar};")
    A("")
A("  // Out-of-context: results live in script vars, returned to the conductor,")
A("  // which writes canonical state (SQLite + git) and evaluates the next seam.")
A("  return results;")
A("}")
script = "\n".join(L) + "\n"
script_sha = hashlib.sha256(script.encode()).hexdigest()

manifest = {
    "segment": label, "sprint": sprint, "nodes": target,
    "batches": [{"index": oi, "nodes": cliques[oi],
                 "spawns": [ {"node": s["node"], "role": s["role"], "tag": s["tag"],
                              "readonly": s["readonly"]}
                             for nid in cliques[oi] for s in spawns_for_node(nid) ]}
                for oi in order],
    "orderings": seg_orderings,
    "total_agents": total_agents,
    "max_concurrent": MAX_CONCURRENT,
    "compiled_at": int(time.time()),
    "script_sha256": script_sha,
}

script_path   = os.path.join(out_dir, f"{label}.workflow.js")
manifest_path = os.path.join(out_dir, f"{label}.manifest.json")
# Capture the prior on-disk script BEFORE overwriting — this IS the "runtime's
# raw script" the §IV faithfulness diff compares a fresh compile(G_seg) against.
prior_script = None
if os.path.exists(script_path):
    with open(script_path) as f:
        prior_script = f.read()
with open(script_path, "w")   as f: f.write(script)
with open(manifest_path, "w") as f: json.dump(manifest, f, indent=2)

# trace
try:
    with open(trace_path, "a") as t:
        t.write(json.dumps({"at": int(time.time()), "event": "graph_compiled",
                            "segment": label, "agents": total_agents,
                            "sha256": script_sha[:12]}) + "\n")
except Exception:
    pass

# ---- §IV faithfulness diff -------------------------------------------------
def run_verify():
    problems = {"soundness": [], "completeness": [], "determinism": []}

    # Independently re-derive the expected spawn multiset + node set from the
    # SOURCE graph (state.json), then check the emitted script against it.
    expected_nodes = set(target)
    expected_spawns = collections.Counter()
    for nid in target:
        for s in spawns_for_node(nid):
            expected_spawns[(s["node"], s["role"])] += 1

    # Parse the emitted script back: every `subagent_type: "shepherd:<role>"`
    # is a spawn; every results["<id>"] = ... is a realized node.
    parsed_roles = collections.Counter(re.findall(r'subagent_type:\s*"shepherd:([a-z]+)"', script))
    parsed_nodes = set(re.findall(r'results\[(?:"([^"]+)"|\'([^\']+)\')\]', script))
    parsed_nodes = {a or b for (a, b) in re.findall(r'results\[(?:"([^"]+)"|\'([^\']+)\')\]', script)}

    # SOUNDNESS — no spawned agent absent from V_seg; no ordering absent from E_seg.
    spawned_total = collections.Counter()
    for (n_, role), c in expected_spawns.items():
        spawned_total[role] += c
    for role, c in parsed_roles.items():
        if spawned_total.get(role, 0) != c:
            problems["soundness"].append(
                f"role '{role}': script spawns {c}, source graph specifies {spawned_total.get(role,0)}")
    for nid in parsed_nodes:
        if nid not in expected_nodes:
            problems["soundness"].append(f"script references node '{nid}' not in segment V_seg")
    # orderings emitted (batch sequence) must be a subset of E_seg
    seg_edge_pairs = {(o["from"], o["to"]) for o in seg_orderings}
    for ia, ib in seen_pairs:
        # every inter-clique ordering we emit must be backed by a real edge
        backed = any(clique_idx.get(o["from"]) == ia and clique_idx.get(o["to"]) == ib
                     for o in seg_orderings)
        if not backed:
            problems["soundness"].append(f"emitted ordering batch{ia}->batch{ib} has no backing edge in E_seg")

    # COMPLETENESS — every must-fire node present; every expected spawn present.
    for nid in expected_nodes:
        if nid not in parsed_nodes:
            problems["completeness"].append(f"segment node '{nid}' missing from compiled script")
    for role, c in spawned_total.items():
        if parsed_roles.get(role, 0) != c:
            problems["completeness"].append(
                f"role '{role}': expected {c} spawns, script has {parsed_roles.get(role,0)}")

    # DETERMINISM / faithfulness diff — the script the runtime was about to run
    # (the prior on-disk artifact) must equal a fresh, deterministic compile(G_seg).
    # A mismatch is a compiler bug or a hand-edit (doctrine §IV: "a mismatch is a
    # compiler bug, not a plan defect"). compile() is a pure function of state.json.
    if prior_script is not None and prior_script != script:
        problems["determinism"].append(
            "prior on-disk script != fresh compile(G_seg) — hand-edited or stale "
            "(recompiled to the canonical form now)")
    # no nondeterministic constructs (Date/Math.random/Promise.race|any) in the script
    for bad in ("Math.random", "Date.now", "Promise.race", "Promise.any"):
        if bad in script:
            problems["determinism"].append(f"nondeterministic construct '{bad}' in compiled script")

    return problems

verify_result = run_verify() if do_verify else None
verify_ok = (verify_result is None) or all(len(v) == 0 for v in verify_result.values())

# ---- report ----------------------------------------------------------------
if fmt == "json":
    out = {"segment": label, "script": script_path, "manifest": manifest_path,
           "nodes": target, "total_agents": total_agents,
           "max_concurrent": MAX_CONCURRENT, "script_sha256": script_sha}
    if verify_result is not None:
        out["faithfulness"] = {k: ("PASS" if not v else v) for k, v in verify_result.items()}
        out["faithfulness_ok"] = verify_ok
    print(json.dumps(out, indent=2))
else:
    print(f"compiled segment '{label}'  ({total_agents} agents, {len(cliques)} batch(es), ≤16 concurrent)")
    print(f"  script   : {script_path}")
    print(f"  manifest : {manifest_path}")
    print(f"  sha256   : {script_sha[:16]}")
    if verify_result is not None:
        print("  faithfulness diff (§IV):")
        for dim in ("soundness", "completeness", "determinism"):
            issues = verify_result[dim]
            if not issues:
                print(f"    ✓ {dim}")
            else:
                print(f"    ✗ {dim}")
                for it in issues:
                    print(f"        - {it}")

if do_verify and not verify_ok:
    sys.exit(2)
PY
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
  compile)      _cmd_compile "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
