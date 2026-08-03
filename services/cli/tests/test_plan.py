"""Tests for `shepherd plan` — native port of `cmd_plan.sh` (no DB, pure filesystem).

Drives the module's Typer app DIRECTLY via a `${PY} -c` subprocess snippet
(`shepherd_cli.commands.plan.app`), NOT via `python -m shepherd_cli plan` —
the `plan` sub-app is not yet registered in `shepherd_cli.app`, so the
module-level invocation is the only path that exercises the Python port
both BEFORE and AFTER the integrator flips registration (going through
`-m shepherd_cli` today would hit the bash shim instead and prove
nothing about this port).

Every load-bearing assertion from the bash suite's
`skills/context/tests/test_plan_verify.sh` is migrated here (hash /
record-critique / verify with the four named failure codes), plus the
`plan extract` / `validate` halves of `test_graph_next.sh`'s GH #225
fixtures (bare-string agents shorthand normalizes; a role-less mapping
fails extract; a hand-corrupted state.json fails validate). Bash-parity
twin tests additionally run `cmd_plan.sh` under the identical cwd/env and
byte-compare stdout, including one cross-tool test where BASH extracts
the state and PYTHON reads it (the migration-safety direction).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

CMD_PLAN_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_plan.sh"

_PLAN_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.plan import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd plan')\n"
)

_GRAPH_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.graph import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd graph')\n"
)

#: `import yaml` poisoned via sys.modules — exercises the bash-parity
#: "PyYAML required" degradation without uninstalling anything.
_PLAN_NO_YAML_SNIPPET = (
    "import sys\n"
    "sys.modules['yaml'] = None\n"
    "from shepherd_cli.commands.plan import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd plan')\n"
)

#: The GH #225 fixture-A plan (bare-string shorthand + mapping form),
#: verbatim from test_graph_next.sh.
PLAN_225 = """## Stage Graph

```yaml
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  agents: [engineer]
  parallel_with: [WORKER-IO]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WORKER-IO
  type: WORKER-IO
  parallel_with: [WAVE-1-IMPL]
  agents: [{role: coder, count: 2}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WAVE-1-AUDIT
  type: WAVE-1-AUDIT
  in_predicates: [{predecessor: WAVE-1-IMPL, edge: on-pass}]
  agents: [{role: auditor, count: 1}]
```
"""


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh git repo with a `.shepherd/` workdir + shepherd.toml marker.

    Mirrors the bash tests' `git init` + `mkdir .shepherd .claude` setup
    so `resolve_repo_root()` (and bash's `shctx_repo_root`) resolve to
    this exact directory, never to the real repository.
    """
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


