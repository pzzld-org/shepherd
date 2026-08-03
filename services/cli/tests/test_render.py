"""Tests for ``shepherd render`` + the ``shepherd_cli.render`` engine.

Determinism is the contract under test (#244/#243): identical template +
identical variables must produce byte-identical output and byte-identical
lineage manifests, missing variables must hard-fail (StrictUndefined), and
the project -> user -> bundled search precedence must hold.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import clean_env_dict, run_cli

#: The full 13-key handoff context (skills/context/references/handoff-template.md).
HANDOFF_VARS = {
    "BRANCH": "v6.4.1-dev.0",
    "DATE": "2026-08-02",
    "SESSION": "sess-0001",
    "NORTH_STAR": "one canonical CLI",
    "COMMITS": "abc1234 first\ndef5678 second",
    "ARTIFACTS_COUNT": "3",
    "MEM_COUNT": "2",
    "LOCK_COUNT": "1",
    "OPEN_ISSUES_COUNT": "27",
    "DRIFT_RISK_COUNT": "0",
    "CARRY_FORWARDS": "- none",
    "NEXT_FOCUS": "- retire bash",
    "FILES_OF_INTEREST": "- services/cli/",
}


def _env(tmp_path: Path) -> dict[str, str]:
    """A stripped env pinning workdir + user home into tmp_path."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    env["SHEPHERD_HOME"] = str(tmp_path / "user-home")
    return env


def _vars_file(tmp_path: Path, variables: dict[str, object]) -> Path:
    path = tmp_path / "vars.json"
    path.write_text(json.dumps(variables))
    return path


def test_list_enumerates_bundled_templates(tmp_path: Path) -> None:
    """``render --list`` includes every bundled *.j2 with its source root."""
    proc = run_cli(["render", "--list"], _env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    names = {line.split("\t")[0] for line in proc.stdout.splitlines()}
    assert {"handoff.md.j2", "boot-prompt.md.j2", "lane-plan.md.j2", "seed.md.j2", "plan.md.j2"} <= names


def test_render_handoff_is_deterministic(tmp_path: Path) -> None:
    """Two renders of the same template + vars are byte-identical."""
    vars_file = _vars_file(tmp_path, HANDOFF_VARS)
    env = _env(tmp_path)
    first = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], env)
    second = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], env)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert "v6.4.1-dev.0" in first.stdout
    assert "abc1234 first" in first.stdout


def test_bare_stem_appends_j2_suffix(tmp_path: Path) -> None:
    """``render handoff.md`` resolves handoff.md.j2."""
    vars_file = _vars_file(tmp_path, HANDOFF_VARS)
    proc = run_cli(["render", "handoff.md", "--vars-json", str(vars_file)], _env(tmp_path))
    assert proc.returncode == 0, proc.stderr


def test_missing_template_exits_3(tmp_path: Path) -> None:
    proc = run_cli(["render", "no-such-template.md.j2"], _env(tmp_path))
    assert proc.returncode == 3
    assert "template not found" in proc.stderr


def test_missing_variable_exits_4(tmp_path: Path) -> None:
    """StrictUndefined: an incomplete context is a hard error, never a blank."""
    incomplete = dict(HANDOFF_VARS)
    del incomplete["NORTH_STAR"]
    vars_file = _vars_file(tmp_path, incomplete)
    proc = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], _env(tmp_path))
    assert proc.returncode == 4
    assert "undefined template variable" in proc.stderr


