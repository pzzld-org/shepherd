"""CLI-level tests for ``shepherd run ledger *`` / ``shepherd run wave verify``
(v6.4.3, #261/#262 — ``shepherd_cli/verdicts.py``'s pure-function core wrapped
as a thin typer surface in ``shepherd_cli/commands/run.py``).

Every test drives the real CLI as a fresh subprocess (issue #198's
established contract — see ``conftest.py``'s own module docstring), with
explicit ``cwd``/env on every call. Unlike ``test_run.py``'s helpers, this
file does NOT use ``conftest.run_cli`` (which hardcodes ``cwd=CLI_ROOT`` —
CLI_ROOT sits inside THIS repo's own git working tree). ``ledger check``/
``ledger path --check`` always shell out to ``git worktree list
--porcelain``, so running them with ``cwd=CLI_ROOT`` would enumerate the
REAL surrounding repo's worktrees instead of a throwaway fixture -- a
correctness leak, not just a style choice. Every test here instead drives
its own ``_run_cli`` with an explicit, isolated ``cwd``: a fresh non-git
``work_dir`` for scenarios that don't need real git worktrees (mirroring
``test_init.py``'s own isolation pattern), or a real throwaway git repo +
linked worktree (mirroring ``test_resolution.py``'s / ``test_verdicts.py``'s
``_init_repo_with_worktree``) for the worktree-divergence scenarios spec
section 6 requires.

Spec section 6 checklist covered here:

- exit codes 0 / 2 / 3 / 5 / 6 / 7 across all three subcommands.
- worktree divergence BOTH directions: a worktree row absent from primary
  FAILS (exit 7); a worktree merely BEHIND passes clean (exit 0) — a HARD
  requirement with its own dedicated test.
- primary-checkout resolution from inside a linked worktree (``ledger
  path`` prints the PRIMARY's absolute path, never the worktree's own).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, clean_env_dict

LEDGER_FILENAME = "auditor-verdicts.txt"


# --------------------------------------------------------------------------
# Subprocess + fixture helpers.
# --------------------------------------------------------------------------
def _run_cli(
    args: list[str], cwd: Path, env: dict[str, str] | None = None, *, timeout: float = 15.0
) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli <args>`` under an EXPLICIT ``cwd``.

    See the module docstring for why this (not ``conftest.run_cli``) is
    used throughout this file.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", *args],
        cwd=str(cwd),
        env=env if env is not None else clean_env_dict(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory — the CLI's cwd / repo-root fallback.

    Mirrors ``test_init.py``'s identical fixture: ``resolve_repo_root()``
    falls back to ``os.getcwd()`` outside a git repo, so ``work_dir`` IS
    the repo root and the namespace resolves to ``work_dir/.shepherd``
    with no ``SHEPHERD_WORKDIR`` override needed.
    """
    d = tmp_path / "work"
    d.mkdir()
    return d


def _ns(root: Path) -> Path:
    """The ``.shepherd`` namespace directory under a resolved repo root."""
    return root / ".shepherd"


def _write_ledger(root: Path, run: str, text: str) -> Path:
    """Write ``<root>/.shepherd/runs/<run>/auditor-verdicts.txt`` directly."""
    run_dir = _ns(root) / "runs" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / LEDGER_FILENAME
    path.write_text(text)
    return path


def _plan_md(*step_ids: str) -> str:
    """A minimal lane plan.md with one ``### <id>: title`` heading per step id."""
    return "".join(f"### {sid}: some step\n\nbody text\n\n" for sid in step_ids)


def _write_lane_plan(root: Path, run: str, lane: str, *step_ids: str) -> Path:
    """Write ``<root>/.shepherd/runs/<run>/lanes/<lane>/plan.md`` directly."""
    lane_dir = _ns(root) / "runs" / run / "lanes" / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    path = lane_dir / "plan.md"
    path.write_text(_plan_md(*step_ids))
    return path


