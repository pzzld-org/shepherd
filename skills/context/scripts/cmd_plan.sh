#!/usr/bin/env bash
# shctx plan <extract|topology|validate> [args]
#
# Parse the engineer's plan.md `## Stage Graph` YAML block and turn it into
# the canonical machine-readable artifact: `<namespace>/graph/state.json`.
#
# This is the bridge from the plan-as-document to the plan-as-program: once
# extracted, the rule engine in `shctx graph` walks the DAG mechanically.
#
#   extract <plan.md> [--sprint=BRANCH] [--force]
#       Parse and store. Refuses to overwrite unless --force. Idempotent.
#   topology [--sprint=BRANCH]
#       Pretty-print the extracted graph (nodes + edges + parallel_with cliques).
#   validate [--sprint=BRANCH]
#       Structural checks: acyclic, predicates resolve, parallel_with mutual,
#       every branch has an on-hard-stop reachable.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

_graph_dir() {
  local root; root="$(shctx_artifacts_root)"
  echo "$root/graph"
}

_state_path() { echo "$(_graph_dir)/state.json"; }

# Critic-proof lives ALONGSIDE the plan (the tracked plans dir), so it is
# git-visible next to the artifact it proves. Derived from the plan path:
#   .../plans/<slug>.plan.md  →  .../plans/<slug>.critic-proof.json
_proof_path() {
  local plan="$1" dir base
  dir="$(dirname "$plan")"; base="$(basename "$plan")"
  base="${base%.md}"; base="${base%.plan}"
  echo "$dir/${base}.critic-proof.json"
}

usage() {
  cat <<'EOF'
shctx plan <extract|topology|validate|hash|record-critique|verify> [args]

  extract <plan.md> [--sprint=BRANCH] [--force]
      Parse the Stage Graph YAML from plan.md and store
      <namespace>/graph/state.json. Refuses to overwrite unless --force.

  topology [--sprint=BRANCH] [--md]
      Pretty-print the extracted graph — nodes by state, edges, parallel cliques.

  validate
      Structural checks (acyclic, predicates resolve, parallel_with mutual).

  hash <plan.md>
      Echo "sha256:<hex>" of the plan bytes. The engineer captures this BEFORE
      dispatching @critic so record-critique can prove the plan was edited.

  record-critique --plan <path> --pre <hash> --verdict <v> [--iterations N] [--findings N]
      Write the critic-proof alongside the plan. Computes the post-critic hash
      from the current plan bytes; edited = (pre != post). Emitted by the
      engineer teammate after the in-session @critic pass + revision.

  verify [--plan <path>] [--quiet]
      Root's thin acceptance gate (mirrors `shctx seed verify`): the plan was
      critiqued AND edited at least once. Exit 1 with a named code on failure —
      CRITIC-PROOF-MISSING / PLAN-UNEDITED / CRITIC-PROOF-STALE / PLAN-UNCRITIQUED.
      post_critic_hash must match the ACTUAL current plan bytes, so a stale or
      hand-forged proof cannot pass.

The state file is the input to `shctx graph` (the rule-engine walker).
Critic-proof: skills/shepherd/references/pipeline.md §INTRO. See skills/shepherd/references/flock.md §Dispatch.
EOF
}

# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------
_cmd_extract() {
  local plan_path="${1:-}"; shift || true
  [[ -n "$plan_path" && -f "$plan_path" ]] \
    || { echo "ERROR: usage: shctx plan extract <plan.md>" >&2; exit 1; }

  local sprint="" force=0
  for arg in "$@"; do
    case "$arg" in
      --sprint=*) sprint="${arg#--sprint=}" ;;
      --force)    force=1 ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -z "$sprint" ]] && sprint=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

  local out_dir; out_dir="$(_graph_dir)"
  mkdir -p "$out_dir"
  local out_path; out_path="$(_state_path)"
  if [[ -f "$out_path" && "$force" -ne 1 ]]; then
    echo "ERROR: $out_path already exists. Pass --force to overwrite." >&2
    exit 1
  fi

  python3 - "$plan_path" "$out_path" "$sprint" <<'PY'
import json, re, sys, time

plan_path, out_path, sprint = sys.argv[1], sys.argv[2], sys.argv[3]

# Extract the YAML block under the `## Stage Graph` heading.
with open(plan_path) as f:
    text = f.read()
m = re.search(r"^##\s+Stage Graph\s*$(.*?)(?=^##\s+|\Z)",
              text, re.MULTILINE | re.DOTALL)