def test_var_flag_overrides_vars_json(tmp_path: Path) -> None:
    vars_file = _vars_file(tmp_path, HANDOFF_VARS)
    proc = run_cli(
        ["render", "handoff.md.j2", "--vars-json", str(vars_file), "--var", "BRANCH=override-branch"],
        _env(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "override-branch" in proc.stdout
    assert "v6.4.1-dev.0" not in proc.stdout


def test_out_and_manifest_lineage(tmp_path: Path) -> None:
    """--out writes the artifact; --manifest writes sha lineage with NO timestamp."""
    vars_file = _vars_file(tmp_path, HANDOFF_VARS)
    out = tmp_path / "artifacts" / "handoff.md"
    env = _env(tmp_path)
    proc = run_cli(
        ["render", "handoff.md.j2", "--vars-json", str(vars_file), "--out", str(out), "--manifest"],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    manifest = json.loads((tmp_path / "artifacts" / "handoff.md.manifest.json").read_text())
    assert set(manifest) == {"template", "template_path", "template_sha256", "vars_sha256", "output_sha256"}
    assert len(manifest["output_sha256"]) == 64

    # Re-render: manifest bytes identical (no volatile fields).
    first_manifest = (tmp_path / "artifacts" / "handoff.md.manifest.json").read_bytes()
    run_cli(
        ["render", "handoff.md.j2", "--vars-json", str(vars_file), "--out", str(out), "--manifest"],
        env,
    )
    assert (tmp_path / "artifacts" / "handoff.md.manifest.json").read_bytes() == first_manifest


def test_project_template_shadows_bundled(tmp_path: Path) -> None:
    """A <workdir>/templates/ copy wins over the bundled package template."""
    workdir_templates = tmp_path / ".shepherd" / "templates"
    workdir_templates.mkdir(parents=True)
    (workdir_templates / "handoff.md.j2").write_text("PROJECT OVERRIDE {{ BRANCH }}\n")
    vars_file = _vars_file(tmp_path, HANDOFF_VARS)
    proc = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], _env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "PROJECT OVERRIDE v6.4.1-dev.0\n"


def test_user_template_shadows_bundled_but_not_project(tmp_path: Path) -> None:
    """~/.shepherd/templates sits between project and bundled in precedence."""
    user_templates = tmp_path / "user-home" / "templates"
    user_templates.mkdir(parents=True)
    (user_templates / "handoff.md.j2").write_text("USER OVERRIDE\n")
    vars_file = _vars_file(tmp_path, {})
    proc = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], _env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "USER OVERRIDE\n"

    project_templates = tmp_path / ".shepherd" / "templates"
    project_templates.mkdir(parents=True)
    (project_templates / "handoff.md.j2").write_text("PROJECT WINS\n")
    proc2 = run_cli(["render", "handoff.md.j2", "--vars-json", str(vars_file)], _env(tmp_path))
    assert proc2.stdout == "PROJECT WINS\n"


def test_boot_prompt_stable_prefix_ordering(tmp_path: Path) -> None:
    """#243: two lanes' boot prompts share a byte prefix through the stable
    blocks; the per-lane INVOCATION-CONTEXT diverges only at the tail."""
    base_vars: dict[str, object] = {
        "plugin_root": "/plug",
        "model_pin": "sonnet",
        "lead_effort": "ultracode",
        "claude_md_path": "/repo/CLAUDE.md",
        "run_dir": ".shepherd/runs/v641-dev0",
        "seed_path": ".shepherd/runs/v641-dev0/seed.md",
        "plan_path": ".shepherd/runs/v641-dev0/plan.md",
        "prior_handoff_path": "-",
        "carry_forward_issues": "-",
        "worktree_path": "/repo/.worktrees/v641-dev0-lane-1",
        "base_commit": "abc1234",
        "git_custody": "lane",
        "toml_snapshot": "",
        "root_session_name": "shepherd-root @ sess-1",
        "team_id": "team-1",
        "scope": "sprint",
        "fanout_mode": "lane",
        "wave_index": "1_of_2",
        "parallel_index": None,
        "peer_teammate_names": [],
    }
    env = _env(tmp_path)
    lane_a = dict(base_vars, lane_plan_path=".shepherd/runs/v641-dev0/lanes/a/plan.md", lane_index="1_of_2")
    lane_b = dict(base_vars, lane_plan_path=".shepherd/runs/v641-dev0/lanes/b/plan.md", lane_index="2_of_2")
    out_a = run_cli(["render", "boot-prompt.md.j2", "--vars-json", str(_vars_file(tmp_path, lane_a))], env)
    vars_b = tmp_path / "vars-b.json"
    vars_b.write_text(json.dumps(lane_b))
    out_b = run_cli(["render", "boot-prompt.md.j2", "--vars-json", str(vars_b)], env)
    assert out_a.returncode == 0, out_a.stderr
    assert out_b.returncode == 0, out_b.stderr

    prohibitions_at = out_a.stdout.index("HARD PROHIBITIONS")
    invocation_at = out_a.stdout.index("INVOCATION-CONTEXT")
    assert prohibitions_at < invocation_at, "stable blocks must precede volatile context"
    # The shared byte prefix must cover at least the whole stable region.
    shared = 0
    for char_a, char_b in zip(out_a.stdout, out_b.stdout):
        if char_a != char_b:
            break
        shared += 1
    assert shared >= prohibitions_at