def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real git repo with one linked worktree.

    Duplicated (not imported) from ``test_resolution.py`` /
    ``test_verdicts.py``'s identical fixture — this suite's established
    self-contained-test-module convention (see ``test_config_schema.py``'s
    own module docstring).

    Returns:
        ``(main_root, worktree_root)`` — the primary checkout and a linked
        worktree at a sibling path, with one commit so ``worktree add``
        works.
    """
    main = tmp_path / "main"
    main.mkdir()
    env = clean_env_dict()
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(args, cwd=main, env=env, check=True, capture_output=True)
    wt = tmp_path / "lane-wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "lane-1", "main"],
        cwd=main,
        env=env,
        check=True,
        capture_output=True,
    )
    return main, wt


# ==========================================================================
# ``shepherd run ledger path``.
# ==========================================================================
def test_ledger_path_prints_absolute_canonical_path(work_dir: Path) -> None:
    """``ledger path`` prints the exact ``{workdir}/runs/{run}/auditor-verdicts.txt``
    absolute path -- need not exist on disk (mirrors ``verdicts.ledger_path``'s
    own contract)."""
    proc = _run_cli(["run", "ledger", "path", "v641-dev0"], work_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(_ns(work_dir) / "runs" / "v641-dev0" / LEDGER_FILENAME)


def test_ledger_path_invalid_run_id_exits_2(work_dir: Path) -> None:
    proc = _run_cli(["run", "ledger", "path", "../escape"], work_dir)
    assert proc.returncode == 2
    assert "invalid run id" in proc.stderr


def test_ledger_path_no_run_and_no_active_run_exits_2(work_dir: Path) -> None:
    """Omitting ``<run>`` with no ``runs/`` directory at all -- exit 2, not
    a crash -- see this module's ``ledger path`` docstring entry."""
    proc = _run_cli(["run", "ledger", "path"], work_dir)
    assert proc.returncode == 2
    assert "no active run" in proc.stderr


def test_ledger_path_omitted_run_resolves_the_active_run(work_dir: Path) -> None:
    """The active run is the mtime-newest ``run.json`` with ``status:
    "executing"`` -- mirrors ``hooks/scripts/_lib.sh``'s ``active_run_dir``."""
    init_a = _run_cli(["run", "init", "v641-dev0"], work_dir)
    assert init_a.returncode == 0, init_a.stderr
    init_b = _run_cli(["run", "init", "v641-dev1"], work_dir)
    assert init_b.returncode == 0, init_b.stderr
    set_executing = _run_cli(["run", "set", "v641-dev1", "--status", "executing"], work_dir)
    assert set_executing.returncode == 0, set_executing.stderr

    proc = _run_cli(["run", "ledger", "path"], work_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(_ns(work_dir) / "runs" / "v641-dev1" / LEDGER_FILENAME)


def test_ledger_path_from_linked_worktree_resolves_primary_checkout(tmp_path: Path) -> None:
    """#261/#221/#231: ``ledger path`` run from inside a LINKED worktree
    still prints the PRIMARY checkout's absolute path -- never the
    worktree's own divorced copy. The exact custody guarantee spec section
    1 says must not regress."""
    main, wt = _init_repo_with_worktree(tmp_path)
    env = clean_env_dict()  # no SHEPHERD_WORKDIR override -- auto-detect via git.

    proc = _run_cli(["run", "ledger", "path", "v641-dev0"], wt, env)

    assert proc.returncode == 0, proc.stderr
    expected = str((main / ".shepherd" / "runs" / "v641-dev0" / LEDGER_FILENAME).resolve())
    assert proc.stdout.strip() == expected
    assert not proc.stdout.startswith(str(wt.resolve()))


def test_ledger_path_check_from_primary_never_flags(tmp_path: Path) -> None:
    """``--check`` is a no-op (exit 0) from the PRIMARY checkout -- there is
    no "linked worktree" risk to detect."""
    main, _wt = _init_repo_with_worktree(tmp_path)
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "path", "v641-dev0", "--check"], main, env)
    assert proc.returncode == 0, proc.stderr


def test_ledger_path_check_clean_when_no_local_worktree_copy_exists(tmp_path: Path) -> None:
    """From inside a linked worktree, with NO local ledger copy present
    there, ``--check`` passes clean (exit 0) -- nothing to warn about."""
    _main, wt = _init_repo_with_worktree(tmp_path)
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "path", "v641-dev0", "--check"], wt, env)
    assert proc.returncode == 0, proc.stderr