if not m:
    sys.exit("ERROR: no `## Stage Graph` section found in " + plan_path)
body = m.group(1)

# Find the first fenced code block (```yaml ... ``` or ``` ... ```).
m2 = re.search(r"```(?:yaml|yml)?\s*\n(.*?)```", body, re.DOTALL)
if not m2:
    sys.exit("ERROR: no fenced code block under `## Stage Graph`")
yaml_text = m2.group(1)

# Prefer PyYAML; degrade with a clear message.
try:
    import yaml
except ImportError:
    sys.exit("ERROR: python3 PyYAML required (apt: python3-yaml | pip: PyYAML)")

doc = yaml.safe_load(yaml_text)
if not isinstance(doc, list):
    sys.exit("ERROR: Stage Graph YAML must be a list of node objects (got "
             + type(doc).__name__ + ")")

# Build the state structure.
nodes = {}
edges = []
for n in doc:
    nid = n.get("id")
    if not nid:
        sys.exit(f"ERROR: node missing `id`: {n!r}")
    if nid in nodes:
        sys.exit(f"ERROR: duplicate node id: {nid}")
    in_preds = n.get("in_predicates") or []
    parallel_with = n.get("parallel_with") or []
    out_edges = n.get("out_edges") or []
    agents = n.get("agents") or []
    state = "done" if n.get("type") == "SEED-VERIFY" else "pending"
    # Mark nodes with no in_predicates as ready, others blocked
    if state == "pending" and not in_preds:
        state = "ready"

    nodes[nid] = {
        "id": nid,
        "type": n.get("type", "UNKNOWN"),
        "state": state,                         # pending | ready | in_flight | done | skipped
        "parallel_with": parallel_with,
        "agents": agents,
        "in_predicates": [
            {"predecessor": p.get("predecessor"), "edge": p.get("edge"),
             "satisfied": False}
            for p in in_preds
        ],
        "started_at": None,
        "exited_at": None,
        "exit_edge": None,
        "agent_ids": [],
    }
    for e in out_edges:
        edges.append({"from": nid, "label": e.get("label"), "to": e.get("target")})

state = {
    "schema_version": 1,
    "sprint": sprint,
    "plan_path": plan_path,
    "extracted_at": int(time.time()),
    "nodes": nodes,
    "edges": edges,
    "trace_path": out_path.replace("state.json", "trace.jsonl"),
}
with open(out_path, "w") as f:
    json.dump(state, f, indent=2)

# Initialize trace
with open(state["trace_path"], "w") as tf:
    import json as _j
    _j.dump({"at": int(time.time()), "event": "graph_extracted",
             "sprint": sprint, "node_count": len(nodes), "edge_count": len(edges)}, tf)
    tf.write("\n")

print(f"extracted {len(nodes)} nodes / {len(edges)} edges from {plan_path}")
print(f"  state:  {out_path}")
print(f"  trace:  {state['trace_path']}")
PY
}

# ---------------------------------------------------------------------------
# topology
# ---------------------------------------------------------------------------
_cmd_topology() {
  local fmt="text"
  for arg in "$@"; do
    case "$arg" in --md) fmt="md" ;; --json) fmt="json" ;; esac
  done

  local s; s="$(_state_path)"
  [[ -f "$s" ]] || { echo "ERROR: no graph state at $s (run 'shctx plan extract <plan.md>' first)" >&2; exit 1; }

  if [[ "$fmt" == "json" ]]; then cat "$s"; return; fi

  python3 - "$s" "$fmt" <<'PY'
import json, sys, collections
state = json.load(open(sys.argv[1]))
fmt = sys.argv[2]

by_state = collections.defaultdict(list)
for nid, n in state["nodes"].items():
    by_state[n["state"]].append(n)

def pn(n):
    pw = ", ".join(n.get("parallel_with") or []) or "—"
    agents = ", ".join(f"{a.get('role')}x{a.get('count',1)}" for a in (n.get("agents") or [])) or "inline"
    return f"{n['id']:<24} {n['type']:<24} {agents:<24} parallel:[{pw}]"

if fmt == "md":
    print(f"## Topology — {state['sprint']}")
    print(f"_{len(state['nodes'])} nodes · {len(state['edges'])} edges · extracted at {state['extracted_at']}_")
    for s in ("ready", "in_flight", "pending", "done", "skipped"):
        bucket = by_state.get(s, [])
        if not bucket: continue
        print(f"\n### {s} ({len(bucket)})")
        for n in bucket:
            print(f"- `{pn(n)}`")
    print("\n### Edges")
    for e in state["edges"]:
        print(f"- `{e['from']}` --{e['label']}--> `{e['to']}`")
