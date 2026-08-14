"""Focused tests for `shepherd plan amend` (#268) and `shepherd plan lane-drift`
(#269) — the two v6.4.4 verbs `hooks/tests/test_v644_wiring.sh` pins live.

`tests/test_plan.py` already carries the broad bash-parity + structural suite
for the whole `plan` app (extract/topology/validate/hash/record-critique/
verify, plus its own amend/lane-drift coverage). This file is narrower and
adds the one property neither file previously asserted directly: that
`amend` cannot be used to launder a REJECTED critic verdict into a passing
one. That is the exact failure mode #268 warns against -- "an amend that
silently satisfies the proof check would turn a real gate into a rubber
stamp" -- so it gets its own test rather than living implicitly inside a
happy-path assertion.

Same harness pattern as `test_plan.py`: drive `shepherd_cli.commands.plan.
app` directly as a `${PY} -c` subprocess (never `python -m shepherd_cli`,
never the `bin/shepherd`/`shctx` wrapper scripts) so cwd/env stay fully
explicit per test.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, clean_env_dict

_PLAN_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.plan import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd plan')\n"
)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh git repo with a `.shepherd/` workdir + shepherd.toml marker.

    Mirrors `test_plan.py`'s fixture so `resolve_repo_root()` resolves to
    this directory, never to the real repository.
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
    """Stripped env (+ SHCTX_QUIET, - SHEPHERD_RUN), same as `test_plan.py`."""
    e = clean_env_dict()
    e.pop("SHEPHERD_RUN", None)
    e["SHCTX_QUIET"] = "1"
    return e


def run_plan(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the plan module app directly: `${PY} -c "<snippet>" <args>`."""
    return subprocess.run(
        [PY, "-c", _PLAN_SNIPPET, *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30
    )


def _proofed_plan(work_dir: Path, env: dict[str, str], *, body: str, verdict: str) -> Path:
    """A plan carrying a critic-proof recorded with the given verdict.

    Args:
        body: The plan bytes AFTER the (simulated) critic pass.
        verdict: The verdict `record-critique` stamps into the proof --
            "PASS" for an approved plan, "FAIL" for a rejected one.
    """
    plan = work_dir / "plan.md"
    plan.write_text("# Plan v1\n")
    pre = run_plan(["hash", str(plan)], work_dir, env).stdout.strip()
    plan.write_text(body)
    proc = run_plan(
        ["record-critique", "--plan", str(plan), "--pre", pre, "--verdict", verdict, "--iterations", "2"],
        work_dir,
        env,
    )
    assert proc.returncode == 0, proc.stderr
    return plan


# --------------------------------------------------------------------------
# amend (#268) -- happy path: root's legitimate mid-sprint correction.
# --------------------------------------------------------------------------
def test_amend_happy_path_re_greens_verify_after_a_root_edit(work_dir: Path, env: dict[str, str]) -> None:
    """edit -> STALE -> amend -> verify passes again, with the amendment on record."""
    plan = _proofed_plan(work_dir, env, body="# Plan v2\n", verdict="PASS")
    assert run_plan(["verify", "--plan", str(plan)], work_dir, env).returncode == 0

    plan.write_text("# Plan v3 -- root's mid-sprint correction\n")
    stale = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert stale.returncode == 1
    assert "CRITIC-PROOF-STALE" in stale.stdout

    amended = run_plan(
        ["amend", "--plan", str(plan), "--reason", "CONTEXT-INVENTORY asserted the inverted direction"],
        work_dir,
        env,
    )
    assert amended.returncode == 0, amended.stderr
    assert "plan amended" in amended.stdout

    # `_cmd_amend`'s closing message was previously the unconditional (and
    # false) claim "'shctx plan verify' now passes; the proof records the
    # amendment." -- false because amend never touches the `critic` block, so
    # a REJECTED verdict (proved below, in
    # test_amend_cannot_launder_a_rejected_critic_verdict_into_a_pass) stays
    # REJECTED after an amend. Fixed to the accurate, conditional wording
    # below. Pin it here: without this assertion, reverting the message back
    # to the false "now passes" claim leaves every test in this file green.
    assert "hash re-tied to the plan's current bytes; the amendment is recorded." in amended.stdout
    assert (
        "'shctx plan verify' re-checks the critic verdict independently -- "
        "a plan the critic REJECTED is still rejected after this." in amended.stdout
    )
    assert "now passes" not in amended.stdout

    reverified = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert reverified.returncode == 0, reverified.stdout

    doc = json.loads((work_dir / "plan.critic-proof.json").read_text())
    assert len(doc["amendments"]) == 1
    assert doc["amendments"][0]["reason"] == "CONTEXT-INVENTORY asserted the inverted direction"


# --------------------------------------------------------------------------
# amend (#268) -- the anti-forgery property: amend re-ties the HASH, never
# the VERDICT. Assumption this test pins: `_cmd_amend` never reads or
# writes `doc["critic"]`, and `_cmd_verify`'s verdict check re-runs against
# that untouched block on every call, amended or not -- so a verdict a
# critic genuinely rejected cannot be walked back to a pass by amending.
# --------------------------------------------------------------------------
def test_amend_cannot_launder_a_rejected_critic_verdict_into_a_pass(work_dir: Path, env: dict[str, str]) -> None:
    """A FAIL verdict must stay a FAIL verdict after amend -- amend is a
    hash re-tie plus an audit record, never a second bite at the critic.

    Without this, root could dodge a real critic rejection by touching the
    plan and calling `amend`, which is exactly the "rubber stamp" #268
    warns amend must never become.
    """
    plan = _proofed_plan(work_dir, env, body="# Plan v2 (critic rejected)\n", verdict="FAIL")
    rejected = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert rejected.returncode == 1
    assert "PLAN-UNCRITIQUED" in rejected.stdout

    before = json.loads((work_dir / "plan.critic-proof.json").read_text())
    plan.write_text("# Plan v3 -- root tries to re-gate around the FAIL\n")
    amended = run_plan(["amend", "--plan", str(plan), "--reason", "attempted re-gate"], work_dir, env)
    # amend itself succeeds: re-tying the hash to an honestly-edited plan and
    # recording WHY is legitimate on its own terms...
    assert amended.returncode == 0, amended.stderr

    after = json.loads((work_dir / "plan.critic-proof.json").read_text())
    assert after["critic"] == before["critic"]  # ...but the verdict block never moved.

    # ...and verify -- run fresh, independently of anything amend printed --
    # still refuses. No rubber stamp.
    still_rejected = run_plan(["verify", "--plan", str(plan)], work_dir, env)
    assert still_rejected.returncode == 1
    assert "PLAN-UNCRITIQUED" in still_rejected.stdout


# --------------------------------------------------------------------------
# amend (#268) -- a plan under a run that never materialized.
# --------------------------------------------------------------------------
def test_amend_refuses_a_plan_under_a_run_that_never_materialized(work_dir: Path, env: dict[str, str]) -> None:
    """`--plan` pointing under a run directory nobody ever spawned: the
    file-existence guard fires before any proof lookup is even attempted."""
    ghost_plan = work_dir / ".shepherd" / "runs" / "v999-neverexisted" / "plan.md"
    proc = run_plan(["amend", "--plan", str(ghost_plan), "--reason", "x"], work_dir, env)
    assert proc.returncode == 2
    assert "required and must exist" in proc.stderr


# --------------------------------------------------------------------------
# lane-drift (#269) -- fixture pair (a fresh lane, distinct from test_plan.py's).
# --------------------------------------------------------------------------
_LANE_VARS = {
    "steps": [
        {
            "id": "S1",
            "title": "wire the retry guard into the dispatch loop",
            "actions": ["implement retry_guard.py", "wire it into dispatch.py"],
            "acceptance": "pytest tests/test_retry_guard.py passes",
        }
    ],
    "acceptance": ["lane tests pass"],
}

_LANE_PLAN = """# Lane l9-fixture -- fixture lane

## Steps

### S1: wire the retry guard into the dispatch loop

- [ ] implement retry_guard.py
- [ ] wire it into dispatch.py
- **Acceptance:** pytest tests/test_retry_guard.py passes

## Lane acceptance

- [ ] lane tests pass

## Deviations

(none yet)
"""


def _lane(work_dir: Path, run: str, lane: str, *, plan: str, variables: dict) -> None:
    """Materialize one lane's plan.md + vars.json under runs/{run}/lanes/{lane}/."""
    lane_dir = work_dir / ".shepherd" / "runs" / run / "lanes" / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    (lane_dir / "plan.md").write_text(plan)
    (lane_dir / "vars.json").write_text(json.dumps(variables))


# --------------------------------------------------------------------------
# lane-drift (#269) -- both commands' happy path lives here: a correctly
# mirrored pair must NOT be flagged. This is the negative control that
# proves the check distinguishes real drift from noise -- without it, a
# check that just complains on every invocation would "pass" this suite too.
# --------------------------------------------------------------------------
def test_lane_drift_clean_on_a_matching_pair(work_dir: Path, env: dict[str, str]) -> None:
    _lane(work_dir, "v645-t1", "l9-fixture", plan=_LANE_PLAN, variables=_LANE_VARS)
    proc = run_plan(["lane-drift", "v645-t1"], work_dir, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "lane-drift: ok" in proc.stdout


# --------------------------------------------------------------------------
# lane-drift (#269) -- the paired positive control: introduce ONE real
# divergence (mirroring the #269 "inverted step title" failure mode) and
# confirm it is caught, non-zero, and named -- proving the check can tell
# the two states apart, not just complain in both.
# --------------------------------------------------------------------------
def test_lane_drift_detects_a_deliberately_introduced_divergence(work_dir: Path, env: dict[str, str]) -> None:
    drifted = json.loads(json.dumps(_LANE_VARS))
    drifted["steps"][0]["title"] = "wire an entirely different guard"
    _lane(work_dir, "v645-t2", "l9-fixture", plan=_LANE_PLAN, variables=drifted)

    proc = run_plan(["lane-drift", "v645-t2"], work_dir, env)
    assert proc.returncode == 1
    assert "step[0].title DRIFT" in proc.stdout
    assert "wire the retry guard into the dispatch loop" in proc.stdout  # plan.md's copy
    assert "wire an entirely different guard" in proc.stdout  # vars.json's stale copy