def test_ledger_path_check_exits_3_when_divergent_local_copy_exists(tmp_path: Path) -> None:
    """From inside a linked worktree, a local ``.shepherd/runs/<run>/
    auditor-verdicts.txt`` copy composed relative to THAT worktree's own
    cwd is exactly the #261 hazard -- ``--check`` exits 3 and names it."""
    _main, wt = _init_repo_with_worktree(tmp_path)
    local_copy = _write_ledger(wt, "v641-dev0", "L1 w1-s1 PASS a local, wrong-worktree copy\n")
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "path", "v641-dev0", "--check"], wt, env)

    assert proc.returncode == 3
    assert str(local_copy.resolve()) in proc.stderr or str(local_copy) in proc.stderr
    # The absolute (primary) path is still printed on stdout even though
    # --check flagged a risk -- the command's primary job (print the
    # canonical path) still happens.
    assert proc.stdout.strip().endswith("/auditor-verdicts.txt")
    assert "lane-wt" not in proc.stdout


# ==========================================================================
# ``shepherd run ledger check``.
# ==========================================================================
def test_ledger_check_exit_5_when_no_ledger_exists(work_dir: Path) -> None:
    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], work_dir)
    assert proc.returncode == 5
    assert "no ledger" in proc.stderr


def test_ledger_check_invalid_run_id_exits_2(work_dir: Path) -> None:
    proc = _run_cli(["run", "ledger", "check", "../escape"], work_dir)
    assert proc.returncode == 2


def test_ledger_check_no_run_and_no_active_run_exits_2(work_dir: Path) -> None:
    proc = _run_cli(["run", "ledger", "check"], work_dir)
    assert proc.returncode == 2
    assert "no active run" in proc.stderr


def test_ledger_check_clean_outside_a_git_repo_exits_0_with_no_output(work_dir: Path) -> None:
    """Outside a git repo entirely (``git worktree list`` itself fails),
    the check degrades to "no worktrees to compare" -- clean, exit 0, no
    output, exactly like ``run wave pending``'s own empty-set idiom."""
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 PASS ok\n")
    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], work_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_ledger_check_worktree_row_absent_from_primary_fails(tmp_path: Path) -> None:
    """FAIL case (exit 7): a linked worktree's local ledger copy holds a row
    the primary lacks -- the destructive shape (merging it could silently
    drop a sibling lane's row)."""
    main, wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(main, "v641-dev0", "L1 w3-s1 PASS ok\n")
    _write_ledger(wt, "v641-dev0", "L1 w3-s1 PASS ok\nL2 w3-s1 PASS only the worktree has this\n")
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], main, env)

    assert proc.returncode == 7
    assert "L2 w3-s1 PASS only the worktree has this" in proc.stdout


def test_ledger_check_worktree_merely_behind_primary_passes_clean(tmp_path: Path) -> None:
    """HARD requirement (spec section 1.2): a worktree missing rows the
    PRIMARY has (every lane's normal state between merges) must NEVER be
    flagged -- exit 0, no output. A check that fires on this gets ignored
    within the hour."""
    main, wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(
        main, "v641-dev0", "L1 w3-s1 PASS ok\nL2 w3-s1 PASS also ok\nL3 w3-s1 PASS still ok\n"
    )
    _write_ledger(wt, "v641-dev0", "L1 w3-s1 PASS ok\n")  # missing L2 and L3's rows
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], main, env)

    assert proc.returncode == 0, proc.stdout
    assert proc.stdout == ""


def test_ledger_check_absent_worktree_copy_is_not_a_finding(tmp_path: Path) -> None:
    """A linked worktree with NO ledger file at all is fine, not a finding
    -- exit 0."""
    main, _wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(main, "v641-dev0", "L1 w3-s1 PASS ok\n")
    # deliberately: no ledger file written under wt at all.
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], main, env)

    assert proc.returncode == 0, proc.stdout
    assert proc.stdout == ""