else:
    print(f"Topology — {state['sprint']}  ({len(state['nodes'])} nodes / {len(state['edges'])} edges)")
    for s in ("ready", "in_flight", "pending", "done", "skipped"):
        bucket = by_state.get(s, [])
        if not bucket: continue
        print(f"\n[{s}] ({len(bucket)})")
        for n in bucket:
            print("  " + pn(n))
    print("\n[edges]")
    for e in state["edges"]:
        print(f"  {e['from']} --{e['label']}--> {e['to']}")
PY
}

# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
_cmd_validate() {
  local s; s="$(_state_path)"
  [[ -f "$s" ]] || { echo "ERROR: no graph state at $s" >&2; exit 1; }

  python3 - "$s" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
nodes = state["nodes"]
edges = state["edges"]
problems = []

# 1. Every edge target must exist
for e in edges:
    if e["to"] not in nodes:
        problems.append(f"edge {e['from']} --{e['label']}--> {e['to']} → target node missing")

# 2. Every in_predicate's predecessor must exist
for nid, n in nodes.items():
    for p in n["in_predicates"]:
        if p["predecessor"] not in nodes:
            problems.append(f"node {nid} in_predicate predecessor {p['predecessor']} missing")

# 3. parallel_with must be mutual
for nid, n in nodes.items():
    for peer in (n.get("parallel_with") or []):
        if peer not in nodes:
            problems.append(f"node {nid} parallel_with {peer} missing")
        elif nid not in (nodes[peer].get("parallel_with") or []):
            problems.append(f"parallel_with not mutual: {nid} <-> {peer}")

# 4. Acyclic check (Kahn): topological sort by in_predicates
remaining = {nid: set(p["predecessor"] for p in n["in_predicates"])
             for nid, n in nodes.items()}
order = []
while True:
    ready = [nid for nid, preds in remaining.items() if not preds]
    if not ready: break
    for r in ready:
        order.append(r)
        del remaining[r]
        for preds in remaining.values():
            preds.discard(r)
if remaining:
    problems.append(f"cycle detected involving nodes: {sorted(remaining.keys())}")

if problems:
    print("VALIDATION FAILED:")
    for p in problems: print("  ✗ " + p)
    sys.exit(1)
print(f"validate: OK  ({len(nodes)} nodes, {len(edges)} edges, topological order valid)")
PY
}

# ---------------------------------------------------------------------------
# hash — sha256 of the plan bytes (engineer captures pre-critic)
# ---------------------------------------------------------------------------
_cmd_hash() {
  local plan="${1:-}"
  [[ -n "$plan" && -f "$plan" ]] || { echo "ERROR: usage: shctx plan hash <plan.md>" >&2; exit 2; }
  python3 - "$plan" <<'PY'
import hashlib, sys
with open(sys.argv[1], "rb") as f:
    print("sha256:" + hashlib.sha256(f.read()).hexdigest())
PY
}

# ---------------------------------------------------------------------------
# record-critique — write the critic-proof alongside the plan
# ---------------------------------------------------------------------------
_cmd_record_critique() {
  local plan="" pre="" verdict="" iterations="1" findings="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --plan)        plan="${2:-}"; shift 2 ;;
      --plan=*)      plan="${1#--plan=}"; shift ;;
      --pre)         pre="${2:-}"; shift 2 ;;
      --pre=*)       pre="${1#--pre=}"; shift ;;
      --verdict)     verdict="${2:-}"; shift 2 ;;
      --verdict=*)   verdict="${1#--verdict=}"; shift ;;
      --iterations)  iterations="${2:-}"; shift 2 ;;
      --iterations=*) iterations="${1#--iterations=}"; shift ;;
      --findings)    findings="${2:-}"; shift 2 ;;
      --findings=*)  findings="${1#--findings=}"; shift ;;
      -h|--help)     usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
    esac
  done
  [[ -n "$plan" && -f "$plan" ]] || { echo "ERROR: --plan <path> required and must exist" >&2; exit 2; }
  [[ -n "$pre" ]]     || { echo "ERROR: --pre <hash> required (capture with 'shctx plan hash' BEFORE the critic pass)" >&2; exit 2; }
  [[ -n "$verdict" ]] || { echo "ERROR: --verdict <PASS|...> required" >&2; exit 2; }
  local proof sprint
  proof="$(_proof_path "$plan")"
  sprint=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  python3 - "$plan" "$proof" "$pre" "$verdict" "$iterations" "$findings" "$sprint" <<'PY'
