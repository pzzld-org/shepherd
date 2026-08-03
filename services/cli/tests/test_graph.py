"""Tests for `shepherd graph` — native port of `cmd_graph.sh` (no DB, pure filesystem).

Drives the module's Typer app DIRECTLY via a `${PY} -c` subprocess snippet
(`shepherd_cli.commands.graph.app`) — the sub-app is not yet registered
in `shepherd_cli.app`, so module-level invocation is what works both
BEFORE and AFTER the integrator flips registration (see test_plan.py's
identical note).

Migrated load-bearing assertions:

- `skills/context/tests/test_graph_next.sh` — the GH #225 regression
  (bare-string agents shorthand through `next`/`next --json`, the
  hand-corrupted-state degradation), PLUS the mandated deeper regression
  walk: an 11-node graph with parallel_with cliques and AND-join
  in_predicates driven through full next/mark cycles to completion with
  zero AttributeErrors/Tracebacks.
- `skills/context/tests/test_graph_compile.sh` — segment detection with
  seams excluded, the §V emission (bounded fanout, read-only annotation,
  briefs map), #180 model pins (agent(prompt, opts) shape, per-spawn
  agentType+model, no legacy `agent(s)`), seam-leak checks, batch
  ordering realizing cross-lane dependencies with no pause/heartbeat
  machinery, and the negative §IV determinism case (hand-edit -> exit 2,
  recompile self-heals).
- from `test_compile_telemetry.sh`'s contract surface that lives in THIS
  command (the telemetry aggregation itself is `shctx adapt report`,
  out of scope here): deterministic script bytes with `compiled_at` ONLY
  in the manifest, the manifest's `script_sha256` matching the actual
  script bytes, and the `graph_compiled` trace event.
- the Dynamic Workflow meta contract (documented deviation 2 in
  `graph.py`): `export const meta = { name, description, phases }` as a
  pure literal, byte-stable across recompiles.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

CMD_GRAPH_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_graph.sh"

_GRAPH_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.graph import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd graph')\n"
)

_PLAN_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.plan import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd plan')\n"
)

#: The compile fixture plan, verbatim from test_graph_compile.sh.
COMPILE_PLAN = """## Stage Graph

```yaml
- id: MESH
  type: MESH
  agents: [{role: engineer, count: 1}]
  out_edges: [{label: on-pass, target: PLAN-GATE}]
- id: PLAN-GATE
  type: PLAN-GATE
  in_predicates: [{predecessor: MESH, edge: on-pass}]
  out_edges: [{label: approved, target: WAVE-1-IMPL}]
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  parallel_with: [WORKER-IO]
  agents: [{role: coder, count: 3}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WORKER-IO
  type: WORKER-IO
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  parallel_with: [WAVE-1-IMPL]
  agents: [{role: worker, count: 1}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WAVE-1-AUDIT
  type: WAVE-1-AUDIT
  in_predicates: [{predecessor: WAVE-1-IMPL, edge: on-pass}]
  agents: [{role: auditor, count: 2, concerns: [code-quality, data-flow]}]
  out_edges: [{label: on-pass, target: WAVE-1-GATE}]
- id: WAVE-1-GATE
  type: WAVE-1-GATE
  in_predicates: [{predecessor: WAVE-1-AUDIT, edge: on-pass}]
  out_edges: [{label: on-pass, target: CLOSE-SWARM}]
- id: CLOSE-SWARM
  type: CLOSE-SWARM
  in_predicates: [{predecessor: WAVE-1-GATE, edge: on-pass}]
  agents: [{role: auditor, count: 3, concerns: [code-quality, data-flow, completeness]}]
  out_edges: [{label: on-no-finding, target: CLOSE-FINALIZE}]
- id: CLOSE-FINALIZE
  type: CLOSE-FINALIZE
  in_predicates: [{predecessor: CLOSE-SWARM, edge: on-no-finding}]
```
"""

#: The #225-mandated regression-walk fixture: 11 nodes, two parallel_with
#: cliques (a 3-clique and a 2-clique), AND-join in_predicates (3-way into
#: WAVE-1-AUDIT, 2-way into CLOSE-SWARM), a mix of bare-string and
#: mapping-form agents, a SEED-VERIFY node that starts done, and two
#: conductor-inline seam nodes.
WALK_PLAN = """## Stage Graph