def test_ledger_check_json_output_shape_on_divergence(tmp_path: Path) -> None:
    main, wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(main, "v641-dev0", "L1 w3-s1 PASS ok\n")
    _write_ledger(wt, "v641-dev0", "L1 w3-s1 PASS ok\nL9 w9-s1 PASS extra row\n")
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0", "--json"], main, env)

    assert proc.returncode == 7
    payload = json.loads(proc.stdout)
    assert payload["run"] == "v641-dev0"
    assert payload["ok"] is False
    assert len(payload["divergences"]) == 1
    assert payload["divergences"][0]["row"] == "L9 w9-s1 PASS extra row"
    assert payload["divergences"][0]["worktree"] == str(wt.resolve())


def test_ledger_check_json_output_shape_clean(tmp_path: Path) -> None:
    main, wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(main, "v641-dev0", "L1 w3-s1 PASS ok\n")
    _write_ledger(wt, "v641-dev0", "L1 w3-s1 PASS ok\n")
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0", "--json"], main, env)

    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload == {"run": "v641-dev0", "divergences": [], "ok": True}


def test_ledger_check_from_inside_the_linked_worktree_still_finds_the_full_set(
    tmp_path: Path,
) -> None:
    """``ledger check`` invoked from INSIDE the linked worktree (not the
    primary) still enumerates every worktree via git's shared metadata and
    reaches the same exit 7 verdict -- cwd never matters to the result."""
    main, wt = _init_repo_with_worktree(tmp_path)
    _write_ledger(main, "v641-dev0", "L1 w3-s1 PASS ok\n")
    _write_ledger(wt, "v641-dev0", "L1 w3-s1 PASS ok\nL2 w3-s1 PASS worktree-only row\n")
    env = clean_env_dict()

    proc = _run_cli(["run", "ledger", "check", "v641-dev0"], wt, env)

    assert proc.returncode == 7
    assert "L2 w3-s1 PASS worktree-only row" in proc.stdout