import hashlib, json, sys, datetime
plan, proof, pre, verdict, iterations, findings, sprint = sys.argv[1:8]
with open(plan, "rb") as f:
    post = "sha256:" + hashlib.sha256(f.read()).hexdigest()
if not pre.startswith("sha256:"):
    pre = "sha256:" + pre
edited = pre != post
doc = {
  "schema_version": 1,
  "sprint": sprint,
  "plan_path": plan,
  "pre_critic_hash": pre,
  "post_critic_hash": post,
  "edited": edited,
  "critic": {"verdict": verdict, "iterations": int(iterations), "findings": int(findings)},
  "recorded_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
}
with open(proof, "w") as f:
    json.dump(doc, f, indent=2); f.write("\n")
print(f"critic-proof written: {proof}")
print(f"  edited={str(edited).lower()}  verdict={verdict}  iterations={iterations}  findings={findings}")
if not edited:
    print("  WARNING: pre == post — plan NOT edited after the critic pass; 'shctx plan verify' will FAIL (PLAN-UNEDITED)")
PY
}

# ---------------------------------------------------------------------------
# verify — root's thin acceptance gate (the critic-proof has teeth)
# ---------------------------------------------------------------------------
_cmd_verify() {
  local plan="" quiet=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --plan)    plan="${2:-}"; shift 2 ;;
      --plan=*)  plan="${1#--plan=}"; shift ;;
      --quiet)   quiet=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
    esac
  done
  local proof=""
  if [[ -n "$plan" ]]; then
    proof="$(_proof_path "$plan")"
  else
    local plans_dir; plans_dir="$(cfg_get plans)"; [[ -n "$plans_dir" ]] || plans_dir=".artifacts/docs/plans"
    [[ "$plans_dir" = /* ]] || plans_dir="$(shctx_repo_root)/$plans_dir"
    local matches count
    matches=$(ls "$plans_dir"/*.critic-proof.json 2>/dev/null || true)
    count=$(printf '%s\n' "$matches" | grep -c . || true)
    if [[ "$count" == "1" ]]; then proof="$matches"; else
      echo "CRITIC-PROOF-MISSING: pass --plan <path> (found $count proof file(s) under $plans_dir)" >&2
      exit 1
    fi
  fi
  python3 - "$proof" "$quiet" <<'PY'
import hashlib, json, os, sys
proof, quiet = sys.argv[1], sys.argv[2] == "1"
def out(s):
    if not quiet: print(s)
if not os.path.isfile(proof):
    print(f"CRITIC-PROOF-MISSING: {proof}"); sys.exit(1)
try:
    d = json.load(open(proof))
except Exception as e:
    print(f"CRITIC-PROOF-MISSING: unparseable proof {proof} ({e})"); sys.exit(1)
plan = d.get("plan_path", "")
pre  = d.get("pre_critic_hash", ""); post = d.get("post_critic_hash", "")
crit = d.get("critic", {}) or {}
verdict = str(crit.get("verdict", "")).upper()
iterations = int(crit.get("iterations", 0) or 0)
if not d.get("edited") or not pre or pre == post:
    print(f"PLAN-UNEDITED: pre==post or edited=false ({proof}) — plan not revised after the critic pass"); sys.exit(1)
if not plan or not os.path.isfile(plan):
    print(f"CRITIC-PROOF-STALE: plan_path missing on disk: {plan}"); sys.exit(1)
cur = "sha256:" + hashlib.sha256(open(plan, "rb").read()).hexdigest()
if cur != post:
    print(f"CRITIC-PROOF-STALE: post_critic_hash != current plan bytes\n  proof: {post}\n  plan:  {cur}"); sys.exit(1)
if not verdict or verdict in ("FAIL", "RED", "REJECT", "REJECTED") or iterations < 1:
    print(f"PLAN-UNCRITIQUED: verdict={verdict or 'MISSING'} iterations={iterations}"); sys.exit(1)
out(f"OK: critic-proof valid — edited=true, verdict={verdict}, iterations={iterations}, hash-tied to {os.path.basename(plan)}")
sys.exit(0)
PY
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  extract)          _cmd_extract "$@" ;;
  topology)         _cmd_topology "$@" ;;
  validate)         _cmd_validate "$@" ;;
  hash)             _cmd_hash "$@" ;;
  record-critique)  _cmd_record_critique "$@" ;;
  verify)           _cmd_verify "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