```yaml
- id: SEED-VERIFY
  type: SEED-VERIFY
- id: MESH
  type: MESH
  agents: [engineer]
  out_edges: [{label: on-pass, target: PLAN-GATE}]
- id: PLAN-GATE
  type: PLAN-GATE
  in_predicates: [{predecessor: MESH, edge: on-pass}]
  out_edges:
    - {label: approved, target: W1A}
    - {label: approved, target: W1B}
    - {label: approved, target: W1C}
- id: W1A
  type: WAVE-1-IMPL
  parallel_with: [W1B, W1C]
  agents: [coder]
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: W1B
  type: WAVE-1-IMPL
  parallel_with: [W1A, W1C]
  agents: [{role: coder, count: 2}]
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: W1C
  type: WAVE-1-IMPL
  parallel_with: [W1A, W1B]
  agents: [worker]
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WAVE-1-AUDIT
  type: WAVE-1-AUDIT
  agents: [{role: auditor, count: 2, concerns: [code-quality, data-flow]}]
  in_predicates:
    - {predecessor: W1A, edge: on-pass}
    - {predecessor: W1B, edge: on-pass}
    - {predecessor: W1C, edge: on-pass}
  out_edges:
    - {label: on-pass, target: WAVE-2-IMPL}
    - {label: on-pass, target: WORKER-IO}
- id: WAVE-2-IMPL
  type: WAVE-2-IMPL
  parallel_with: [WORKER-IO]
  agents: [coder]
  in_predicates: [{predecessor: WAVE-1-AUDIT, edge: on-pass}]
  out_edges: [{label: on-pass, target: CLOSE-SWARM}]
- id: WORKER-IO
  type: WORKER-IO
  parallel_with: [WAVE-2-IMPL]
  agents: [{role: worker, count: 1}]
  in_predicates: [{predecessor: WAVE-1-AUDIT, edge: on-pass}]
  out_edges: [{label: on-pass, target: CLOSE-SWARM}]
- id: CLOSE-SWARM
  type: CLOSE-SWARM
  agents: [{role: auditor, count: 3, concerns: [code-quality, data-flow, completeness]}]
  in_predicates:
    - {predecessor: WAVE-2-IMPL, edge: on-pass}
    - {predecessor: WORKER-IO, edge: on-pass}
  out_edges: [{label: on-no-finding, target: CLOSE-FINALIZE}]
- id: CLOSE-FINALIZE
  type: CLOSE-FINALIZE
  in_predicates: [{predecessor: CLOSE-SWARM, edge: on-no-finding}]
```
"""


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh git repo with `.shepherd/` + shepherd.toml (see test_plan.py)."""
    d = tmp_path / "work"
    d.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    (d / ".shepherd").mkdir()
    (d / ".claude").mkdir()
    (d / ".claude" / "shepherd.toml").touch()
    return d


@pytest.fixture
def env() -> dict[str, str]:
    """Stripped env (+ SHCTX_QUIET, - SHEPHERD_RUN) shared by py + bash runs."""
    e = clean_env_dict()
    e.pop("SHEPHERD_RUN", None)
    e["SHCTX_QUIET"] = "1"
    return e