# ==========================================================================
# ``shepherd run wave verify``.
# ==========================================================================
def test_wave_verify_exit_0_when_every_step_resolves_clean(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1", "W1-L1-S2")
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 PASS ok\nL1 w1-s2 PASS ok\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "W1-L1-S1\tPASS" in proc.stdout
    assert "W1-L1-S2\tPASS" in proc.stdout
    assert "FINDINGS" not in proc.stdout


def test_wave_verify_no_verdict_for_missing_rows_exits_6(work_dir: Path) -> None:
    """The #262 headline case: steps with zero matching ledger rows."""
    _write_lane_plan(work_dir, "v641-dev0", "lane-d", "W3-L4-S1", "W3-L4-S2", "W3-L4-S3")
    _write_ledger(work_dir, "v641-dev0", "")  # nothing recorded for lane 4 at all

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 6
    for step_id in ("W3-L4-S1", "W3-L4-S2", "W3-L4-S3"):
        assert f"{step_id}\t-\t-" in proc.stdout
        assert f"NO-VERDICT\t{step_id}:" in proc.stdout


def test_wave_verify_missing_ledger_file_is_all_no_verdict_not_a_crash(work_dir: Path) -> None:
    """No ``auditor-verdicts.txt`` at all (nothing recorded yet) is treated
    as an empty ledger -- every step reads NO-VERDICT, exit 6, never a
    crash or an exit-5 (the run/lane-plan directory DOES exist)."""
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 6
    assert "W1-L1-S1\t-\t-" in proc.stdout


def test_wave_verify_unresolved_verdict_last_redo_or_fail_exits_6(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1", "W1-L1-S2")
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 REDO still broken\nL1 w1-s2 FAIL outright\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 6
    assert "UNRESOLVED-VERDICT\tW1-L1-S1:" in proc.stdout
    assert "UNRESOLVED-VERDICT\tW1-L1-S2:" in proc.stdout


def test_wave_verify_redo_then_pass_resolves_clean_last_wins(work_dir: Path) -> None:
    """A cleared REDO -> PASS loop is the NORMAL shape of a lane that
    failed a step, was told to redo it, and passed on retry -- must exit 0,
    never report it as still-failing (first-wins would get this wrong)."""
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W3-L3-S1")
    _write_ledger(work_dir, "v641-dev0", "L3 w3-s1 REDO needs more work\nL3 w3-s1 PASS cleared on retry\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 0, proc.stdout
    assert "W3-L3-S1\tPASS\tL3 w3-s1 PASS cleared on retry" in proc.stdout


def test_wave_verify_orphan_verdict_for_row_naming_step_in_no_lane_plan(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W3-L1-S1")
    _write_ledger(work_dir, "v641-dev0", "L1 w3-s1 PASS ok\nL1 w3-s3 PASS a step no plan ever declared\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 6
    assert "ORPHAN-VERDICT\tL1 w3-s3: no matching step in any lane plan" in proc.stdout


def test_wave_verify_malformed_row_reported_not_crashed_on(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1")
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 PASS ok\nnot a valid ledger line\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 6
    assert "MALFORMED-ROW\tline 2:" in proc.stdout


def test_wave_verify_wave_filter_restricts_scope(work_dir: Path) -> None:
    """``--wave N`` restricts both the enumerated steps AND the ledger rows
    considered -- a step (and its verdict) in a DIFFERENT wave is entirely
    invisible, in both directions (no false NO-VERDICT, no false ORPHAN)."""
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1", "W2-L1-S1")
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 PASS wave one ok\nL9 w9-s1 PASS unrelated wave, no plan\n")

    wave_1 = _run_cli(["run", "wave", "verify", "v641-dev0", "--wave", "1"], work_dir)
    assert wave_1.returncode == 0, wave_1.stdout
    assert "W1-L1-S1\tPASS" in wave_1.stdout
    assert "W2-L1-S1" not in wave_1.stdout
    # The unrelated wave-9 row must NOT be reported as an orphan when we
    # only asked about wave 1 -- it's simply out of scope, not evidence of
    # a step missing from a plan.
    assert "w9-s1" not in wave_1.stdout

    wave_2 = _run_cli(["run", "wave", "verify", "v641-dev0", "--wave", "2"], work_dir)
    assert wave_2.returncode == 6  # W2-L1-S1 has no matching row -> NO-VERDICT
    assert "W2-L1-S1\t-\t-" in wave_2.stdout
    assert "W1-L1-S1" not in wave_2.stdout


def test_wave_verify_json_output_shape(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W1-L1-S1")
    _write_ledger(work_dir, "v641-dev0", "L1 w1-s1 PASS ok\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0", "--json"], work_dir)

    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["run"] == "v641-dev0"
    assert payload["wave"] is None
    assert payload["ok"] is True
    assert payload["findings"] == []
    assert payload["steps"] == [{"step": "W1-L1-S1", "verdict": "PASS", "line_no": 1, "raw": "L1 w1-s1 PASS ok"}]


def test_wave_verify_json_wave_field_reflects_the_filter(work_dir: Path) -> None:
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W3-L1-S1")
    _write_ledger(work_dir, "v641-dev0", "L1 w3-s1 PASS ok\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0", "--wave", "3", "--json"], work_dir)

    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["wave"] == 3


def test_wave_verify_missing_lanes_dir_exits_5(work_dir: Path) -> None:
    """A run that was never scaffolded (no ``lanes/`` dir at all, hence no
    ``run.json`` either) -- exit 5, not a crash."""
    proc = _run_cli(["run", "wave", "verify", "never-created"], work_dir)
    assert proc.returncode == 5


def test_wave_verify_invalid_run_id_exits_2(work_dir: Path) -> None:
    proc = _run_cli(["run", "wave", "verify", "../escape"], work_dir)
    assert proc.returncode == 2


def test_wave_verify_positional_verdict_field_never_grepped(work_dir: Path) -> None:
    """CLI-level regression test for the exact field incident #262's spec
    names: a PASS row whose free-form prose contains the word REDO must
    still resolve PASS end-to-end through the real CLI."""
    _write_lane_plan(work_dir, "v641-dev0", "lane-a", "W3-L3-S1")
    _write_ledger(work_dir, "v641-dev0", "L3 w3-s1 PASS REDO iter 2 cleared\n")

    proc = _run_cli(["run", "wave", "verify", "v641-dev0"], work_dir)

    assert proc.returncode == 0, proc.stdout
    assert "W3-L3-S1\tPASS\tL3 w3-s1 PASS REDO iter 2 cleared" in proc.stdout