def run_plan(args: list[str], cwd: Path, env: dict[str, str], *, snippet: str = _PLAN_SNIPPET) -> subprocess.CompletedProcess[str]:
    """Run the plan module app directly: `${PY} -c "<snippet>" <args>`."""
    return subprocess.run([PY, "-c", snippet, *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def run_graph(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the graph module app directly (cross-module interop checks)."""
    return subprocess.run([PY, "-c", _GRAPH_SNIPPET, *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def run_bash_plan(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_plan.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(["bash", str(CMD_PLAN_SH), *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def write_plan(cwd: Path, content: str = PLAN_225, name: str = "plan.md") -> Path:
    path = cwd / name
    path.write_text(content)
    return path


def state_file(cwd: Path) -> Path:
    return cwd / ".shepherd" / "graph" / "state.json"


# --------------------------------------------------------------------------
# hash
# --------------------------------------------------------------------------
def test_hash_emits_sha256_of_plan_bytes(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "v625.plan.md"
    plan.write_text("# plan v1\nwave-1\n")
    proc = run_plan(["hash", str(plan)], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    expected = "sha256:" + hashlib.sha256(plan.read_bytes()).hexdigest()
    assert proc.stdout == expected + "\n"


def test_hash_missing_arg_exits_2(work_dir: Path, env: dict[str, str]) -> None:
    proc = run_plan(["hash"], work_dir, env)
    assert proc.returncode == 2
    assert proc.stderr.strip() == "ERROR: usage: shctx plan hash <plan.md>"


# --------------------------------------------------------------------------
# record-critique + verify (test_plan_verify.sh migration)
# --------------------------------------------------------------------------
def test_record_critique_and_verify_happy_path(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "v625.plan.md"
    plan.write_text("# plan v1\nwave-1\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    plan.write_text("# plan v2 (revised per critic)\nwave-1\nwave-2\n")

    rec = run_plan(
        ["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "PASS", "--iterations", "1", "--findings", "2"],
        work_dir,
        env,
    )
    assert rec.returncode == 0, rec.stderr
    proof = work_dir / "v625.critic-proof.json"
    assert proof.is_file(), "record-critique wrote proof"
    doc = json.loads(proof.read_text())
    assert doc["edited"] is True
    assert doc["critic"] == {"verdict": "PASS", "iterations": 1, "findings": 2}
    assert doc["pre_critic_hash"] == pre
    assert doc["post_critic_hash"] == "sha256:" + hashlib.sha256(plan.read_bytes()).hexdigest()

    ok = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert ok.stdout.startswith("OK: critic-proof valid")

    quiet = run_plan(["verify", "--plan", str(plan), "--quiet"], work_dir, env)
    assert quiet.returncode == 0
    assert quiet.stdout == ""


def test_verify_unedited_plan_fails_plan_unedited(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "u.plan.md"
    plan.write_text("# plan unedited\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    rec = run_plan(["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "PASS", "--iterations", "1"], work_dir, env)
    assert "WARNING: pre == post" in rec.stdout

    proc = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert proc.returncode == 1
    assert "PLAN-UNEDITED" in proc.stdout


def test_verify_post_proof_edit_fails_stale(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "s.plan.md"
    plan.write_text("# plan A\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    plan.write_text("# plan B (revised)\n")
    run_plan(["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "PASS", "--iterations", "1"], work_dir, env)
    plan.write_text("# plan C (edited AFTER the proof)\n")

    proc = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert proc.returncode == 1
    assert "CRITIC-PROOF-STALE" in proc.stdout


def test_verify_no_proof_fails_missing(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "noproof.plan.md"
    plan.write_text("# no proof\n")
    proc = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert proc.returncode == 1
    assert "CRITIC-PROOF-MISSING" in proc.stdout


def test_verify_bad_verdict_fails_uncritiqued(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "r.plan.md"
    plan.write_text("# plan A\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    plan.write_text("# plan B (revised)\n")
    run_plan(["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "REJECTED"], work_dir, env)

    proc = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert proc.returncode == 1
    assert "PLAN-UNCRITIQUED: verdict=REJECTED" in proc.stdout


def test_verify_without_plan_ambiguity_goes_to_stderr(work_dir: Path, env: dict[str, str]) -> None:
    """The proof-dir-ambiguity CRITIC-PROOF-MISSING is the ONE verify
    failure bash prints on stderr — the stream asymmetry is load-bearing."""
    proc = run_plan(["verify"], work_dir, env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "CRITIC-PROOF-MISSING: pass --plan <path> (found 0 proof file(s) under" in proc.stderr


def test_verify_without_plan_resolves_single_proof_via_cfg_plans_key(work_dir: Path, env: dict[str, str]) -> None:
    """`cfg_get plans` (section-agnostic, bash parity) points verify at the
    proofs dir; exactly one proof file there resolves without --plan."""
    (work_dir / ".claude" / "shepherd.toml").write_text('plans = "myplans"\n')
    plans_dir = work_dir / "myplans"
    plans_dir.mkdir()
    plan = plans_dir / "x.plan.md"
    plan.write_text("# A\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    plan.write_text("# B (revised)\n")
    run_plan(["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "PASS"], work_dir, env)
    assert (plans_dir / "x.critic-proof.json").is_file()

    proc = run_plan(["verify"], work_dir, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("OK: critic-proof valid")


def test_record_critique_missing_required_flags_exit_2(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "p.plan.md"
    plan.write_text("x\n")
    no_plan = run_plan(["record-critique", "--pre", "abc", "--verdict", "PASS"], work_dir, env)
    assert no_plan.returncode == 2
    assert "--plan <path> required" in no_plan.stderr
    no_pre = run_plan(["record-critique", "--plan", str(plan), "--verdict", "PASS"], work_dir, env)
    assert no_pre.returncode == 2
    assert "--pre <hash> required" in no_pre.stderr
    no_verdict = run_plan(["record-critique", "--plan", str(plan), "--pre", "abc"], work_dir, env)
    assert no_verdict.returncode == 2
    assert "--verdict <PASS|...> required" in no_verdict.stderr


# --------------------------------------------------------------------------
# extract (incl. the GH #225 normalization fixtures)
# --------------------------------------------------------------------------
def test_extract_normalizes_agents_and_seeds_states(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    proc = run_plan(["extract", "plan.md", "--sprint=v6.3.9-dev.0"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "extracted 3 nodes / 2 edges from plan.md" in proc.stdout
    state = json.loads(state_file(work_dir).read_text())
    assert state["sprint"] == "v6.3.9-dev.0"
    # #225: the bare-string shorthand is normalized at the single write site.
    assert state["nodes"]["WAVE-1-IMPL"]["agents"] == [{"role": "engineer", "count": 1}]
    assert state["nodes"]["WORKER-IO"]["agents"] == [{"role": "coder", "count": 2}]
    # No in_predicates -> ready; with in_predicates -> pending.
    assert state["nodes"]["WAVE-1-IMPL"]["state"] == "ready"
    assert state["nodes"]["WAVE-1-AUDIT"]["state"] == "pending"
    assert state["nodes"]["WAVE-1-AUDIT"]["in_predicates"] == [
        {"predecessor": "WAVE-1-IMPL", "edge": "on-pass", "satisfied": False}
    ]
    assert state["edges"][0] == {"from": "WAVE-1-IMPL", "label": "on-pass", "to": "WAVE-1-AUDIT"}
    # Trace initialized with the extraction event.
    trace_lines = (work_dir / ".shepherd" / "graph" / "trace.jsonl").read_text().splitlines()
    first = json.loads(trace_lines[0])
    assert first["event"] == "graph_extracted"
    assert first["node_count"] == 3


def test_extract_seed_verify_type_starts_done(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(
        work_dir,
        "## Stage Graph\n\n```yaml\n- id: SEED-VERIFY\n  type: SEED-VERIFY\n```\n",
    )
    proc = run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    state = json.loads(state_file(work_dir).read_text())
    assert state["nodes"]["SEED-VERIFY"]["state"] == "done"


def test_extract_refuses_overwrite_without_force(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    assert run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env).returncode == 0
    again = run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    assert again.returncode == 1
    assert "already exists. Pass --force to overwrite." in again.stderr
    forced = run_plan(["extract", "plan.md", "--sprint=s2", "--force"], work_dir, env)
    assert forced.returncode == 0, forced.stderr
    assert json.loads(state_file(work_dir).read_text())["sprint"] == "s2"


def test_extract_malformed_agents_mapping_fails_loudly(work_dir: Path, env: dict[str, str]) -> None:
    """GH #225 fixture B: a role-less mapping fails AT EXTRACT, not later."""
    write_plan(
        work_dir,
        "## Stage Graph\n\n```yaml\n- id: WAVE-1-IMPL\n  type: WAVE-1-IMPL\n  agents: [{count: 3}]\n```\n",
        name="plan-bad.md",
    )
    proc = run_plan(["extract", "plan-bad.md", "--sprint=s"], work_dir, env)
    assert proc.returncode == 1
    assert "malformed agents entry" in proc.stderr
    assert not state_file(work_dir).exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# no section here\n", "no `## Stage Graph` section found"),
        ("## Stage Graph\n\nprose but no fence\n", "no fenced code block under `## Stage Graph`"),
        ("## Stage Graph\n\n```yaml\njust: a-mapping\n```\n", "must be a list of node objects"),
        ("## Stage Graph\n\n```yaml\n- type: X\n```\n", "node missing `id`"),
        ("## Stage Graph\n\n```yaml\n- id: A\n- id: A\n```\n", "duplicate node id: A"),
    ],
)
def test_extract_parse_failures(content: str, message: str, work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir, content)
    proc = run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    assert proc.returncode == 1
    assert message in proc.stderr


def test_extract_missing_plan_usage_error(work_dir: Path, env: dict[str, str]) -> None:
    proc = run_plan(["extract"], work_dir, env)
    assert proc.returncode == 1
    assert proc.stderr.strip() == "ERROR: usage: shctx plan extract <plan.md>"


def test_extract_unknown_arg_exits_1(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    proc = run_plan(["extract", "plan.md", "--bogus"], work_dir, env)
    assert proc.returncode == 1
    assert proc.stderr.strip() == "ERROR: unknown arg: --bogus"


def test_extract_without_pyyaml_degrades_with_bash_message(work_dir: Path, env: dict[str, str]) -> None:
    """Bash parity: the heredoc's ImportError arm. Poisons sys.modules so
    `import yaml` raises even though the venv has PyYAML installed."""
    write_plan(work_dir)
    proc = run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env, snippet=_PLAN_NO_YAML_SNIPPET)
    assert proc.returncode == 1
    assert "ERROR: python3 PyYAML required (apt: python3-yaml | pip: PyYAML)" in proc.stderr


# --------------------------------------------------------------------------
# topology
# --------------------------------------------------------------------------
def test_topology_text_and_json(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    run_plan(["extract", "plan.md", "--sprint=v6.3.9-dev.0"], work_dir, env)

    topo = run_plan(["topology"], work_dir, env)
    assert topo.returncode == 0, topo.stderr
    assert topo.stdout.startswith("Topology — v6.3.9-dev.0  (3 nodes / 2 edges)")
    assert "engineerx1" in topo.stdout  # normalized shorthand renders rolexcount
    assert "coderx2" in topo.stdout

    topo_json = run_plan(["topology", "--json"], work_dir, env)
    assert topo_json.returncode == 0
    # bash `cat` parity: the RAW state.json bytes, no re-serialization.
    assert topo_json.stdout == state_file(work_dir).read_text()

    topo_md = run_plan(["topology", "--md"], work_dir, env)
    assert topo_md.stdout.startswith("## Topology — v6.3.9-dev.0")
    assert "### Edges" in topo_md.stdout


def test_topology_without_state_errors(work_dir: Path, env: dict[str, str]) -> None:
    proc = run_plan(["topology"], work_dir, env)
    assert proc.returncode == 1
    assert "ERROR: no graph state at" in proc.stderr
    assert "run 'shctx plan extract <plan.md>' first" in proc.stderr


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------
def test_validate_ok_on_clean_graph(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    proc = run_plan(["validate"], work_dir, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "validate: OK  (3 nodes, 2 edges, topological order valid)"


def test_validate_catches_hand_corrupted_agents(work_dir: Path, env: dict[str, str]) -> None:
    """GH #225 fixture C: a malformed agents entry that slipped past
    extract (hand-edited state.json) fails validate instead of OK-ing a
    graph that would AttributeError in `graph next`."""
    write_plan(work_dir, "## Stage Graph\n\n```yaml\n- id: WAVE-1-IMPL\n  type: WAVE-1-IMPL\n  agents: [engineer]\n```\n")
    run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    state = json.loads(state_file(work_dir).read_text())
    state["nodes"]["WAVE-1-IMPL"]["agents"] = [{"count": 3}]
    state_file(work_dir).write_text(json.dumps(state, indent=2))

    proc = run_plan(["validate"], work_dir, env)
    assert proc.returncode == 1
    assert "malformed agents entry" in proc.stdout

    # And the reader-side guard: `graph next` degrades, never crashes.
    nxt = run_graph(["next"], work_dir, env)
    assert nxt.returncode == 0, nxt.stderr
    assert "AttributeError" not in nxt.stdout + nxt.stderr
    assert "Traceback" not in nxt.stdout + nxt.stderr


def test_validate_structural_failures(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(
        work_dir,
        "## Stage Graph\n\n```yaml\n"
        "- id: A\n  type: WAVE-1-IMPL\n  agents: [coder]\n  parallel_with: [B]\n"
        "  in_predicates: [{predecessor: B, edge: on-pass}]\n"
        "  out_edges: [{label: on-pass, target: NOPE}]\n"
        "- id: B\n  type: WAVE-1-IMPL\n  agents: [coder]\n"
        "  in_predicates: [{predecessor: A, edge: on-pass}]\n"
        "```\n",
    )
    run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    proc = run_plan(["validate"], work_dir, env)
    assert proc.returncode == 1
    assert "VALIDATION FAILED:" in proc.stdout
    assert "target node missing" in proc.stdout  # edge A --on-pass--> NOPE
    assert "parallel_with not mutual: A <-> B" in proc.stdout
    assert "cycle detected involving nodes: ['A', 'B']" in proc.stdout


# --------------------------------------------------------------------------
# dispatch: usage / unknown subcommand
# --------------------------------------------------------------------------
@pytest.mark.parametrize("args", [[], ["-h"], ["--help"]])
def test_bare_and_help_print_usage_exit_0(args: list[str], work_dir: Path, env: dict[str, str]) -> None:
    proc = run_plan(args, work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("shctx plan <extract|topology|validate|hash|record-critique|verify> [args]")


def test_unknown_subcommand_exits_1_with_stderr_usage(work_dir: Path, env: dict[str, str]) -> None:
    proc = run_plan(["bogus"], work_dir, env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("ERROR: unknown subcommand: bogus")
    assert "shctx plan <extract|topology|validate" in proc.stderr


# --------------------------------------------------------------------------
# run-scoped artifact shim (additive; documented in the module docstring)
# --------------------------------------------------------------------------
def test_extract_with_run_flag_writes_run_scoped_state(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    proc = run_plan(["extract", "plan.md", "--sprint=s", "--run=r1"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    run_state = work_dir / ".shepherd" / "runs" / "r1" / "graph" / "state.json"
    assert run_state.is_file()
    assert not state_file(work_dir).exists()  # legacy path untouched

    # Readers with the same --run resolve the run-scoped state...
    topo = run_plan(["topology", "--run=r1"], work_dir, env)
    assert topo.returncode == 0, topo.stderr
    validate = run_plan(["validate", "--run=r1"], work_dir, env)
    assert validate.returncode == 0, validate.stdout + validate.stderr
    # ...while a run-less read still targets (and misses) the legacy path.
    legacy = run_plan(["topology"], work_dir, env)
    assert legacy.returncode == 1


def test_shepherd_run_env_identifies_active_run(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    env_run = dict(env)
    env_run["SHEPHERD_RUN"] = "r2"
    proc = run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env_run)
    assert proc.returncode == 0, proc.stderr
    assert (work_dir / ".shepherd" / "runs" / "r2" / "graph" / "state.json").is_file()


def test_run_flag_falls_back_to_legacy_state_when_run_scoped_absent(work_dir: Path, env: dict[str, str]) -> None:
    """The ALWAYS-fall-back-on-read rule: legacy state, --run given, no
    run-scoped state.json — reads resolve the legacy path."""
    write_plan(work_dir)
    run_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)  # legacy write
    proc = run_plan(["topology", "--run=r9"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert "Topology — s" in proc.stdout


# --------------------------------------------------------------------------
# bash-parity twins (byte-for-byte, same cwd/env)
# --------------------------------------------------------------------------
def test_usage_bash_parity(work_dir: Path, env: dict[str, str]) -> None:
    python_proc = run_plan([], work_dir, env)
    bash_proc = run_bash_plan([], work_dir, env)
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_topology_bash_parity_on_bash_written_state(work_dir: Path, env: dict[str, str]) -> None:
    """Cross-tool migration safety: BASH extracts the state, then both
    tools' `topology` renderings byte-match on that same file."""
    write_plan(work_dir)
    extracted = run_bash_plan(["extract", "plan.md", "--sprint=v6.3.9-dev.0"], work_dir, env)
    assert extracted.returncode == 0, extracted.stderr
    python_proc = run_plan(["topology"], work_dir, env)
    bash_proc = run_bash_plan(["topology"], work_dir, env)
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
    python_md = run_plan(["topology", "--md"], work_dir, env)
    bash_md = run_bash_plan(["topology", "--md"], work_dir, env)
    assert python_md.stdout == bash_md.stdout


def test_validate_bash_parity(work_dir: Path, env: dict[str, str]) -> None:
    write_plan(work_dir)
    run_bash_plan(["extract", "plan.md", "--sprint=s"], work_dir, env)
    python_proc = run_plan(["validate"], work_dir, env)
    bash_proc = run_bash_plan(["validate"], work_dir, env)
    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_hash_and_verify_bash_parity(work_dir: Path, env: dict[str, str]) -> None:
    plan = work_dir / "v625.plan.md"
    plan.write_text("# plan v1\n")
    python_hash = run_plan(["hash", str(plan)], work_dir, env)
    bash_hash = run_bash_plan(["hash", str(plan)], work_dir, env)
    assert python_hash.stdout == bash_hash.stdout

    pre = python_hash.stdout.strip()
    plan.write_text("# plan v2 (revised)\n")
    run_plan(["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", "PASS"], work_dir, env)
    python_v = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    bash_v = run_bash_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert python_v.returncode == bash_v.returncode == 0
    assert python_v.stdout == bash_v.stdout