def run_graph(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the graph module app directly: `${PY} -c "<snippet>" <args>`."""
    return subprocess.run([PY, "-c", _GRAPH_SNIPPET, *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def run_plan(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the plan module app directly (the state writer for fixtures)."""
    return subprocess.run([PY, "-c", _PLAN_SNIPPET, *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def run_bash_graph(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_graph.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(["bash", str(CMD_GRAPH_SH), *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def extract(cwd: Path, env: dict[str, str], content: str, sprint: str = "v6.0.1-dev.0") -> None:
    (cwd / "plan.md").write_text(content)
    proc = run_plan(["extract", "plan.md", f"--sprint={sprint}"], cwd, env)
    assert proc.returncode == 0, proc.stderr


def state_file(cwd: Path) -> Path:
    return cwd / ".shepherd" / "graph" / "state.json"


def assert_clean(proc: subprocess.CompletedProcess[str]) -> None:
    """rc 0 and no Python crash artifacts anywhere (the #225 bar)."""
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "AttributeError" not in combined, combined
    assert "Traceback" not in combined, combined


def mark(cwd: Path, env: dict[str, str], nid: str, state: str, exit_edge: str | None = None) -> subprocess.CompletedProcess[str]:
    args = ["mark", nid, f"--state={state}"]
    if exit_edge:
        args.append(f"--exit={exit_edge}")
    proc = run_graph(args, cwd, env)
    assert_clean(proc)
    return proc


# --------------------------------------------------------------------------
# GH #225 — shorthand agents through next/status/topology (fixture A)
# --------------------------------------------------------------------------
def test_next_renders_shorthand_and_mapping_roles(work_dir: Path, env: dict[str, str]) -> None:
    extract(
        work_dir,
        env,
        "## Stage Graph\n\n```yaml\n"
        "- id: WAVE-1-IMPL\n  type: WAVE-1-IMPL\n  agents: [engineer]\n  parallel_with: [WORKER-IO]\n"
        "  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]\n"
        "- id: WORKER-IO\n  type: WORKER-IO\n  parallel_with: [WAVE-1-IMPL]\n  agents: [{role: coder, count: 2}]\n"
        "  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]\n"
        "- id: WAVE-1-AUDIT\n  type: WAVE-1-AUDIT\n"
        "  in_predicates: [{predecessor: WAVE-1-IMPL, edge: on-pass}]\n"
        "  agents: [{role: auditor, count: 1}]\n"
        "```\n",
        sprint="v6.3.9-dev.0",
    )
    nxt = run_graph(["next"], work_dir, env)
    assert_clean(nxt)
    assert "@engineer" in nxt.stdout
    assert "@coder ×2" in nxt.stdout

    nxt_json = run_graph(["next", "--json"], work_dir, env)
    assert_clean(nxt_json)
    assert '"role": "engineer"' in nxt_json.stdout
    assert '"count": 1' in nxt_json.stdout
    payload = json.loads(nxt_json.stdout)
    assert payload["count"] == 2
    assert sorted(n["id"] for n in payload["batch"]) == ["WAVE-1-IMPL", "WORKER-IO"]


def test_next_degrades_on_hand_corrupted_agents(work_dir: Path, env: dict[str, str]) -> None:
    """#225 fixture C reader half: no AttributeError on a role-less mapping."""
    extract(work_dir, env, "## Stage Graph\n\n```yaml\n- id: WAVE-1-IMPL\n  type: WAVE-1-IMPL\n  agents: [engineer]\n```\n")
    state = json.loads(state_file(work_dir).read_text())
    state["nodes"]["WAVE-1-IMPL"]["agents"] = [{"count": 3}]
    state_file(work_dir).write_text(json.dumps(state, indent=2))

    nxt = run_graph(["next"], work_dir, env)
    assert_clean(nxt)  # degrades (role renders as None), never crashes


# --------------------------------------------------------------------------
# GH #225 mandated regression walk: 11 nodes, cliques + AND-joins, to 100%
# --------------------------------------------------------------------------
def test_full_walk_through_cliques_and_and_joins(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN, sprint="v-walk")

    # SEED-VERIFY starts done; MESH is the sole ready node.
    status = run_graph(["status", "--json"], work_dir, env)
    assert_clean(status)
    st = json.loads(status.stdout)
    assert st["total"] == 11
    assert st["by_state"]["done"] == 1
    assert st["ready"] == ["MESH"]

    # 1. MESH (single-node batch, bare-string engineer shorthand).
    nxt = run_graph(["next"], work_dir, env)
    assert_clean(nxt)
    assert "Next batch (1 node(s)" in nxt.stdout
    assert "@engineer ×1" in nxt.stdout
    mark(work_dir, env, "MESH", "in_flight")
    out = mark(work_dir, env, "MESH", "done", "on-pass")
    assert "newly ready: PLAN-GATE" in out.stdout

    # 2. PLAN-GATE (conductor-inline seam: no agents).
    nxt = run_graph(["next"], work_dir, env)
    assert_clean(nxt)
    assert "PLAN-GATE" in nxt.stdout
    assert "conductor-inline" in nxt.stdout
    out = mark(work_dir, env, "PLAN-GATE", "done", "approved")
    assert "W1A" in out.stdout and "W1B" in out.stdout and "W1C" in out.stdout

    # 3. The 3-clique fires as ONE batch (parallel_with closure).
    nxt_json = run_graph(["next", "--json"], work_dir, env)
    assert_clean(nxt_json)
    batch = json.loads(nxt_json.stdout)
    assert sorted(n["id"] for n in batch["batch"]) == ["W1A", "W1B", "W1C"]
    assert batch["count"] == 3
    # AND-join: after 2 of 3 predecessors, WAVE-1-AUDIT must NOT be ready.
    mark(work_dir, env, "W1A", "done", "on-pass")
    mark(work_dir, env, "W1B", "done", "on-pass")
    st = json.loads(run_graph(["status", "--json"], work_dir, env).stdout)
    assert "WAVE-1-AUDIT" not in st["ready"]
    assert st["ready"] == ["W1C"]
    out = mark(work_dir, env, "W1C", "done", "on-pass")
    assert "WAVE-1-AUDIT" in out.stdout  # third leg satisfies the AND-join

    # 4. WAVE-1-AUDIT fans two downstream ready nodes on one exit edge.
    out = mark(work_dir, env, "WAVE-1-AUDIT", "done", "on-pass")
    assert "WAVE-2-IMPL" in out.stdout and "WORKER-IO" in out.stdout

    # 5. The 2-clique fires as one batch; both must land for CLOSE-SWARM.
    batch = json.loads(run_graph(["next", "--json"], work_dir, env).stdout)
    assert sorted(n["id"] for n in batch["batch"]) == ["WAVE-2-IMPL", "WORKER-IO"]
    mark(work_dir, env, "WAVE-2-IMPL", "done", "on-pass")
    st = json.loads(run_graph(["status", "--json"], work_dir, env).stdout)
    assert "CLOSE-SWARM" not in st["ready"]
    mark(work_dir, env, "WORKER-IO", "done", "on-pass")

    # 6-7. CLOSE-SWARM then CLOSE-FINALIZE, to completion.
    mark(work_dir, env, "CLOSE-SWARM", "done", "on-no-finding")
    mark(work_dir, env, "CLOSE-FINALIZE", "done", "on-pass")

    st = json.loads(run_graph(["status", "--json"], work_dir, env).stdout)
    assert st["completion_pct"] == 100
    assert st["by_state"] == {"done": 11}
    done_next = run_graph(["next"], work_dir, env)
    assert_clean(done_next)
    assert done_next.stdout.strip() == "Graph complete — no nodes remain."

    # The walk left a full audit trail.
    trace = run_graph(["trace"], work_dir, env)
    assert_clean(trace)
    assert trace.stdout.count("node_mark") == 11
    assert "graph_extracted" in trace.stdout


# --------------------------------------------------------------------------
# mark / status / trace / reset edges
# --------------------------------------------------------------------------
def test_mark_in_flight_records_agent_and_started_at(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN)
    mark_out = run_graph(["mark", "MESH", "--state=in_flight", "--agent=a1"], work_dir, env)
    assert_clean(mark_out)
    state = json.loads(state_file(work_dir).read_text())
    node = state["nodes"]["MESH"]
    assert node["state"] == "in_flight"
    assert isinstance(node["started_at"], int)
    assert node["agent_ids"] == ["a1"]
    # Dedupe (documented deviation 3: insertion-order, same membership).
    run_graph(["mark", "MESH", "--state=in_flight", "--agent=a1"], work_dir, env)
    run_graph(["mark", "MESH", "--state=in_flight", "--agent=a2"], work_dir, env)
    state = json.loads(state_file(work_dir).read_text())
    assert state["nodes"]["MESH"]["agent_ids"] == ["a1", "a2"]


def test_mark_errors(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN)
    no_nid = run_graph(["mark"], work_dir, env)
    assert no_nid.returncode == 1
    assert "ERROR: usage: shctx graph mark <node-id> --state=..." in no_nid.stderr
    bad_state = run_graph(["mark", "MESH", "--state=frobbed"], work_dir, env)
    assert bad_state.returncode == 1
    assert "ERROR: --state must be in_flight|done|skipped" in bad_state.stderr
    bad_node = run_graph(["mark", "NOPE", "--state=done"], work_dir, env)
    assert bad_node.returncode == 1
    assert "ERROR: node NOPE not in graph" in bad_node.stderr
    unknown = run_graph(["mark", "MESH", "--state=done", "--bogus"], work_dir, env)
    assert unknown.returncode == 1
    assert "ERROR: unknown arg: --bogus" in unknown.stderr


def test_status_formats(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN, sprint="v-status")
    text = run_graph(["status"], work_dir, env)
    assert_clean(text)
    assert text.stdout.startswith("Graph status — sprint: v-status")
    assert "completion: 1/11 (9%)" in text.stdout
    md = run_graph(["status", "--md"], work_dir, env)
    assert md.stdout.startswith("## Graph status — v-status")
    assert "**Ready now:** `MESH`" in md.stdout


def test_trace_tail_and_json_and_empty(work_dir: Path, env: dict[str, str]) -> None:
    no_trace = run_graph(["trace"], work_dir, env)
    assert no_trace.returncode == 0
    assert no_trace.stdout.startswith("(no trace yet at ")

    extract(work_dir, env, WALK_PLAN)
    mark(work_dir, env, "MESH", "done", "on-pass")
    tail = run_graph(["trace", "--tail=1"], work_dir, env)
    assert_clean(tail)
    lines = tail.stdout.strip().splitlines()
    assert len(lines) == 1
    assert "node_mark" in lines[0]
    raw = run_graph(["trace", "--json"], work_dir, env)
    trace_file = work_dir / ".shepherd" / "graph" / "trace.jsonl"
    assert raw.stdout == trace_file.read_text()  # bash cat parity: raw bytes


def test_reset_requires_force(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN)
    dry = run_graph(["reset"], work_dir, env)
    assert_clean(dry)
    assert dry.stdout.startswith("Will remove:")
    assert "Re-run with --force to confirm." in dry.stdout
    assert state_file(work_dir).exists()
    forced = run_graph(["reset", "--force"], work_dir, env)
    assert forced.stdout.strip() == "reset: graph state and trace removed."
    assert not state_file(work_dir).exists()
    assert not (work_dir / ".shepherd" / "graph" / "trace.jsonl").exists()


def test_missing_state_and_dispatch_edges(work_dir: Path, env: dict[str, str]) -> None:
    for sub in (["status"], ["next"], ["compile"], ["diagram"]):
        proc = run_graph(sub, work_dir, env)
        assert proc.returncode == 1
        assert "ERROR: no graph state at" in proc.stderr
    usage = run_graph([], work_dir, env)
    assert usage.returncode == 0
    assert usage.stdout.startswith("shctx graph <status|next|mark|trace|reset> [args]")
    unknown = run_graph(["bogus"], work_dir, env)
    assert unknown.returncode == 1
    assert unknown.stderr.startswith("ERROR: unknown subcommand: bogus")


# --------------------------------------------------------------------------
# compile (test_graph_compile.sh migration)
# --------------------------------------------------------------------------
def test_compile_list_excludes_seams(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    listed = run_graph(["compile", "--list"], work_dir, env)
    assert_clean(listed)
    assert "segment CLOSE-SWARM: CLOSE-SWARM" in listed.stdout
    assert "WAVE-1-IMPL, WORKER-IO" in listed.stdout
    assert not re.search(r"segment (PLAN-GATE|WAVE-1-GATE|CLOSE-FINALIZE|MESH):", listed.stdout), (
        "a seam node was emitted as a compilable segment"
    )


def test_compile_default_close_swarm_with_clean_faithfulness(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    out = run_graph(["compile", "--verify"], work_dir, env)
    assert_clean(out)
    assert "compiled segment 'CLOSE-SWARM'" in out.stdout
    for dim in ("soundness", "completeness", "determinism", "model_pin"):
        assert f"✓ {dim}" in out.stdout

    script = work_dir / ".shepherd" / "graph" / "compiled" / "CLOSE-SWARM.workflow.js"
    assert script.is_file()
    body = script.read_text()
    assert body.count('agentType: "shepherd:auditor"') == 3
    assert "read-only: allowlist-enforced" in body
    assert "MAX_CONCURRENT = 16" in body
    assert 'briefs["CLOSE-SWARM:code-quality"]' in body

    # #180 model-pin: real agent(prompt, opts) shape + explicit pins.
    assert "() => agent(briefs[" in body
    assert not re.search(r"=>\s*agent\(\s*s\s*\)|agent\(s\)", body), "legacy opts-less agent(s) shape (#180)"
    assert body.count('model: "sonnet"') == 3  # 3 auditors, all sonnet
    n_agenttype = len(re.findall(r'agentType: "shepherd:', body))
    n_modelpin = len(re.findall(r'model: "', body))
    assert n_agenttype == n_modelpin == 3, "an unpinned spawn (#180)"

    # Seam content must never leak into the EXECUTABLE body.
    assert not re.search(
        r'agentType: "shepherd:engineer"|results\["(CLOSE-FINALIZE|WAVE-1-GATE|MESH|PLAN-GATE)"\]', body
    ), "seam content leaked into compiled CLOSE-SWARM script body"


def test_compile_wave_segment_batches_and_ordering(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    wave = run_graph(["compile", "--segment=WAVE-1-IMPL", "--verify"], work_dir, env)
    assert_clean(wave)
    assert "✓ soundness" in wave.stdout
    assert "✓ completeness" in wave.stdout

    wscript = work_dir / ".shepherd" / "graph" / "compiled" / "WAVE-1-IMPL.workflow.js"
    assert wscript.is_file()
    wbody = wscript.read_text()
    assert wbody.count('agentType: "shepherd:coder"') == 3
    assert wbody.count('agentType: "shepherd:worker"') == 1
    assert wbody.count('agentType: "shepherd:auditor"') == 2
    # two batches: IMPL/WORKER clique first, AUDIT second (sequential edge)
    assert wbody.count("await fanout(") == 2
    # Lane E parity (#78): NO pause/heartbeat machinery in the path...
    assert not re.search(r"PAUSE|heartbeat|PAUSE-FOR-DEPENDENCY", wbody, re.IGNORECASE)
    # ...the cross-lane dependency is realized purely by await ordering.
    coder_ln = wbody.index("shepherd:coder")
    audit_ln = wbody.index("shepherd:auditor")
    assert coder_ln < audit_ln, "cross-lane dependency not realized by in-script await ordering (#78)"


def test_compile_determinism_negative_then_self_heal(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    assert_clean(run_graph(["compile", "--verify"], work_dir, env))
    script = work_dir / ".shepherd" / "graph" / "compiled" / "CLOSE-SWARM.workflow.js"
    with script.open("a") as fh:
        fh.write("\n// tampered\n")
    tampered = run_graph(["compile", "--segment=CLOSE-SWARM", "--verify"], work_dir, env)
    assert tampered.returncode == 2, "faithfulness diff passed on a hand-edited (stale) script"
    assert "✗ determinism" in tampered.stdout
    # Self-heals: the recompile rewrote the canonical script; re-verify passes.
    healed = run_graph(["compile", "--segment=CLOSE-SWARM", "--verify"], work_dir, env)
    assert_clean(healed)
    assert "✓ determinism" in healed.stdout


def test_compile_meta_contract_and_manifest_only_compiled_at(work_dir: Path, env: dict[str, str]) -> None:
    """The Dynamic Workflow meta contract + deterministic script bytes:
    `export const meta = { name, description, phases }` is a pure literal;
    `compiled_at` lives ONLY in the manifest; the manifest's sha256 matches
    the actual script bytes; recompiling reproduces identical bytes."""
    extract(work_dir, env, COMPILE_PLAN)
    assert_clean(run_graph(["compile"], work_dir, env))
    script = work_dir / ".shepherd" / "graph" / "compiled" / "CLOSE-SWARM.workflow.js"
    manifest_path = work_dir / ".shepherd" / "graph" / "compiled" / "CLOSE-SWARM.manifest.json"
    body = script.read_text()
    manifest = json.loads(manifest_path.read_text())

    assert "export const meta = {" in body
    assert '  name: "CLOSE-SWARM",' in body
    assert "  description: " in body
    assert "  phases: " in body
    assert re.search(r"  phases: \[\[.*\]\],", body), "phases must be a pure array literal"
    assert "compiled_at" not in body, "compiled_at must NEVER enter the script body"
    for banned in ("Math.random", "Date.now", "Promise.race", "Promise.any"):
        assert banned not in body

    assert isinstance(manifest["compiled_at"], int)
    assert manifest["script_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert manifest["segment"] == "CLOSE-SWARM"
    assert manifest["total_agents"] == 3
    assert manifest["max_concurrent"] == 16

    # Recompile: byte-identical script (compiled_at may advance in manifest).
    assert_clean(run_graph(["compile"], work_dir, env))
    assert script.read_text() == body

    # The compile left a graph_compiled trace event.
    trace = run_graph(["trace"], work_dir, env)
    assert trace.stdout.count("graph_compiled") >= 2


def test_compile_json_output_and_unknown_segment(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    js_out = run_graph(["compile", "--json", "--verify"], work_dir, env)
    assert_clean(js_out)
    payload = json.loads(js_out.stdout)
    assert payload["segment"] == "CLOSE-SWARM"
    assert payload["faithfulness_ok"] is True
    assert payload["faithfulness"] == {
        "soundness": "PASS",
        "completeness": "PASS",
        "determinism": "PASS",
        "model_pin": "PASS",
    }
    bad = run_graph(["compile", "--segment=PLAN-GATE"], work_dir, env)
    assert bad.returncode == 1
    assert "no compilable segment contains node 'PLAN-GATE'" in bad.stderr


def test_compile_model_pins_resolve_from_models_config(work_dir: Path, env: dict[str, str]) -> None:
    """#180: an explicit [models] key rebinds every emitted pin for that role."""
    (work_dir / ".claude" / "shepherd.toml").write_text('[models]\nauditor = "haiku-custom"\n')
    extract(work_dir, env, COMPILE_PLAN)
    assert_clean(run_graph(["compile"], work_dir, env))
    body = (work_dir / ".shepherd" / "graph" / "compiled" / "CLOSE-SWARM.workflow.js").read_text()
    assert body.count('model: "haiku-custom"') == 3
    assert 'model: "sonnet"' not in body


# --------------------------------------------------------------------------
# diagram
# --------------------------------------------------------------------------
def test_diagram_stdout_classifies_seams_and_fanout(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN)
    proc = run_graph(["diagram", "--stdout"], work_dir, env)
    assert_clean(proc)
    assert "flowchart TD" in proc.stdout
    assert 'n_PLAN_GATE{{"' in proc.stdout  # hexagon = seam
    assert "class n_PLAN_GATE seam;" in proc.stdout
    assert "class n_CLOSE_SWARM fanout;" in proc.stdout
    assert "n_MESH -->|on-pass| n_PLAN_GATE" in proc.stdout


def test_diagram_writes_default_file_and_rejects_bad_segment(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, COMPILE_PLAN, sprint="v-diag")
    proc = run_graph(["diagram"], work_dir, env)
    assert_clean(proc)
    assert "diagram written:" in proc.stdout
    assert (work_dir / ".shepherd" / "graph" / "diagrams" / "v-diag.mmd").is_file()
    bad = run_graph(["diagram", "--segment=NOPE"], work_dir, env)
    assert bad.returncode == 1
    assert "ERROR: node 'NOPE' not in graph." in bad.stderr


# --------------------------------------------------------------------------
# run-scoped artifact shim (additive; documented in the module docstring)
# --------------------------------------------------------------------------
def test_run_scoped_state_drives_walker_and_compiler(work_dir: Path, env: dict[str, str]) -> None:
    (work_dir / "plan.md").write_text(COMPILE_PLAN)
    proc = run_plan(["extract", "plan.md", "--sprint=s", "--run=r1"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    run_graph_dir = work_dir / ".shepherd" / "runs" / "r1" / "graph"
    assert (run_graph_dir / "state.json").is_file()

    # Walker + compiler resolve the run-scoped state via --run...
    status = run_graph(["status", "--run=r1"], work_dir, env)
    assert_clean(status)
    compiled = run_graph(["compile", "--run=r1"], work_dir, env)
    assert_clean(compiled)
    # ...and derived artifacts land inside the run dir, not the legacy one.
    assert (run_graph_dir / "compiled" / "CLOSE-SWARM.workflow.js").is_file()
    assert not (work_dir / ".shepherd" / "graph").exists()
    # A run-less read still targets (and misses) the legacy path.
    legacy = run_graph(["status"], work_dir, env)
    assert legacy.returncode == 1


def test_run_flag_falls_back_to_legacy_state(work_dir: Path, env: dict[str, str]) -> None:
    extract(work_dir, env, WALK_PLAN)  # legacy write
    proc = run_graph(["status", "--run=missing-run"], work_dir, env)
    assert_clean(proc)  # ALWAYS fall back to reading legacy paths


# --------------------------------------------------------------------------
# bash-parity twins (byte-for-byte, same cwd/env, bash-written state)
# --------------------------------------------------------------------------
def _bash_extract(cwd: Path, env: dict[str, str], content: str, sprint: str) -> None:
    (cwd / "plan.md").write_text(content)
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "skills" / "context" / "scripts" / "cmd_plan.sh"), "extract", "plan.md", f"--sprint={sprint}"],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_status_and_next_bash_parity_on_bash_written_state(work_dir: Path, env: dict[str, str]) -> None:
    _bash_extract(work_dir, env, COMPILE_PLAN, "v6.0.1-dev.0")
    for args in (["status"], ["status", "--md"], ["status", "--json"], ["next"], ["next", "--json"]):
        python_proc = run_graph(args, work_dir, env)
        bash_proc = run_bash_graph(args, work_dir, env)
        assert python_proc.returncode == bash_proc.returncode == 0, args
        assert python_proc.stdout == bash_proc.stdout, args


def test_compile_script_bash_parity_modulo_meta_block(work_dir: Path, env: dict[str, str]) -> None:
    """The compiled script must equal bash's byte-for-byte EXCEPT the
    documented meta-contract block (deviation 2 in graph.py) — proving no
    accidental emission drift hid behind the intentional change."""
    _bash_extract(work_dir, env, COMPILE_PLAN, "v6.0.1-dev.0")
    bash_out = run_bash_graph(["compile", "--segment=WAVE-1-IMPL"], work_dir, env)
    assert bash_out.returncode == 0, bash_out.stderr
    script = work_dir / ".shepherd" / "graph" / "compiled" / "WAVE-1-IMPL.workflow.js"
    bash_body = script.read_text()

    py_out = run_graph(["compile", "--segment=WAVE-1-IMPL"], work_dir, env)
    assert_clean(py_out)
    py_body = script.read_text()

    meta_re = re.compile(r"export const meta = \{\n(?:.*\n)*?\};\n\n", re.MULTILINE)
    assert meta_re.search(py_body), "meta block missing from python-compiled script"
    assert meta_re.sub("", py_body) == bash_body

    # And the manifests agree on everything except timestamp + sha256.
    manifest = json.loads((work_dir / ".shepherd" / "graph" / "compiled" / "WAVE-1-IMPL.manifest.json").read_text())
    assert manifest["script_sha256"] == hashlib.sha256(py_body.encode()).hexdigest()


def test_compile_list_bash_parity(work_dir: Path, env: dict[str, str]) -> None:
    _bash_extract(work_dir, env, COMPILE_PLAN, "v6.0.1-dev.0")
    python_proc = run_graph(["compile", "--list"], work_dir, env)
    bash_proc = run_bash_graph(["compile", "--list"], work_dir, env)
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
